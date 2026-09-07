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
from pathlib import Path


@dataclass(frozen=True)
class AssemblyDescriptor:
    mapping_index: int
    data_offset: int
    data_size: int
    debug_data_offset: int
    debug_data_size: int
    config_data_offset: int
    config_data_size: int


def _decompress_xalz(data: bytes) -> bytes:
    magic, _descriptor_index, output_size = struct.unpack_from("<4sII", data)
    if magic != b"XALZ":
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


def unpack(store_path: Path, output_dir: Path) -> None:
    store = store_path.read_bytes()
    magic, version, entry_count, index_count, index_size = struct.unpack_from(
        "<4sIIII", store
    )
    if magic != b"XABA":
        raise ValueError(f"{store_path} is not an Android assembly store")

    header_size = 20
    descriptor_size = struct.calcsize("<7I")
    descriptors_offset = header_size + index_size
    names_offset = descriptors_offset + entry_count * descriptor_size
    descriptors = [
        AssemblyDescriptor(
            *struct.unpack_from("<7I", store, descriptors_offset + i * descriptor_size)
        )
        for i in range(entry_count)
    ]

    names: list[str] = []
    cursor = names_offset
    for _ in range(entry_count):
        name_size = struct.unpack_from("<I", store, cursor)[0]
        cursor += 4
        names.append(store[cursor: cursor + name_size].decode("utf-8"))
        cursor += name_size

    output_dir.mkdir(parents=True, exist_ok=True)
    for name, descriptor in zip(names, descriptors, strict=True):
        start = descriptor.data_offset
        end = start + descriptor.data_size
        assembly = _decompress_xalz(store[start:end])
        destination = output_dir / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(assembly)
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
