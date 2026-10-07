#!/usr/bin/env python3
"""binscan: how hard is it to run this binary on an iPhone (iOS 27, TXM)?

Reads ELF (Linux) and PE (Windows) files without any third-party module and
reports what a runtime on iOS would have to deal with:

  ELF / aarch64  -> the native Linux path (docs/03-linux-path.md): raw `svc`
                    sites, TPIDR_EL0 use, system registers XNU does not let
                    EL0 read, 16 KiB page layout, and how many loads, stores
                    and indirect branches a sandboxing translator rewrites.
  ELF / x86      -> the FEXCore path.
  PE             -> the Wine + FEX + DXMT path (docs/02-windows-path.md):
                    architecture, .NET, graphics API and anti-cheat imports.

The instruction counts come from a linear sweep of the executable segments,
so data embedded in code is counted too: treat them as estimates.

Usage: binscan.py [--json] FILE...
"""

import json
import os
import struct
import sys
from collections import Counter

IOS_PAGE = 0x4000  # iOS uses 16 KiB pages on every arm64 device

EM_386, EM_X86_64, EM_AARCH64 = 3, 62, 183
ELF_MACHINES = {EM_386: "i386", EM_X86_64: "x86-64", EM_AARCH64: "aarch64", 40: "arm", 243: "riscv"}
PT_LOAD, PT_DYNAMIC, PT_INTERP, PT_GNU_RELRO = 1, 2, 3, 0x6474E552
PF_X, PF_W = 1, 2
DT_NEEDED, DT_STRTAB = 1, 5

PE_MACHINES = {0x14C: "i386", 0x8664: "x86-64", 0xAA64: "arm64", 0xA641: "arm64ec", 0x1C4: "arm"}

# System registers a Linux aarch64 program may read at EL0 that XNU also
# serves. Linux additionally emulates reads of MIDR_EL1 and the ID_AA64*
# registers (HWCAP_CPUID); XNU does not, so those reads raise SIGILL.
# Encoding: op0:op1:CRn:CRm:op2 packed as bits [20:5] of the MRS opcode.
def _sysreg(op0, op1, crn, crm, op2):
    return ((op0 - 2) << 14) | (op1 << 11) | (crn << 7) | (crm << 3) | op2

SYSREG_NAMES = {
    _sysreg(3, 3, 13, 0, 2): "TPIDR_EL0",
    _sysreg(3, 3, 13, 0, 3): "TPIDRRO_EL0",
    _sysreg(3, 3, 14, 0, 0): "CNTFRQ_EL0",
    _sysreg(3, 3, 14, 0, 1): "CNTPCT_EL0",
    _sysreg(3, 3, 14, 0, 2): "CNTVCT_EL0",
    _sysreg(3, 3, 0, 0, 1): "CTR_EL0",
    _sysreg(3, 3, 0, 0, 7): "DCZID_EL0",
    _sysreg(3, 3, 4, 4, 0): "FPCR",
    _sysreg(3, 3, 4, 4, 1): "FPSR",
    _sysreg(3, 3, 4, 2, 0): "NZCV",
    _sysreg(3, 3, 4, 2, 1): "DAIF",
    _sysreg(3, 0, 0, 0, 0): "MIDR_EL1",
    _sysreg(3, 0, 0, 0, 5): "MPIDR_EL1",
    _sysreg(3, 0, 0, 4, 0): "ID_AA64PFR0_EL1",
    _sysreg(3, 0, 0, 4, 1): "ID_AA64PFR1_EL1",
    _sysreg(3, 0, 0, 6, 0): "ID_AA64ISAR0_EL1",
    _sysreg(3, 0, 0, 6, 1): "ID_AA64ISAR1_EL1",
    _sysreg(3, 0, 0, 7, 0): "ID_AA64MMFR0_EL1",
    _sysreg(3, 0, 0, 7, 1): "ID_AA64MMFR1_EL1",
    _sysreg(3, 0, 0, 5, 0): "ID_AA64DFR0_EL1",
}
EL0_SAFE = {"TPIDR_EL0", "TPIDRRO_EL0", "CNTFRQ_EL0", "CNTPCT_EL0", "CNTVCT_EL0",
            "CTR_EL0", "DCZID_EL0", "FPCR", "FPSR", "NZCV", "DAIF"}

