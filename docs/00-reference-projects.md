# 00 · 参考项目分析

调研日期：2026-10-07。三个指定项目都克隆下来逐个读了源码，不只是看 README。
调研中发现了 Husk，它和本项目的 Linux 方向高度重合，也一并收进来。

| 项目 | 一句话 | 对我们的意义 |
|---|---|---|
| [GetMoreRam](https://github.com/hugeBlack/GetMoreRam) | 用免费 Apple ID 给侧载 App 的 App ID 加上 “Increased Memory Limit” 能力 | 解决 **内存上限**（jetsam） |
| [StikDebug](https://github.com/StikDebug/StikDebug) | 在手机本机上当调试器，替侧载 App 打开 **JIT** | 解决 **可执行内存**，没有它就跑不了任何翻译器或模拟器 |
| [Madeira](https://github.com/willfaust/Madeira) | Wine + FEX-Emu + DXMT，在免越狱 iPhone 上跑 Windows PC 游戏 | **Windows 方向基本已经有人做完**，我们应该站在它上面 |
| [Husk](https://github.com/Leviidev/Husk)（补充） | 在 iPhone 上跑 Android：QEMU 整机虚拟化 + 原生 “翻译层” | **Linux 方向的最佳参考**：QEMU-on-iOS 和 “原生跑 arm64 Linux 代码” 两条路它都在走 |

---

## 1. GetMoreRam

**代码量很小**（十几个 Swift 文件），本身就是 [StosSign](https://github.com/stossy11/StosSign) 的一层 UI 外壳。

关键逻辑全部在 `AppIDViewModel.swift`：

```swift
AppleAPI.shared.updateAppID(appID, capabilities: ["INCREASED_MEMORY_LIMIT"], team: team, session: session)
```

流程：

1. 用你签侧载 App 的那个 Apple ID 登录 Apple 开发者服务（anisette 数据的获取代码来自 SideStore）。
2. 列出该 team 下所有 App ID。
3. 给目标 App ID 打开 `INCREASED_MEMORY_LIMIT` 能力。
4. 用 SideStore/AltStore **重新安装** 目标 App。新的 provisioning profile 里就带上了
   `com.apple.developer.kernel.increased-memory-limit` 授权（entitlement）。

**要点**

- 免费账号也能给 App ID 加这个能力，**项目作者已用免费账号实测成功（2026-10）**。这正是 Madeira 设置页里 “Memory+” 绿勾的来源。
- 另一个同样关键的授权是 `com.apple.developer.kernel.extended-virtual-addressing`。没有它，
  用户态地址空间到 `0xfc0000000`（63 GB）为止；有了它可到 512 GB（Madeira `EntitlementChecker.swift`
  里有记录）。这对 Linux 方向的多进程设计至关重要（见 [03](03-linux-path.md)）。
  GetMoreRam 只申请 `INCREASED_MEMORY_LIMIT`（代码里写死），所以上面的实测 **不涵盖** 它。
  它的能力 ID 是 `EXTENDED_VIRTUAL_ADDRESSING`（StosSign 里已有常量 `capabilityExtendedVirtualAddressing`），
  **免费账号能不能加上，尚未验证**。测试方法见 [01](01-platform-iphone18pro-ios27.md#4-内存与地址空间)。
- 本项目可以直接内置同样的能力（StosSign 方式），而不是让用户再装一个 App。

## 2. StikDebug

iOS 17.4+ 的本机调试器 / JIT 开启工具，基于 Rust 库 [idevice](https://github.com/jkcoxson/idevice)。AGPL-3.0。

**工作原理**

- 通过 **LocalDevVPN** 建立的回环隧道，连到本机的 `lockdownd`（`10.7.0.1:62078`），用 **配对文件**
  （pairing file）认证，挂载 Developer Disk Image，然后启动 `debugserver` 附加到目标 App。
- 进程被调试时内核设置 `CS_DEBUGGED`，从而允许可执行的动态代码页。目标 App 必须是
  `get-task-allow` 签名（开发证书签名，侧载都满足）。

**TXM（iOS 26+）下的新协议**——这是整个生态现在的地基

`ProcessInfo+TXM.swift` 判定哪些设备有 TXM（Trusted Execution Monitor）：

- iOS 26：A15 及更新的 iPhone（硬件号 ≥ iPhone14,2）；
- **iOS 27：除 `iPad8,11/12` 外全部设备**。iPhone 18 Pro 出厂即 iOS 27，所以必然是 TXM。

有 TXM 时，“附加一下调试器，然后自己 mmap RWX” 的老办法不再成立。新的做法是一个
**由断点构成的 RPC**（`Scripts/universal.js`）：

```c
// App 侧：x16 = 命令号，x0/x1 = 参数，返回值写回 x0
void  JIT26Detach(void)                       { asm("mov x16,#0; brk #0xf00d; ret"); }
void* JIT26PrepareRegion(void *addr, size_t n){ asm("mov x16,#1; brk #0xf00d; ret"); }
void  BreakSendJITScript(char *s, size_t n)   { asm("mov x16,#2; brk #0xf00d; ret"); }
```

调试器侧的 JS 脚本循环 `c`（继续）→ 捕获 `brk` → 读 x16 分派：

- `PrepareRegion(0, size)`：发 gdb-remote 包 `_M<size>,rx` 让 debugserver 在目标进程里分配 RX 内存，
  再调用原生的 `prepare_memory_region`：**对每个 16 KiB 页通过调试器写 1 个字节**。被调试器写过的页，
  之后 App 自己就能通过 `vm_remap` 出来的 RW 别名去写。
- App 拿到 RX 地址后自己 `vm_remap` 一个 RW 别名，之后写代码走 RW、执行走 RX，不再需要调试器。
- `Detach`：调试器离开。**之后再触发 `brk` 就是真正的 SIGTRAP，进程直接挂。**

**由此得出的设计铁律**：JIT 区域是 **一次性** 的。启动时一次申请够，之后永远不再申请。
QEMU 的 TCG（`tb-size` 固定、满了就 flush）天然适合；FEX、DBT 类翻译器也要按这个约束设计。

**风险**：[StikDebug#476](https://github.com/StikDebug/StikDebug/issues/476)（2026-10-05）报告
StikDebug 3.1.13 在 iOS 27.0 上对所有 App 附加失败（E96），被以 “not planned” 关闭。
而 Madeira 和 Husk 的 **内置 StikJIT**（见下）在 iOS 27 上报告可用。所以在 iPhone 18 Pro 上
应优先走内置 StikJIT 路线，StikDebug 作为备选。

## 3. Madeira

“在 iPhone 上免越狱运行未修改的 Windows PC 游戏”。GPL-3.0-or-later + Metal Shader Converter 例外条款。
截至 2026-10 仍在活跃开发，iOS 26+，开发主力机是近代 Pro 系列 iPhone。

**分层**

| 层 | 作用 |
|---|---|
| FEX-Emu（fork） | x86/x86-64 → ARM64 JIT 翻译 |
| Wine 11.4（fork，**ARM64EC** 构建） | Windows API。Wine 自身原生运行，只有游戏代码被翻译；32 位走 WoW64 |
| DXMT（fork） | D3D9/10/11 → Metal |
| madeira-d3d12（自研） | D3D12 → Metal，运行时用 Apple Metal Shader Converter 转 DXIL |
| FFmpeg / VideoToolbox / AudioToolbox | 过场动画与音频 |

**值得学习的工程决策**

1. **单进程**：iOS App 不能启动其他程序，所以连 `wineserver` 都是作为线程跑的
   （`build/wineserver`，`WineServerBridge.m`）。这是任何 “在 iOS 上跑另一个 OS 的程序” 的共同前提。
2. **JIT 两条路**：外部 StikDebug（`stikdebug://enable-jit?bundle-id=…&pid=…&script…`）或
   **内置 StikJIT**：一个 classic app extension（`MadeiraJITHelper.appex`，挂在 `com.apple.ar.viewer`
   扩展点上）作为第二个进程充当调试器——一个进程无法同步调试自己。**iOS 27 上还能在 App 内完成配对，
   完全不需要电脑**（App 扮演局域网里的 “电脑”，用户在 设置 › 隐私与安全性 › 开发者模式 里输入配对码）。
3. **JIT 内存分配器**（`JITAllocator.c`）：`mach_make_memory_entry_64` + 两次 `vm_map` 做 RW/RX 双映射；
   用私有 API `mach_memory_entry_ownership(..., VM_LEDGER_FLAG_NO_FOOTPRINT)`（来自 MeloNX）让 JIT
   内存 **不计入 jetsam 内存上限**；进程启动时用 constructor 抢占低地址窗口 `0x140000000`，避免后续碎片化。
4. **授权**：`increased-memory-limit` + `get-task-allow`（+ 可选 `extended-virtual-addressing`），
   启动时自检并在设置页显示状态。
5. **蜂窝网络问题**：LocalDevVPN 回环只在 Wi-Fi 或无网络时可用，蜂窝数据下不通；Madeira 用一个
   快捷指令（Shortcut）自动切 VPN/蜂窝。

**对 Linux 方向的意外收获**：`FEXBridge.mm` 里已经有一个 ELF 加载器，把一个静态链接的 x86-64 Linux
“Hello World” 用 FEXCore 在 iPhone 上跑通了（自带极简 syscall 处理）。说明
“FEXCore + 自己的 Linux syscall 层” 跑 x86-64 Linux 程序在 iOS 上是可行的。

**局限**：只有 Debug 配置能跑游戏（Release 会崩）；没有 Vulkan/OpenGL → Metal 的路径；
反作弊游戏不可能；部分 64 位游戏要用户自备 VC++ 运行库。

## 4. Husk（补充调研）

在 iPhone 上跑 Android App，GPL-2.0-or-later。两种模式：

- **Emulation**：QEMU 10.0.12（UTM 的 fork，可编成 `libqemu-aarch64-softmmu.dylib` 在进程内运行）
  + TCG 整机模拟 LineageOS。iOS 不给第三方 App 用 Hypervisor.framework，所以只能 TCG（软件 MMU，慢）。
- **Translation Layer**（实验中）：APK 里的 arm64 `.so` **直接在 CPU 上原生执行**，Husk 自己提供
  bionic libc / JNI / GLES(ANGLE) / Vulkan(MoltenVK) 等。不启动 Android。

它的文档里有大量对我们 Linux 方向直接可复用的结论：

- **JIT 自测在 iPhone18,1 / iOS 27.0 上通过**：256 MiB 区域 749 ms 准备完毕。
- 准备时间与区域大小线性相关（每 16 KiB 页一个 gdb 包）：1 GiB = 65,536 个包。区域大小要实测权衡。
- 原生跑 arm64 ELF 的难点清单：16 KiB 页（4 KiB 链接的库代码与可写数据同页）、
  `TPIDR_EL0`（Linux/Android 用它做 TLS，Darwin 用 `TPIDRRO_EL0`，需要在设备上测 XNU 是否保存它）、
  x18、内联的 `svc #0`（Linux 用 x8 传号，XNU 读 x16）、结构体布局/errno/信号号差异。
- **许可证陷阱**：QEMU 是 GPLv2-only，与 Apache-2.0、GPLv3 不能链进同一个程序。

## 5. 其他现状

- **UTM**：v4.7.x 发布说明写明 iOS 26 破坏了 AltJIT 等工具的 JIT 方式，建议需要 JIT 的用户不要升级。
  UTM SE（无 JIT，TCG 解释器）能跑但非常慢。iPhone 18 Pro 无法降级，因此 UTM 原版目前不是可用方案。
- **iSH**：i386 用户态解释器 + Linux syscall 翻译层，跑 Alpine。它在 2025 年按欧盟 DMA 向 Apple
  申请 JIT 被拒。它的 “Linux syscall → XNU” 内核层是我们 Linux 原生方案的重要参考（GPL-3.0，可兼容）。

## 结论

1. **JIT 是一切的前提**，在 iPhone 18 Pro（iOS 27）上只能用 “TXM 断点协议 + 一次性区域”。
   内置 StikJIT（含 App 内配对）是首选。
2. **内存授权**（increased-memory-limit，最好再加 extended-virtual-addressing）是第二前提，GetMoreRam 的做法可以直接内置。
3. **Windows：不重造轮子**，基于 Madeira。详见 [02](02-windows-path.md)。
4. **Linux：这是还没人做好的部分**，也是本仓库主要的原创工作。详见 [03](03-linux-path.md)。
