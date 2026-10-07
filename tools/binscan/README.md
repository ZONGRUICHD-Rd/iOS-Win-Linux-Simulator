# binscan

判断一个 Linux（ELF）或 Windows（PE）二进制在 iPhone（iOS 27，TXM）上要走哪条路、会遇到什么问题。
纯 Python 3，无第三方依赖。

```sh
python3 tools/binscan/binscan.py [--json] FILE...
```

## 输出

**ELF / aarch64**（原生 Linux 运行时，见 `docs/03-linux-path.md`）

| 字段 | 含义 |
|---|---|
| `svc_sites` | 内联 `svc` 的数量，每一处都必须被导向 Linux syscall 层 |
| `tpidr_el0_reads` / `_writes` | 用 TPIDR_EL0 做 TLS 的位置 |
| `sysreg_reads_xnu_traps` | 读 Linux 会代为模拟、XNU 不会的系统寄存器（MIDR_EL1、ID_AA64*） |
| `sysreg_reads_unrecognised` | 表外的 MRS 编码，几乎都是代码段中被扫到的数据 |
| `indirect_branches` | `br` / `blr` / `ret`，动态翻译器要查表的地方 |
| `mem_access_ratio` | 访存指令占比，LFI 式改写要处理的部分 |
| `min_load_align`、`pages_16k_wx*` | 按 16 KiB 页布局后，代码和可写数据同页的页数（第二个数排除 RELRO） |

**ELF / x86** → FEXCore 路线。**PE** → Wine 路线，给出架构、.NET、图形 API、反作弊导入。

指令统计是对可执行段的线性扫描，代码中的数据也会被计入，结果是估计值。

## 测试

```sh
cd tools/binscan && python3 -m unittest -v test_binscan
```

需要 `clang`、`ld.lld`、`lld-link`、`llvm-dlltool` 来生成测试用的 aarch64 ELF、x86-64 ELF 和 Windows PE；缺少时测试会跳过。

## 复现 docs/03 中的 Debian 数据

```sh
mkdir debs && cd debs
curl -sSO https://deb.debian.org/debian/pool/main/b/bash/bash_5.2.15-2+b13_arm64.deb
mkdir bash && (cd bash && ar x ../bash_5.2.15-2+b13_arm64.deb && tar xf data.tar.xz)
python3 ../tools/binscan/binscan.py bash/bin/bash
```

其余几个包同理：`busybox-static_1.35.0-4+deb12u1+b1`、`coreutils_9.1-1`、
`python3.11-minimal_3.11.2-6+deb12u8`、`libc6_2.36-9+deb12u14`（均为 bookworm arm64）。