# DLLs whose import says which graphics path a Windows program needs.
GRAPHICS_DLLS = {
    "d3d9.dll": "Direct3D 9 (DXMT)",
    "d3d10.dll": "Direct3D 10 (DXMT)",
    "d3d10_1.dll": "Direct3D 10 (DXMT)",
    "d3d11.dll": "Direct3D 11 (DXMT)",
    "d3d12.dll": "Direct3D 12 (madeira-d3d12)",
    "dxgi.dll": "DXGI",
    "opengl32.dll": "OpenGL (no Metal path in Madeira yet)",
    "vulkan-1.dll": "Vulkan (no path in Madeira yet; MoltenVK is a candidate)",
    "ddraw.dll": "DirectDraw (wined3d)",
    "d3d8.dll": "Direct3D 8 (needs a d3d8->d3d9 layer)",
}
ANTICHEAT_HINTS = ("easyanticheat", "beclient", "battleye", "vgk", "xigncode", "nprotect",
                   "gameguard", "eac_", "anticheat")


class ScanError(Exception):
    pass


# --------------------------------------------------------------------- ELF

def _cstr(data, off):
    end = data.find(b"\0", off)
    return data[off:end if end >= 0 else len(data)].decode("utf-8", "replace")


def _elf_headers(data):
    if data[:4] != b"\x7fELF":
        raise ScanError("not an ELF file")
    if data[4] != 2:
        raise ScanError("32-bit ELF: only 64-bit programs are in scope")
    if data[5] != 1:
        raise ScanError("big-endian ELF")
    (e_type, e_machine, _ver, e_entry, e_phoff, e_shoff, _flags, _ehsize,
     e_phentsize, e_phnum, e_shentsize, e_shnum, e_shstrndx) = struct.unpack_from(
        "<HHIQQQIHHHHHH", data, 16)
    phdrs = []
    for i in range(e_phnum):
        p_type, p_flags, p_offset, p_vaddr, _paddr, p_filesz, p_memsz, p_align = \
            struct.unpack_from("<IIQQQQQQ", data, e_phoff + i * e_phentsize)
        phdrs.append(dict(type=p_type, flags=p_flags, offset=p_offset, vaddr=p_vaddr,
                          filesz=p_filesz, memsz=p_memsz, align=p_align))
    sections = []
    if e_shoff and e_shnum and e_shstrndx < e_shnum:
        raw = [struct.unpack_from("<IIQQQQIIQQ", data, e_shoff + i * e_shentsize)
               for i in range(e_shnum)]
        stroff = raw[e_shstrndx][4]
        sections = [_cstr(data, stroff + s[0]) for s in raw]
    return dict(type=e_type, machine=e_machine, entry=e_entry, phdrs=phdrs, sections=sections)


def _vaddr_to_offset(phdrs, vaddr):
    for p in phdrs:
        if p["type"] == PT_LOAD and p["vaddr"] <= vaddr < p["vaddr"] + p["filesz"]:
            return p["offset"] + vaddr - p["vaddr"]
    return None


def _elf_dynamic(data, phdrs):
    dyn = next((p for p in phdrs if p["type"] == PT_DYNAMIC), None)
    if not dyn:
        return []
    entries, strtab = [], None
    for off in range(dyn["offset"], dyn["offset"] + dyn["filesz"], 16):
        tag, val = struct.unpack_from("<qQ", data, off)
        if tag == 0:
            break
        if tag == DT_STRTAB:
            strtab = val
        entries.append((tag, val))
    stroff = _vaddr_to_offset(phdrs, strtab) if strtab is not None else None
    if stroff is None:
        return []
    return [_cstr(data, stroff + v) for t, v in entries if t == DT_NEEDED]


