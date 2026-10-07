# 01 · 目标平台：iPhone 18 Pro / iOS 27

## 硬件

| 项 | 值 | 来源 |
|---|---|---|
| 型号标识 | `iPhone19,2`（V63AP） | theapplewiki |
| SoC | A20 Pro，TSMC N2（2 nm） | 多家媒体 |
| 内存 | 12 GB | 多家媒体 |
| 出厂系统 | iOS 27（24A427 / 24A8428） | MacRumors / theapplewiki |
| 发布 | 2026-09-09 | — |

**出厂 iOS 27，不能降级**。所以所有 “iOS 26 以前” 的 JIT 技巧（AltJIT、TrollStore 的 Allow JIT、
iOS 17 的旧 JIT 方式）都不适用。唯一的路是 **TXM 下的调试器 JIT**。

12 GB 内存是这代机器最大的利好：Madeira 和 Husk 的文档都提到可用内存是游戏/虚拟机的首要瓶颈。
但 **App 实际能用多少由 jetsam 决定**，需要 increased-memory-limit 授权，具体数值必须在设备上测
（`os_proc_available_memory()`）。

## 约束清单

每一条都标了 **已确认**（读源码或文档得出）或 **待实测**（必须在 iPhone 18 Pro 上验证）。

### 1. 可执行内存只能由调试器授予（已确认）

- iOS 27 上全部设备都有 TXM。
- 流程：App 带 `get-task-allow` 签名 → 调试器附加（`CS_DEBUGGED`）→ App 用 `brk #0xf00d` 请求
  `JIT26PrepareRegion` → 拿到 RX 区域，自己 `vm_remap` 出 RW 别名 → `JIT26Detach`。
- **区域是一次性的**。detach 之后再请求就是 SIGTRAP 崩溃。所有翻译器的代码缓存必须在启动时一次性划好。
- 准备时间 ∝ 区域大小（每 16 KiB 一个 gdb 包）。Husk 实测 256 MiB = 749 ms（iPhone18,1 / iOS 27.0）。
- 获得调试器的方式：内置 StikJIT（App 扩展充当调试器进程，iOS 27 可 App 内配对）或外部 StikDebug。
  都依赖 **LocalDevVPN**（App Store 上的回环 VPN），**蜂窝数据下不可用**，需要 Wi-Fi 或完全断网。
- 待实测：在 iPhone 18 Pro 上能准备的最大区域、所需时间；StikDebug#476（iOS 27.0 附加失败）是否影响内置 StikJIT。
- **在 LiveContainer 里只有 StikDebug 一条路**（内置 StikJIT 需要 App 扩展），所以 StikDebug#476 的影响更直接。见 [06](06-livecontainer.md)。

### 2. 没有硬件虚拟化（已确认）

Hypervisor.framework 不对第三方 iOS App 开放（需要 `com.apple.private.hypervisor`，即越狱）。
所以 **整机虚拟机只能用 QEMU TCG 软件模拟**，CPU 和 MMU 都是软件的，比原生慢一个数量级以上。

### 3. 不能创建进程（已确认）

不能 `fork`、不能 `exec`、不能 `posix_spawn` 自己带的程序。“另一个系统” 的所有进程只能活在 **一个 iOS 进程** 里：

- Windows：Madeira 把 wineserver 变成线程，Wine 的多进程场景受限。
- Linux：这是最难的问题。Linux 用户态大量依赖 `fork`/`exec`（shell、apt、dpkg 维护脚本……）。
  多个 Linux 进程挤在同一个地址空间里，必须给每个进程分配不同的地址区间并做隔离。见 [03](03-linux-path.md)。

### 4. 内存与地址空间

| 授权 | 作用 | 获取 |
|---|---|---|
| `com.apple.developer.kernel.increased-memory-limit` | 提高 jetsam 上限 | 免费账号可加（GetMoreRam 方式）**已实测**：iPhone 18 Pro / iOS 27，2026-10 |
| `com.apple.developer.kernel.extended-virtual-addressing` | 用户地址空间 63 GB → 512 GB | 免费账号能否加 **待实测** |

**测试 extended-virtual-addressing**（不需要写新代码）：

1. 把 GetMoreRam 的 `AppIDViewModel.swift` 里那一行改成
   `capabilities: ["INCREASED_MEMORY_LIMIT", "EXTENDED_VIRTUAL_ADDRESSING"]`，自己编译侧载；
   或者用任何能按 ID 打开 App ID 能力的工具。服务器拒绝时会直接返回错误，这本身就是答案。
