#!/usr/bin/env python3
"""Tests for MadeiraArchive.c (the zip/7z importer), run on Linux or macOS.

    python3 madeira/tests/archive/test_archive.py MADEIRA_DIR [7ZZ]

MADEIRA_DIR is a prepared Madeira tree (madeira/prepare.sh). 7ZZ is the 7-Zip
command-line program (7zz / 7z); without it the 7z cases are skipped.
The driver is built with AddressSanitizer and UBSan.
"""

import hashlib
import os
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
MADEIRA = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else None
SEVENZ = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else shutil.which("7zz") or shutil.which("7z")
del sys.argv[1:]

# Any two x86-64 binaries of the host (ELF is fine: 7-Zip filters ELF and PE alike).
X86_EXE = shutil.which("bash") or "/bin/sh"
X86_DLL = next((p for p in ("/usr/lib/x86_64-linux-gnu/libc.so.6", "/lib64/libc.so.6", shutil.which("python3"))
                if p and os.path.exists(p)), X86_EXE)

MA_OK, MA_ERR_FORMAT, MA_ERR_UNSUPPORTED, MA_ERR_ENCRYPTED = 0, 2, 3, 4
MA_ERR_CANCELLED, MA_ERR_UNSAFE_PATH, MA_ERR_CRC, MA_ERR_TOO_LARGE = 6, 7, 9, 10


def build(tmp):
    arc = os.path.join(MADEIRA, "app/Madeira/Archive")
    lz = os.path.join(arc, "lzma")
    srcs = [os.path.join(lz, f) for f in sorted(os.listdir(lz)) if f.endswith(".c")]
    out = os.path.join(tmp, "ma_cli")
    cmd = ["cc", "-g", "-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=undefined",
           # 7-Zip reads unaligned words on purpose (fine on x86-64 and arm64)
           "-fno-sanitize=alignment",
           "-DZ7_PPMD_SUPPORT", "-I" + arc, os.path.join(HERE, "ma_cli.c"),
           os.path.join(arc, "MadeiraArchive.c")] + srcs + ["-lz", "-o", out]
    if sys.platform == "darwin":
        cmd += ["-framework", "CoreFoundation"]
    subprocess.run(cmd, check=True)
    return out


def read(path):
    with open(path, "rb") as f:
        return f.read()


def write(path, data):
    with open(path, "wb" if isinstance(data, bytes) else "w") as f:
        f.write(data)


def tree(root):
    """{relative path: sha256 or 'dir'} for everything under root."""
    result = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for d in dirnames:
            result[os.path.relpath(os.path.join(dirpath, d), root)] = "dir"
        for f in filenames:
            p = os.path.join(dirpath, f)
            with open(p, "rb") as fh:
                result[os.path.relpath(p, root)] = hashlib.sha256(fh.read()).hexdigest()
    return result


def make_source(root):
    """A small Windows-style program folder: binaries, text, empty file and folder, CJK names."""
    os.makedirs(os.path.join(root, "Game/bin"))
    os.makedirs(os.path.join(root, "Game/存档"))
    os.makedirs(os.path.join(root, "Game/empty"))
    # Real x86-64 executables: 7-Zip picks BCJ/BCJ2 only for files it parses as code.
    shutil.copyfile(X86_EXE, os.path.join(root, "Game/game.exe"))
    shutil.copyfile(X86_DLL, os.path.join(root, "Game/bin/engine.dll"))
    with open(os.path.join(root, "Game/存档/说明.txt"), "w", encoding="utf-8") as f:
        f.write("中文说明\n" * 5000)
    with open(os.path.join(root, "Game/data.pak"), "wb") as f:
        f.write(bytes(random.Random(1).getrandbits(8) for _ in range(200000)) + b"\0" * 3000000)
    open(os.path.join(root, "Game/empty.txt"), "w").close()


