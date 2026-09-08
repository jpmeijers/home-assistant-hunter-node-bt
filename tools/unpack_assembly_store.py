"""Extract managed DLLs from a modern .NET Android assembly store payload.

The input is the raw ``payload`` ELF section whose first four bytes are XABA.
Compressed assemblies use Xamarin's 12-byte XALZ header and raw LZ4 blocks.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import struct
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

MAX_ASSEMBLY_BYTES = 64 * 1024 * 1024
MAX_STORE_BYTES = 256 * 1024 * 1024
MAX_TOTAL_OUTPUT_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True)
class AssemblyDescriptor:
    mapping_index: int
    data_offset: int
    data_size: int
    debug_data_offset: int
    debug_data_size: int
    config_data_offset: int
    config_data_size: int


def _output_size(data: bytes) -> int:
    """Validate declared sizes before allocating decompression buffers."""
    if data.startswith(b"XALZ"):
        if len(data) < 12:
            raise ValueError("truncated XALZ header")
        size = struct.unpack_from("<I", data, 8)[0]
    else:
        size = len(data)
    if not 0 < size <= MAX_ASSEMBLY_BYTES:
        raise ValueError("assembly exceeds output size limit or is empty")
    return size


def _decompress_xalz(data: bytes) -> bytes:
    output_size = _output_size(data)
    if not data.startswith(b"XALZ"):
        return data

    library_name = ctypes.util.find_library("lz4")
    if library_name is None:
        raise RuntimeError("liblz4 is required to unpack XALZ assemblies")
    lz4 = ctypes.CDLL(library_name)
    decompress = lz4.LZ4_decompress_safe
    decompress.argtypes = (
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
    )
    decompress.restype = ctypes.c_int

    compressed = data[12:]
    source = ctypes.create_string_buffer(compressed)
    output = ctypes.create_string_buffer(output_size)
    actual_size = decompress(source, output, len(compressed), output_size)
    if actual_size < 0:
        raise RuntimeError("liblz4 rejected an XALZ block")
    if actual_size != output_size:
        raise RuntimeError(
            f"XALZ size mismatch: expected {output_size}, got {actual_size}"
        )
    return output.raw


def _destination(output_dir: Path, name: str) -> Path:
    """Reject unsafe paths and existing files, including symlinks."""
    path = Path(name)
    if (
        not name
        or "\0" in name
        or "\\" in name
        or path.is_absolute()
        or PureWindowsPath(name).drive
        or any(part in {"", ".", ".."} for part in name.split("/"))
    ):
        raise ValueError("unsafe assembly name")
    destination = output_dir / path
    if not destination.resolve().is_relative_to(output_dir):
        raise ValueError("assembly destination escapes output directory")
    current = output_dir
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("assembly destination contains a symlink")
    if destination.exists():
        raise ValueError("assembly destination already exists")
    return destination


def unpack(store_path: Path, output_dir: Path) -> None:
    with store_path.open("rb") as source:
        store = source.read(MAX_STORE_BYTES + 1)
    if len(store) > MAX_STORE_BYTES:
        raise ValueError("assembly store exceeds size limit")
    if len(store) < 20:
        raise ValueError("truncated assembly store header")
    magic, version, entry_count, index_count, index_size = struct.unpack_from(
        "<4sIIII", store
    )
    if magic != b"XABA":
        raise ValueError(f"{store_path} is not an Android assembly store")

    header_size = 20
    descriptor_size = struct.calcsize("<7I")
    descriptors_offset = header_size + index_size
    names_offset = descriptors_offset + entry_count * descriptor_size
    if names_offset > len(store) or not index_count:
        raise ValueError("invalid assembly store index or descriptors")
    descriptors = [
        AssemblyDescriptor(
            *struct.unpack_from("<7I", store, descriptors_offset + i * descriptor_size)
        )
        for i in range(entry_count)
    ]

    names: list[str] = []
    cursor = names_offset
    for _ in range(entry_count):
        if cursor + 4 > len(store):
            raise ValueError("truncated assembly name length")
        name_size = struct.unpack_from("<I", store, cursor)[0]
        cursor += 4
        if cursor + name_size > len(store):
            raise ValueError("truncated assembly name")
        names.append(store[cursor: cursor + name_size].decode("utf-8"))
        cursor += name_size

    output_dir = output_dir.resolve()
    destinations: set[Path] = set()
    entries: list[tuple[str, AssemblyDescriptor]] = []
    total_output = 0
    # Validate every entry before creating any output, including entries after
    # otherwise valid files in a malicious store.
    for name, descriptor in zip(names, descriptors, strict=True):
        destination = _destination(output_dir, name)
        if destination in destinations:
            raise ValueError("duplicate assembly destination")
        destinations.add(destination)
        start = descriptor.data_offset
        end = start + descriptor.data_size
        if start < cursor or end > len(store):
            raise ValueError("assembly data lies outside the store payload")
        total_output += _output_size(store[start:end])
        if total_output > MAX_TOTAL_OUTPUT_BYTES:
            raise ValueError("assemblies exceed total output size limit")
        entries.append((name, descriptor))

    output_dir.mkdir(parents=True, exist_ok=True)
    for name, descriptor in entries:
        destination = _destination(output_dir, name)
        start = descriptor.data_offset
        end = start + descriptor.data_size
        assembly = _decompress_xalz(store[start:end])
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as output:
            output.write(assembly)
        print(f"{name}: {len(assembly)} bytes")

    index_entry_size = index_size // index_count
    print(
        f"extracted {entry_count} assemblies; format=0x{version:08x}; "
        f"index_entry_size={index_entry_size}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("store", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    unpack(args.store, args.output_dir)


if __name__ == "__main__":
    main()
