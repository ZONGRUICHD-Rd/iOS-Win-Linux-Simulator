# iOS-Win-Linux-Simulator

在 **iPhone 18 Pro（A20 Pro / 12 GB / iOS 27）** 上，免越狱运行：

- **Windows 软件和游戏**（x86/x64 PE，经 Wine + FEX + Metal）
- **Linux（Ubuntu / Debian）**（arm64 用户态，以及完整虚拟机）

> 状态：**调研与设计阶段**。目前仓库里有调研文档、路线图和一个可用的分析工具（`tools/binscan`），
> 还没有能装到手机上的 App。

## 一页结论

| 问题 | 结论 |
|---|---|
| 能不能做？ | 能。iOS 27 下，侧载 + 调试器 JIT + 内存授权，三件事凑齐就能跑翻译器和模拟器 |
| JIT 怎么来？ | iPhone 18 Pro 出厂 iOS 27，有 TXM，只能用 StikDebug/StikJIT 的 **断点协议**，而且 JIT 区域 **只能申请一次** |
| 内存怎么办？ | 用 GetMoreRam 给 App ID 加 increased-memory-limit（免费账号已在 iPhone 18 Pro / iOS 27 实测可行）；extended-virtual-addressing 待验证 |
| Windows | **基于 Madeira，不重造**。它已经能在 iPhone 上跑 Windows 游戏；我们做实测、分诊和补空白（Vulkan 等） |
| Linux | **没人做好，是本项目的主战场**。先用 QEMU 整机 VM 快速跑起来，再做 “动态 LFI” 原生运行时追求性能 |

## 文档

| | |
|---|---|
| [00 · 参考项目分析](docs/00-reference-projects.md) | GetMoreRam、StikDebug、Madeira 源码级分析；补充 Husk、UTM、iSH |
| [01 · 目标平台](docs/01-platform-iphone18pro-ios27.md) | iPhone 18 Pro / iOS 27 的硬约束：JIT、进程、内存、16K 页、TLS、图形、签名 |
| [02 · Windows 方向](docs/02-windows-path.md) | 在 iPhone 18 Pro 上运行 Madeira 的步骤，兼容性分诊，Madeira 的空白 |
| [03 · Linux 方向](docs/03-linux-path.md) | 四条技术路线对比，推荐方案，B2 “动态 LFI” 设计，Debian 二进制实测数据 |
| [04 · 路线图](docs/04-roadmap.md) | P0 设备探针 → P1 Windows → P2 QEMU VM → P3 原生运行时 → P4 体验 |
| [05 · 许可证](docs/05-licensing.md) | 各组件许可证兼容性；为什么 QEMU 必须单独构建 |

## 架构草图

```
┌──────────────────────────── iPhone 18 Pro · iOS 27 ────────────────────────────┐
│                                                                                │
│  Windows App（Madeira）        Linux App（本项目）             Linux VM App      │
│  ┌───────────────────┐        ┌──────────────────────────┐   ┌──────────────┐  │
│  │ Wine ARM64EC      │        │ Linux syscall 层          │   │ QEMU TCG     │  │
│  │ FEX (x86→arm64)   │        │ arm64→arm64 翻译器         │   │ (GPLv2,      │  │
│  │ DXMT / d3d12→Metal│        │  + LFI 式 4 GiB 进程槽位   │   │  单独构建)    │  │
│  └───────────────────┘        │ FEXCore（x86-64 ELF）     │   │ Debian/Ubuntu│  │
│                               └──────────────────────────┘   └──────────────┘  │
│  ─────────────────────── 共同地基 ────────────────────────────────────────────  │
│  一次性 JIT 区域（brk #0xf00d 协议，内置 StikJIT / StikDebug，LocalDevVPN）       │
│  内存授权（increased-memory-limit，extended-virtual-addressing）                 │
│  单进程（不能 fork/exec），16 KiB 页，只有 Metal                                 │
└────────────────────────────────────────────────────────────────────────────────┘
```

## 工具

`tools/binscan`：判断一个 ELF/PE 在 iOS 上走哪条路、要处理什么（`svc`、TLS、受限系统寄存器、16K 页、
图形 API、反作弊……）。

```sh
python3 tools/binscan/binscan.py /path/to/Game.exe /path/to/debian/bin/bash
```

## 参考项目

- [hugeBlack/GetMoreRam](https://github.com/hugeBlack/GetMoreRam)
- [StikDebug/StikDebug](https://github.com/StikDebug/StikDebug)、[StikDebug/StikJIT](https://github.com/StikDebug/StikJIT)
- [willfaust/Madeira](https://github.com/willfaust/Madeira)
- [Leviidev/Husk](https://github.com/Leviidev/Husk)
- [utmapp/UTM](https://github.com/utmapp/UTM)、[ish-app/ish](https://github.com/ish-app/ish)
- [LFI: Lightweight Fault Isolation](https://www.scs.stanford.edu/~zyedidia/docs/papers/lfi.pdf)、[LLVM LFI 文档](https://releases.llvm.org/22.1.0/docs/LFI.html)

## 许可证

GPL-3.0-or-later，见 [LICENSE](LICENSE) 和 [docs/05-licensing.md](docs/05-licensing.md)。