@unittest.skipUnless(MADEIRA, "pass the prepared Madeira tree")
class ArchiveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.cli = build(cls.tmp)
        cls.src = os.path.join(cls.tmp, "src")
        make_source(cls.src)
        cls.expected = tree(cls.src)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def extract(self, archive, mem_mb=None, env=None):
        dest = tempfile.mkdtemp(dir=self.tmp)
        args = [self.cli, archive, dest] + ([str(mem_mb)] if mem_mb else [])
        p = subprocess.run(args, capture_output=True, text=True, env=dict(os.environ, **(env or {})))
        self.assertNotIn("Sanitizer", p.stderr, p.stderr)
        self.assertNotIn("runtime error", p.stderr, p.stderr)
        return p.returncode, p.stdout, dest

    def assertExtracts(self, archive, **kw):
        rc, out, dest = self.extract(archive, **kw)
        self.assertEqual(rc, MA_OK, out)
        self.assertEqual(tree(dest), self.expected)
        return dest

    def path(self, name):
        return os.path.join(self.tmp, name)

    # ------------------------------------------------------------- zip

    def zip_source(self, name, compression, **kw):
        p = self.path(name)
        with zipfile.ZipFile(p, "w", compression, **kw) as z:
            for dirpath, dirnames, filenames in os.walk(self.src):
                for d in dirnames:
                    rel = os.path.relpath(os.path.join(dirpath, d), self.src)
                    z.writestr(rel + "/", b"")
                for f in filenames:
                    full = os.path.join(dirpath, f)
                    z.write(full, os.path.relpath(full, self.src))
        return p

    def test_zip_deflate(self):
        self.assertExtracts(self.zip_source("d.zip", zipfile.ZIP_DEFLATED))

    def test_zip_stored(self):
        self.assertExtracts(self.zip_source("s.zip", zipfile.ZIP_STORED))

    def test_zip64(self):
        p = self.path("z64.zip")
        with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
            for dirpath, dirnames, filenames in os.walk(self.src):
                for d in dirnames:
                    z.writestr(os.path.relpath(os.path.join(dirpath, d), self.src) + "/", b"")
                for f in filenames:
                    full = os.path.join(dirpath, f)
                    with open(full, "rb") as fh, z.open(os.path.relpath(full, self.src), "w", force_zip64=True) as out:
                        out.write(fh.read())
        self.assertExtracts(p)

    def test_zip_gbk_names_without_utf8_flag(self):
        # Windows' built-in zip on a Chinese system writes GBK names with no flag.
        p = self.path("gbk.zip")
        gbk = "存档/说明.txt".encode("gbk")
        placeholder = "x" * len(gbk)
        with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(placeholder, "中文".encode("utf-8"))
        data = read(p).replace(placeholder.encode(), gbk)
        write(p, data)
        rc, out, dest = self.extract(p)
        self.assertEqual(rc, MA_OK, out)
        self.assertTrue(os.path.isfile(os.path.join(dest, "存档/说明.txt")), tree(dest))

    def test_zip_backslash_paths(self):
        p = self.path("bs.zip")
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("Game\\bin\\a.txt", b"a")
        rc, out, dest = self.extract(p)
        self.assertEqual(rc, MA_OK, out)
        self.assertEqual(read(os.path.join(dest, "Game/bin/a.txt")), b"a")

    def test_zip_path_traversal_is_refused(self):
        p = self.path("evil.zip")
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("ok.txt", b"ok")
            z.writestr("../evil.txt", b"x")
        rc, out, dest = self.extract(p)
        self.assertEqual(rc, MA_ERR_UNSAFE_PATH, out)
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(dest), "evil.txt")))

    def test_zip_absolute_and_drive_paths_stay_inside(self):
        p = self.path("abs.zip")
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("/etc/a.txt", b"a")
            z.writestr("C:\\Games\\b.txt", b"b")
        rc, out, dest = self.extract(p)
        self.assertEqual(rc, MA_OK, out)
        self.assertEqual(tree(dest).keys(), {"etc", "etc/a.txt", "Games", "Games/b.txt"})

    def test_zip_crc_mismatch(self):
        p = self.path("crc.zip")
        with zipfile.ZipFile(p, "w", zipfile.ZIP_STORED) as z:
            z.writestr("a.txt", b"hello world")
        data = bytearray(read(p))
        i = data.index(b"hello world")
        data[i] ^= 1
        write(p, bytes(data))
        rc, out, _ = self.extract(p)
        self.assertEqual(rc, MA_ERR_CRC, out)

    def test_cancel(self):
        rc, out, _ = self.extract(self.zip_source("c.zip", zipfile.ZIP_DEFLATED), env={"MA_CANCEL_AT": "1000"})
        self.assertEqual(rc, MA_ERR_CANCELLED, out)

    def test_not_an_archive(self):
        p = self.path("x.txt")
        write(p, "hello there")
        self.assertEqual(self.extract(p)[0], MA_ERR_FORMAT)

    def test_fuzzed_zip_never_crashes(self):
        base = read(self.zip_source("f.zip", zipfile.ZIP_DEFLATED))
        rnd = random.Random(7)
        for i in range(60):
            data = bytearray(base)
            for _ in range(rnd.randint(1, 20)):
                data[rnd.randrange(len(data))] = rnd.randrange(256)
            p = self.path("fz%d.zip" % i)
            write(p, bytes(data))
            rc, out, _ = self.extract(p)  # asserts there is no sanitizer report
            self.assertIn(rc, range(0, 11), out)

    # -------------------------------------------------------------- 7z

    def sevenz(self, name, *switches):
        p = self.path(name)
        subprocess.run([SEVENZ, "a", "-bd", "-y", p] + list(switches) + ["."], cwd=self.src,
                       check=True, capture_output=True)
        return p

    def methods(self, archive):
        out = subprocess.run([SEVENZ, "l", "-slt", archive], capture_output=True, text=True).stdout
        return {l.split(" = ", 1)[1] for l in out.splitlines() if l.startswith("Method = ") and l != "Method = "}

    @unittest.skipUnless(SEVENZ, "no 7-Zip command-line program")
    def test_7z_default_bcj_lzma2(self):
        p = self.sevenz("m5.7z", "-mx5")
        self.assertTrue(any("BCJ" in m and "BCJ2" not in m for m in self.methods(p)), self.methods(p))
        self.assertExtracts(p)

    @unittest.skipUnless(SEVENZ, "no 7-Zip command-line program")
    def test_7z_ultra_bcj2_streams(self):
        p = self.sevenz("m9.7z", "-mx9")
        self.assertTrue(any("BCJ2" in m for m in self.methods(p)), self.methods(p))
        # 1 MB is far below the solid block: BCJ2 must stream, not use memory.
        self.assertExtracts(p, mem_mb=1)

    @unittest.skipUnless(SEVENZ, "no 7-Zip command-line program")
    def test_7z_methods(self):
        for name, sw in [("lzma.7z", ["-m0=LZMA"]), ("copy.7z", ["-m0=Copy"]),
                         ("arm64.7z", ["-m0=ARM64", "-m1=LZMA2"]),
                         ("delta.7z", ["-m0=Delta:4", "-m1=LZMA2"]),
                         ("nonsolid.7z", ["-ms=off"]), ("x86lzma.7z", ["-m0=BCJ", "-m1=LZMA"])]:
            with self.subTest(name):
                self.assertExtracts(self.sevenz(name, *sw), mem_mb=1)

    @unittest.skipUnless(SEVENZ, "no 7-Zip command-line program")
    def test_7z_ppmd_uses_memory_path_with_limit(self):
        p = self.sevenz("ppmd.7z", "-m0=PPMd")
        self.assertExtracts(p)
        rc, out, _ = self.extract(p, mem_mb=1)
        self.assertEqual(rc, MA_ERR_TOO_LARGE, out)

    @unittest.skipUnless(SEVENZ, "no 7-Zip command-line program")
    def test_7z_encrypted(self):
        rc, out, _ = self.extract(self.sevenz("enc.7z", "-psecret"))
        self.assertEqual(rc, MA_ERR_ENCRYPTED, out)
        rc, out, _ = self.extract(self.sevenz("enc-names.7z", "-psecret", "-mhe=on"))
        self.assertEqual(rc, MA_ERR_UNSUPPORTED, out)

    @unittest.skipUnless(SEVENZ, "no 7-Zip command-line program")
    def test_zip_made_by_7zip_encrypted(self):
        rc, out, _ = self.extract(self.sevenz("enc.zip", "-tzip", "-psecret"))
        self.assertEqual(rc, MA_ERR_ENCRYPTED, out)

    @unittest.skipUnless(SEVENZ, "no 7-Zip command-line program")
    def test_fuzzed_7z_never_crashes(self):
        for src_name, sw in [("fz5.7z", ["-mx5"]), ("fz9.7z", ["-mx9"])]:
            base = read(self.sevenz(src_name, *sw))
            rnd = random.Random(11)
            for i in range(40):
                data = bytearray(base)
                for _ in range(rnd.randint(1, 10)):
                    data[rnd.randrange(32, len(data))] = rnd.randrange(256)
                p = self.path("%s.%d.7z" % (src_name, i))
                write(p, bytes(data))
                rc, out, _ = self.extract(p, mem_mb=64)
                self.assertIn(rc, range(0, 11), out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
