"""Tests for the executable patcher. The vanilla executable is not part of the
repository: set VF1_VANILLA_EXE to your own copy, or these tests skip."""
import hashlib
import json
import os
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "patcher"))
sys.path.insert(0, str(ROOT / "tools"))
import vf1_patcher  # noqa: E402

VANILLA = os.environ.get("VF1_VANILLA_EXE")


def vanilla_bytes():
    if not VANILLA or not Path(VANILLA).is_file():
        raise unittest.SkipTest("set VF1_VANILLA_EXE to the vanilla Virtual Families.exe")
    return Path(VANILLA).read_bytes()


class StubIsCurrent(unittest.TestCase):
    def test_stub_json_matches_the_assembler(self):
        try:
            import build_stub
        except ImportError:
            self.skipTest("keystone is not installed")
        self.assertEqual(build_stub.build(), json.loads(vf1_patcher.STUB.read_text()))


class PatchExecutable(unittest.TestCase):
    def setUp(self):
        self.vanilla = vanilla_bytes()
        self.patched = vf1_patcher.patch_executable(self.vanilla)
        self.pe = vf1_patcher.PE(self.patched)
        self.stub = json.loads(vf1_patcher.STUB.read_text())

    def test_two_new_sections_and_no_writable_code(self):
        secs = {s[0]: s for s in self.pe.sections()}
        self.assertIn(".vf1fun", secs)
        self.assertIn(".vf1fud", secs)
        o = self.pe.opt + self.pe.optsz
        for i in range(self.pe.nsec):
            name = bytes(self.pe.data[o + i * 40:o + i * 40 + 8]).rstrip(b"\0").decode()
            chars = struct.unpack_from("<I", self.pe.data, o + i * 40 + 36)[0]
            self.assertFalse(chars & 0x20000000 and chars & 0x80000000, f"{name} is writable and executable")

    def test_the_two_hooks_point_into_the_stub(self):
        site = self.pe.offset(vf1_patcher.HOOK_SITE)
        rel = struct.unpack_from("<i", self.patched, site + 1)[0]
        self.assertEqual(self.patched[site], 0xE8)
        self.assertEqual(vf1_patcher.HOOK_SITE + 5 + rel, int(self.stub["store_entry"], 16))
        slot = self.pe.offset(vf1_patcher.INIT_SLOT)
        self.assertEqual(struct.unpack_from("<I", self.patched, slot)[0], int(self.stub["init_entry"], 16))
        update = self.pe.offset(vf1_patcher.UPDATE_SLOT)
        self.assertEqual(struct.unpack_from("<I", self.patched, update)[0], int(self.stub["tick_entry"], 16))

    def test_nothing_else_changes_in_the_original_image(self):
        changed = [i for i, (a, b) in enumerate(zip(self.vanilla, self.patched)) if a != b]
        allowed = set(range(self.pe.offset(vf1_patcher.HOOK_SITE), self.pe.offset(vf1_patcher.HOOK_SITE) + 5))
        allowed |= set(range(self.pe.offset(vf1_patcher.INIT_SLOT), self.pe.offset(vf1_patcher.INIT_SLOT) + 4))
        allowed |= set(range(self.pe.offset(vf1_patcher.UPDATE_SLOT), self.pe.offset(vf1_patcher.UPDATE_SLOT) + 4))
        allowed |= set(range(self.pe.pe, self.pe.opt + self.pe.optsz + self.pe.nsec * 40))  # headers
        self.assertEqual([i for i in changed if i not in allowed], [])

    def test_checksum_is_valid(self):
        stored = struct.unpack_from("<I", self.patched, self.pe.opt + 64)[0]
        again = vf1_patcher.PE(self.patched)
        again.update_checksum()
        self.assertEqual(stored, struct.unpack_from("<I", again.data, again.opt + 64)[0])

    def test_refuses_anything_but_vanilla(self):
        with self.assertRaises(vf1_patcher.PatchError):
            vf1_patcher.patch_executable(self.patched)


if __name__ == "__main__":
    unittest.main()
