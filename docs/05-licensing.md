# 05 · 许可证

本仓库自有代码：**GPL-3.0-or-later**（见 `LICENSE`）。选择理由：与 Madeira（GPL-3.0-or-later）、
iSH（GPL-3.0）、Wine（LGPL-2.1+）、FEX/DXMT（MIT）都能合并，便于把 Windows 方向的改动回馈给 Madeira。

| 组件 | 许可证 | 能否和本仓库代码进同一个程序 |
|---|---|---|
| Madeira 及其 fork 中的改动 | GPL-3.0-or-later + Converter 例外 | ✅ |
| Wine | LGPL-2.1-or-later | ✅（须满足重链接义务，见 Madeira `docs/BUILDING.md`） |
| FEX-Emu、DXMT 上游 | MIT | ✅ |
| iSH | GPL-3.0 | ✅（参考/借用其 syscall 层） |
| StikJIT | MPL-2.0 | ✅（文件级 copyleft） |
| idevice | MIT | ✅ |
| StikDebug | AGPL-3.0 | 作为独立 App 使用即可；不要把它的代码并进来 |
| **QEMU** | **GPLv2** | ❌ **不能**与 GPLv3 代码合并。P2 的 VM 必须是 **单独的 App 构建** |
| Husk | GPL-2.0-or-later | 可以参考设计；若借用代码，在 GPLv3 程序中按 “or later” 取 GPLv3 |
| UTM 的 App 代码（CocoaSpice 等） | Apache-2.0 | 与 GPLv2（QEMU）不兼容，P2 中不要使用 |
| LLVM（含 LFI） | Apache-2.0 with LLVM exception | ✅ 与 GPLv3 兼容 |
| Metal Shader Converter | Apple 专有 | 只能经 Madeira 的例外条款使用 |
| 微软 VC++ 运行库 | 微软专有 | 不分发，由用户自备 |

P2（QEMU）那个独立构建中，我们为它写的胶水代码可以采用 GPL-2.0-or-later，以便与 QEMU 合并。

（这不是法律意见。正式发布前请逐个组件核对。）