2. 若服务器接受，从侧载工具 **重新安装** Madeira。
3. 看 Madeira 的诊断日志（`DeviceDiagnostics`，启动时写入），其中有两项：
   - `profile-extended-va=1`：描述文件里确实带上了授权；
   - `address-map=[...) 512GB`：内核确实给了扩展地址空间（没有时是 `63GB`）。

两项都满足才算成功。注意 Apple 可能只在付费账号上开放这个能力（网上有 “需要付费证书” 的说法，未经证实）。

另外：

- JIT 内存可以用 `mach_memory_entry_ownership(..., VM_LEDGER_FLAG_NO_FOOTPRINT)` 标记为不计入 footprint
  （MeloNX / Madeira 的做法，私有 API）。
- Madeira 在进程启动时抢占 `0x140000000` 附近的低地址窗口（Windows PE 的默认基址），防止系统库先占掉。
  Linux 侧同理：非 PIE 程序要 `0x400000` 起的地址。

### 5. 16 KiB 页（已确认）

iOS 所有 arm64 设备页大小为 16 KiB。按 4 KiB 链接的 ELF 可能把代码和可写数据放进同一个 16 KiB 页。
好消息：用 `tools/binscan` 实测 Debian 12 arm64 的 busybox、bash、coreutils、python3.11、libc 都按
64 KiB 对齐（`min_load_align = 65536`），**没有一个 W+X 冲突页**。

### 6. 线程寄存器（待实测）

- Linux aarch64 的 glibc/musl/bionic 都用 `TPIDR_EL0` 存线程指针；Darwin 用 `TPIDRRO_EL0`。
  如果 XNU 在线程切换和信号处理时保留 `TPIDR_EL0`，Linux 代码的 TLS 可以原样工作；否则要改写每一处访问。
  `binscan` 在 Debian libc.so.6 里数到 1485 处读取。
- x18：Darwin 保留 x18，普通 Linux 代码不用它，但 shadow call stack 会用。

### 7. 系统寄存器（已确认，有对策）

Linux 内核会为 EL0 模拟 `MIDR_EL1`、`ID_AA64*_EL1` 的读取（HWCAP_CPUID），XNU 不会 → SIGILL。
`binscan` 在 Debian 的 `ld-linux-aarch64.so.1` 和 busybox 里都找到了 `mrs MIDR_EL1`（glibc 的
`init_cpu_features`）。对策：我们的运行时构造 auxv 时 **不设置 HWCAP_CPUID**，glibc 就不会去读；
动态翻译器还可以直接把这些指令改写成返回伪造值。

### 8. 图形（已确认）

只有 Metal。没有原生 OpenGL/Vulkan。可用的转换层：

| 源 API | 到 Metal |
|---|---|
| D3D9/10/11 | DXMT（Madeira 在用） |
| D3D12 | madeira-d3d12 + Metal Shader Converter |
| Vulkan | MoltenVK（Husk 在用） |
| OpenGL ES | ANGLE（Husk 在用） |
| 桌面 OpenGL | 没有成熟方案（Mesa Zink → Vulkan → MoltenVK 理论可行） |

### 9. 签名与后台（已确认）

- 免费 Apple ID：签名 7 天过期，需每周刷新（SideStore/AltStore 自动续签）；同时只能激活少量侧载 App。
- 必须开发证书签名（`get-task-allow`），企业/发布证书签的包无法被调试器附加 → 没有 JIT。
- App 进入后台会被挂起；调试器进程会被 iOS 的 cpulimit 杀掉（AetherPS4 有记录）。
  所以 JIT 必须在前台一次准备好，再 detach。
- 因为需要调试器，这类 App **不可能上架 App Store**。

## P0 设备探针（待写）

在 iPhone 18 Pro 上用一个极小的探针 App 一次性测完上面所有 “待实测” 项，输出一份 JSON 报告：

1. 授权：`increased-memory-limit` / `extended-virtual-addressing` 是否生效；`os_proc_available_memory()`。
2. 地址空间：`TASK_VM_INFO` 的 `[min, max)`（63 GB 还是 512 GB）；能否在 `0x400000`、`0x140000000` 预留。
3. JIT：内置 StikJIT 准备 256 MiB / 1 GiB / 2 GiB 区域的耗时与成功率；生成代码返回 42。
4. `TPIDR_EL0`：四个线程各写不同值，数百次上下文切换和一次信号处理后是否仍保持。
5. x18 是否被保留。
6. 能否在 JIT 区域内按 “carve” / “place” 两种布局放置 ELF 映像（Husk 的两种方案）。
