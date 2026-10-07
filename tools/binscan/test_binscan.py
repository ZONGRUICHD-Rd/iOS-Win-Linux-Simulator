#!/usr/bin/env python3
"""Tests for binscan. Fixtures are built with clang + lld when they exist.

Run: python3 -m unittest tools/binscan/test_binscan.py
"""

import os
import shutil
import subprocess
import tempfile
import unittest

import binscan

HAVE_TOOLS = all(shutil.which(t) for t in ("clang", "ld.lld", "lld-link", "llvm-dlltool"))

AARCH64_ASM = r"""
    .text
    .globl _start
_start:
    mrs  x1, tpidr_el0
    msr  tpidr_el0, x1
    mrs  x2, midr_el1
    mrs  x3, cntvct_el0
    adr  x4, 1f
    br   x4
1:  mov  x8, #93
    mov  x0, #0
    svc  #0
    ret
    .data
value: .quad 42
"""

X86_C = "void _start(void) { for (;;) ; }\n"

PE_C = r"""
__declspec(dllimport) long D3D11CreateDevice(void);
__declspec(dllimport) void *EasyAntiCheat_Init(void);
int mainCRTStartup(void) { return (int)D3D11CreateDevice() + (int)(long long)EasyAntiCheat_Init(); }
"""


def run(*cmd, cwd):
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True)


@unittest.skipUnless(HAVE_TOOLS, "needs clang, ld.lld, lld-link and llvm-dlltool")
class BinscanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        d = cls.tmp
        with open(os.path.join(d, "a.S"), "w") as f:
            f.write(AARCH64_ASM)
        with open(os.path.join(d, "x.c"), "w") as f:
            f.write(X86_C)
        with open(os.path.join(d, "pe.c"), "w") as f:
            f.write(PE_C)
        with open(os.path.join(d, "d3d11.def"), "w") as f:
            f.write("LIBRARY d3d11.dll\nEXPORTS\nD3D11CreateDevice\n")
        with open(os.path.join(d, "eac.def"), "w") as f:
            f.write("LIBRARY EasyAntiCheat_x64.dll\nEXPORTS\nEasyAntiCheat_Init\n")

        aarch64 = ("clang", "--target=aarch64-linux-gnu", "-nostdlib", "-static", "-fuse-ld=lld")
        # 16 KiB-safe layout, as current Debian arm64 links
        run(*aarch64, "-Wl,-z,max-page-size=65536", "a.S", "-o", "a64", cwd=d)
        # 4 KiB layout with code and data packed together
        run(*aarch64, "-Wl,-z,max-page-size=4096", "-Wl,--no-rosegment", "-Wl,-z,norelro",
            "-Wl,-z,separate-loadable-segments", "a.S", "-o", "a64-4k", cwd=d)
        run(*aarch64, "-Wl,-z,max-page-size=4096", "-Wl,-N", "a.S", "-o", "a64-omagic", cwd=d)
        run("clang", "--target=x86_64-linux-gnu", "-nostdlib", "-static", "-fuse-ld=lld",
            "x.c", "-o", "x64", cwd=d)
        run("llvm-dlltool", "-m", "i386:x86-64", "-d", "d3d11.def", "-l", "d3d11.lib", cwd=d)
        run("llvm-dlltool", "-m", "i386:x86-64", "-d", "eac.def", "-l", "eac.lib", cwd=d)
        run("clang", "--target=x86_64-pc-windows-msvc", "-c", "pe.c", "-o", "pe.obj", cwd=d)
        run("lld-link", "/entry:mainCRTStartup", "/subsystem:windows", "/nodefaultlib",
            "pe.obj", "d3d11.lib", "eac.lib", "/out:game.exe", cwd=d)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def path(self, name):
        return os.path.join(self.tmp, name)

    def test_aarch64_instruction_classes(self):
        r = binscan.scan(self.path("a64"))
        self.assertEqual(r["arch"], "aarch64")
        self.assertEqual(r["kind"], "executable")
        self.assertEqual(r["svc_sites"], 1)
        self.assertEqual(r["tpidr_el0_reads"], 1)
        self.assertEqual(r["tpidr_el0_writes"], 1)
        self.assertEqual(r["sysreg_reads_xnu_traps"], {"MIDR_EL1": 1})
        self.assertEqual(r["indirect_branches"], 2)  # br + ret
        self.assertEqual(r["pages_16k_wx_after_relro"], 0)
        self.assertIn("native", r["path_on_ios"])

    def test_omagic_layout_mixes_code_and_data(self):
        # -N puts text and data in one RWX segment: every page is W+X.
        r = binscan.scan(self.path("a64-omagic"))
        self.assertGreater(r["pages_16k_wx_after_relro"], 0)
        self.assertTrue(any("16 KiB page" in n for n in r["notes"]))

    def test_page_plan_on_4k_layout(self):
        r = binscan.scan(self.path("a64-4k"))
        self.assertEqual(r["min_load_align"], 4096)
        # code and data share no 4 KiB page here; the 16 KiB plan decides
        self.assertIn(r["pages_16k_wx"], (0, 1))

    def test_page_plan_relro_is_excluded(self):
        phdrs = [
            dict(type=binscan.PT_LOAD, flags=binscan.PF_X, vaddr=0x0, memsz=0x1000),
            dict(type=binscan.PT_LOAD, flags=binscan.PF_W, vaddr=0x2000, memsz=0x800),
            dict(type=binscan.PT_GNU_RELRO, flags=0, vaddr=0x2000, memsz=0x800),
        ]
        self.assertEqual(binscan.page_plan(phdrs), (1, 0))
        # RELRO ends on the 16 KiB boundary; the data after it is on a page of its own
        phdrs[1]["memsz"] = 0x4000
        phdrs[2]["memsz"] = 0x2000
        self.assertEqual(binscan.page_plan(phdrs), (1, 0))
        # RELRO ends inside the code's page, so late-writable data shares it
        phdrs[2]["memsz"] = 0x400
        self.assertEqual(binscan.page_plan(phdrs), (1, 1))

    def test_x86_64_elf_goes_to_fex(self):
        r = binscan.scan(self.path("x64"))
        self.assertEqual(r["arch"], "x86-64")
        self.assertIn("FEX", r["path_on_ios"])

    def test_pe_imports_graphics_and_anticheat(self):
        r = binscan.scan(self.path("game.exe"))
        self.assertEqual(r["format"], "PE")
        self.assertEqual(r["arch"], "x86-64")
        self.assertEqual(r["subsystem"], "GUI")
        self.assertFalse(r["dotnet"])
        self.assertIn("d3d11.dll", r["imports"])
        self.assertEqual(r["graphics"], ["Direct3D 11 (DXMT)"])
        self.assertEqual(r["anticheat_hints"], ["easyanticheat_x64.dll"])
        self.assertIn("Wine", r["path_on_ios"])

    def test_rejects_other_files(self):
        p = self.path("text.txt")
        with open(p, "w") as f:
            f.write("hello")
        with self.assertRaises(binscan.ScanError):
            binscan.scan(p)


if __name__ == "__main__":
    unittest.main()