def page_plan(phdrs, page=IOS_PAGE):
    """Lay the PT_LOAD segments out on `page`-sized pages, as a loader would.

    Returns (pages_mixing_w_and_x, same_but_ignoring_relro): a page that holds
    executable bytes and writable bytes would have to be W+X at once. Bytes
    under PT_GNU_RELRO are written only while relocating, through the RW
    alias, so the second count leaves them out.
    """
    relro = [(p["vaddr"], p["vaddr"] + p["memsz"]) for p in phdrs if p["type"] == PT_GNU_RELRO]
    x_pages, w_pages, w_pages_late = set(), set(), set()
    for p in phdrs:
        if p["type"] != PT_LOAD or p["memsz"] == 0:
            continue
        first, last = p["vaddr"] // page, (p["vaddr"] + p["memsz"] - 1) // page
        if p["flags"] & PF_X:
            x_pages.update(range(first, last + 1))
        if p["flags"] & PF_W:
            w_pages.update(range(first, last + 1))
            # writable bytes that stay writable after relocation
            start, end = p["vaddr"], p["vaddr"] + p["memsz"]
            for lo, hi in relro:
                if lo <= start < hi:
                    start = min(hi, end)
            if start < end:
                w_pages_late.update(range(start // page, (end - 1) // page + 1))
    return len(x_pages & w_pages), len(x_pages & w_pages_late)


def scan_aarch64_code(data, phdrs):
    """Linear sweep over executable PT_LOAD bytes, classifying each word."""
    c = Counter()
    sysregs = Counter()
    for p in phdrs:
        if p["type"] != PT_LOAD or not p["flags"] & PF_X:
            continue
        start = p["offset"] + (-p["offset"] % 4)
        end = p["offset"] + p["filesz"]
        for (w,) in struct.iter_unpack("<I", data[start:end - (end - start) % 4]):
            c["insns"] += 1
            if w & 0xFFE0001F == 0xD4000001:
                c["svc"] += 1
            elif w & 0xFFF00000 == 0xD5300000:  # MRS
                name = SYSREG_NAMES.get((w >> 5) & 0x7FFF, "S%04x" % ((w >> 5) & 0x7FFF))
                sysregs[name] += 1
            elif w & 0xFFF00000 == 0xD5100000:  # MSR (register)
                if (w >> 5) & 0x7FFF == _sysreg(3, 3, 13, 0, 2):
                    c["msr_tpidr_el0"] += 1
            elif w & 0xFFFFFC1F in (0xD61F0000, 0xD63F0000):  # BR, BLR
                c["indirect_branch"] += 1
            elif w & 0xFFFFFC1F == 0xD65F0000:  # RET
                c["ret"] += 1
            # loads and stores: op0 bits x1x0 at [28:25]
            if (w >> 25) & 0b0101 == 0b0100:
                c["mem"] += 1
    return c, sysregs


def scan_elf(path, data):
    h = _elf_headers(data)
    arch = ELF_MACHINES.get(h["machine"], "machine %d" % h["machine"])
    phdrs = h["phdrs"]
    interp = next((data[p["offset"]:p["offset"] + p["filesz"]].rstrip(b"\0").decode()
                   for p in phdrs if p["type"] == PT_INTERP), None)
    loads = [p for p in phdrs if p["type"] == PT_LOAD]
    r = dict(path=path, format="ELF", arch=arch,
             kind={2: "executable", 3: "shared object / PIE"}.get(h["type"], "type %d" % h["type"]),
             interpreter=interp, needed=_elf_dynamic(data, phdrs),
             min_load_align=min((p["align"] for p in loads), default=0))
    mixed, mixed_late = page_plan(phdrs)
    r["pages_16k_wx"] = mixed
    r["pages_16k_wx_after_relro"] = mixed_late
    secs = set(h["sections"])
    r["go_runtime"] = bool(secs & {".go.buildinfo", ".gopclntab", ".note.go.buildid"})
    notes = []

    if h["machine"] == EM_AARCH64:
        r["path_on_ios"] = "native aarch64 Linux runtime (translator + Linux syscall layer)"
        c, sysregs = scan_aarch64_code(data, phdrs)
        r["insns"] = c["insns"]
        r["svc_sites"] = c["svc"]
        r["tpidr_el0_reads"] = sysregs.get("TPIDR_EL0", 0)
        r["tpidr_el0_writes"] = c["msr_tpidr_el0"]
        r["indirect_branches"] = c["indirect_branch"] + c["ret"]
        r["mem_access_ratio"] = round(c["mem"] / c["insns"], 3) if c["insns"] else 0.0
        known = set(SYSREG_NAMES.values())
        trapping = {k: v for k, v in sysregs.items() if k in known and k not in EL0_SAFE}
        r["sysreg_reads_xnu_traps"] = dict(sorted(trapping.items()))
        # MRS words naming registers outside the table are almost always data
        # swept up with the code; count them so a real one is not hidden.
        r["sysreg_reads_unrecognised"] = sum(v for k, v in sysregs.items() if k not in known)
        if c["svc"]:
            notes.append("%d raw svc sites: each one must reach the Linux syscall layer, "
                         "not XNU (x8 holds the Linux number, XNU reads x16)" % c["svc"])
        if r["tpidr_el0_reads"] or r["tpidr_el0_writes"]:
            notes.append("uses TPIDR_EL0 for TLS: fine if XNU preserves it per thread "
                         "(measure on device), otherwise rewrite each access")
        if trapping:
            notes.append("reads %s, which Linux emulates for EL0 and XNU does not: clear "
                         "HWCAP_CPUID in the auxv so libc skips them, or trap and emulate"
                         % ", ".join(sorted(trapping)))
        if mixed_late:
            notes.append("%d 16 KiB page(s) hold code and writable data together: needs "
                         "write emulation or relinking with -z max-page-size=16384" % mixed_late)
        if r["go_runtime"]:
            notes.append("Go runtime: issues raw syscalls itself and relies on signals "
                         "for preemption")
    elif h["machine"] in (EM_X86_64, EM_386):
        r["path_on_ios"] = "FEXCore (x86 -> arm64 JIT) + the same Linux syscall layer"
        if h["machine"] == EM_386:
            notes.append("32-bit x86: FEX handles it, but needs a 32-bit address layout")
    else:
        r["path_on_ios"] = "unsupported architecture"
    r["notes"] = notes
    return r


# ---------------------------------------------------------------------- PE

def scan_pe(path, data):
    if data[:2] != b"MZ":
        raise ScanError("not a PE file")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        raise ScanError("MZ without a PE header (DOS program)")
    machine, nsec, _ts, _sym, _nsym, opt_size, chars = struct.unpack_from("<HHIIIHH", data, pe + 4)
    opt = pe + 24
    magic = struct.unpack_from("<H", data, opt)[0]
    if magic == 0x20B:
        subsystem = struct.unpack_from("<H", data, opt + 68)[0]
        ndirs_off, dirs_off = opt + 108, opt + 112
    elif magic == 0x10B:
        subsystem = struct.unpack_from("<H", data, opt + 68)[0]
        ndirs_off, dirs_off = opt + 92, opt + 96
    else:
        raise ScanError("unknown optional header magic 0x%x" % magic)
    ndirs = struct.unpack_from("<I", data, ndirs_off)[0]
    dirs = [struct.unpack_from("<II", data, dirs_off + 8 * i) for i in range(min(ndirs, 16))]
    secs = []
    for i in range(nsec):
        s = opt + opt_size + 40 * i
        name = data[s:s + 8].rstrip(b"\0").decode("latin-1")
        vsize, va, rsize, roff = struct.unpack_from("<IIII", data, s + 8)
        secs.append((name, va, max(vsize, rsize), roff, rsize))

    def rva(r):
        for _n, va, size, roff, rsize in secs:
            if va <= r < va + size and r - va < rsize:
                return roff + r - va
        return None

    imports = []
    if len(dirs) > 1 and dirs[1][0]:
        off = rva(dirs[1][0])
        while off is not None and off + 20 <= len(data):
            name_rva = struct.unpack_from("<I", data, off + 12)[0]
            if name_rva == 0:
                break
            noff = rva(name_rva)
            if noff is not None:
                imports.append(_cstr(data, noff).lower())
            off += 20

    arch = PE_MACHINES.get(machine, "machine 0x%x" % machine)
    r = dict(path=path, format="PE", arch=arch,
             kind="DLL" if chars & 0x2000 else "executable",
             subsystem={2: "GUI", 3: "console"}.get(subsystem, str(subsystem)),
             dotnet=len(dirs) > 14 and dirs[14][0] != 0,
             imports=imports)
    r["graphics"] = sorted({GRAPHICS_DLLS[d] for d in imports if d in GRAPHICS_DLLS})
    lowered = [d for d in imports] + [s[0].lower() for s in secs]
    r["anticheat_hints"] = sorted({d for d in lowered if any(h in d for h in ANTICHEAT_HINTS)})
    notes = []
    if arch == "x86-64":
        r["path_on_ios"] = "Wine (ARM64EC) + FEX: guest code translated, Wine native"
    elif arch == "i386":
        r["path_on_ios"] = "Wine WoW64 + FEX (32-bit)"
    elif arch in ("arm64", "arm64ec"):
        r["path_on_ios"] = "Wine arm64: runs natively, no translation"
    else:
        r["path_on_ios"] = "unsupported architecture"
    if r["dotnet"]:
        notes.append(".NET assembly: needs Wine Mono (or a native .NET runtime)")
    if r["anticheat_hints"]:
        notes.append("kernel/user anti-cheat imports: expect it not to run under Wine")
    if any("Vulkan" in g or "OpenGL" in g for g in r["graphics"]):
        notes.append("graphics API with no Metal path in Madeira today")
    r["notes"] = notes
    return r


# -------------------------------------------------------------------- main

def scan(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] == b"\x7fELF":
        return scan_elf(path, data)
    if data[:2] == b"MZ":
        return scan_pe(path, data)
    raise ScanError("neither ELF nor PE")


def _print_human(r):
    print("%s" % r["path"])
    skip = {"path", "notes", "imports", "needed"}
    for k, v in r.items():
        if k in skip or v is None or v is False or v == [] or v == {}:
            continue
        print("  %-26s %s" % (k, v))
    deps = r.get("needed") or r.get("imports")
    if deps:
        print("  %-26s %s" % ("needed" if "needed" in r else "imports", ", ".join(deps)))
    for n in r["notes"]:
        print("  - " + n)


def main(argv):
    as_json = "--json" in argv
    files = [a for a in argv if a != "--json"]
    if not files:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    results, status = [], 0
    for path in files:
        try:
            results.append(scan(path))
        except (ScanError, OSError, struct.error) as e:
            results.append(dict(path=path, error=str(e)))
            status = 1
    if as_json:
        json.dump(results, sys.stdout, indent=2)
        print()
    else:
        for r in results:
            if "error" in r:
                print("%s\n  error: %s" % (r["path"], r["error"]))
            else:
                _print_human(r)
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
