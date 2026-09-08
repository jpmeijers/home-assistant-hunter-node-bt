"""Untrusted assembly stores must not write outside their output directory."""

import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.unpack_assembly_store import MAX_ASSEMBLY_BYTES, _decompress_xalz, unpack


def store_bytes(entries):
    names = b"".join(struct.pack("<I", len(name.encode())) + name.encode() for name, _ in entries)
    offset = 20 + 28 * len(entries) + len(names)
    descriptors = b""
    payload = b""
    for _, data in entries:
        descriptors += struct.pack("<7I", 0, offset, len(data), 0, 0, 0, 0)
        offset += len(data)
        payload += data
    return struct.pack("<4sIIII", b"XABA", 1, len(entries), 1, 0) + descriptors + names + payload


class ExtractorSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "store"
        self.output = self.root / "output"

    def extract(self, entries):
        self.source.write_bytes(store_bytes(entries))
        unpack(self.source, self.output)

    def test_valid_nested_assembly(self):
        self.extract([("nested/test.dll", b"ordinary assembly bytes")])
        self.assertEqual((self.output / "nested/test.dll").read_bytes(), b"ordinary assembly bytes")

    def test_rejects_all_unsafe_names_before_writing(self):
        for name in ("../escape", str(self.root / "escape"), "nested/../../escape",
                     "C:/escape", "nested\\escape", "", ".", "a\0b"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.extract([("safe.dll", b"safe"), (name, b"marker")])
            self.assertFalse(self.output.exists())
            self.assertFalse((self.root / "escape").exists())

    def test_rejects_symlink_parents_and_leaves(self):
        self.output.mkdir()
        outside = self.root / "outside"
        outside.mkdir()
        (self.output / "link").symlink_to(outside, target_is_directory=True)
        (self.output / "leaf.dll").symlink_to(outside / "missing")
        for name in ("link/escape.dll", "leaf.dll"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.extract([(name, b"marker")])
        self.assertEqual(list(outside.iterdir()), [])

    def test_refuses_overwrites_and_duplicate_names(self):
        self.output.mkdir()
        existing = self.output / "existing.dll"
        existing.write_bytes(b"original")
        with self.assertRaises(ValueError):
            self.extract([("existing.dll", b"replacement")])
        self.assertEqual(existing.read_bytes(), b"original")
        with self.assertRaises(ValueError):
            self.extract([("new.dll", b"first"), ("new.dll", b"second")])
        self.assertFalse((self.output / "new.dll").exists())

    def test_rejects_decompression_bomb_before_allocation(self):
        with patch("tools.unpack_assembly_store.ctypes.create_string_buffer") as allocate:
            with self.assertRaises(ValueError):
                _decompress_xalz(struct.pack("<4sII", b"XALZ", 0, MAX_ASSEMBLY_BYTES + 1))
            allocate.assert_not_called()

    def test_rejects_truncated_store_and_payload(self):
        valid = store_bytes([("test.dll", b"assembly")])
        for length in (0, 19, 25, len(valid) - 1):
            self.source.write_bytes(valid[:length])
            with self.subTest(length=length), self.assertRaises(ValueError):
                unpack(self.source, self.output)
            self.assertFalse(self.output.exists())
