# 03 · Linux（Ubuntu / Debian）方向

目标：在 iPhone 18 Pro 上跑 Ubuntu/Debian 的 arm64 用户态——shell、apt、编程语言、服务，最终是图形程序。

这部分 **没有现成可用的方案**：UTM 原版的 JIT 在 iOS 26+ 失效；UTM SE 和 iSH 是解释器，很慢；
iSH 还是 i386。所以这是本仓库的主要原创工作。

## 四条技术路线

### A. 整机虚拟机：QEMU TCG

和 UTM、Husk 的 Emulation 模式一样：QEMU 编成 dylib 在进程内运行，TCG 用调试器授予的一次性
JIT 区域（`tcg_splitwx_diff` 正好对应 RX/RW 双映射），启动 Ubuntu/Debian arm64 云镜像。

- ✅ **兼容性完美**：真内核、systemd、fork、Docker 都行。
- ✅ **已被证明可行**：Husk 在 iOS 27 上已把 QEMU 10.0.12 编成 iOS dylib、JIT 自测通过，Alpine 正在启动中。
- ❌ **慢**：软件 MMU，每次访存都要查 TLB。同架构（arm64 on arm64）并不省掉这部分开销。
- ❌ 内存：guest RAM 加 QEMU 自身都算在 App 头上。
- ❌ 许可证：QEMU 是 GPLv2，不能和 GPLv3 代码（Madeira 的改动、我们的代码）链接进同一个程序。

### B. 原生用户态运行时（“Linux 翻译层”，类似 WSL1）

不启动 Linux 内核，直接在 iPhone 的 CPU 上执行 arm64 Linux 程序的机器码，由我们实现 Linux 系统调用。
iSH（x86 解释器 + syscall 层）、Husk 的 Translation Layer（arm64 Android `.so` 原生执行）都是这个思路。

三个必须解决的问题：

1. **系统调用**：Linux 程序用 `svc #0`、x8 传号；在 iOS 上同一条指令会进 XNU、x16 传号——直接执行会乱。
   必须把每一处 `svc` 改到我们的 syscall 层。`binscan` 实测：动态链接的 `ls` 有 0 处、bash 1 处，
   但 `libc.so.6` 有 513 处、静态的 busybox 有 279 处——**处理好 libc 和 ld.so 就覆盖了绝大多数**。
2. **进程**：iOS 不能 fork。多个 Linux 进程必须共享一个 iOS 进程的地址空间。
   `fork` 时子进程需要父进程地址空间的副本，**而且副本中的指针必须仍然有效**——副本在另一个地址上，
   原生执行时这些指针都会指错。这是 B 路线的核心难题。
3. **可执行内存**：程序的代码页只能放在调试器给的一次性 JIT 区域里（Husk 的 carve/place 布局）。
   Python 的 JIT、Node/V8、Java、LuaJIT 这种 **guest 自己的 JIT** 也必须从这块区域里分配。

按执行方式再细分：

| 子方案 | 做法 | 问题 |
|---|---|---|
| B1 静态补丁 | 加载时把 `svc` 改成跳转 | guest 自己 JIT 出来的代码没法补；代码里的数据可能被误改；**fork 无解** |
| **B2 同构动态翻译 + LFI 式沙箱** | 见下 | 工作量大，但三个问题都有解 |
| B3 解释器 | iSH 式 | 无 JIT 时也能跑，但慢 |

### B2 的设计：动态版的 LFI

[LFI（Lightweight Fault Isolation）](https://www.scs.stanford.edu/~zyedidia/docs/papers/lfi.pdf)
是斯坦福 Zachary Yedidia 等人的 arm64 软件隔离方案（ASPLOS 2024），已进入 LLVM 22：

- 一个地址空间里可以放 **上万个 4 GiB 沙箱**；
- 每个沙箱的访存都被改写为 `基址寄存器 + 低 32 位偏移`（`x27` 存基址，`x28`/`x30`/`sp` 保持在沙箱内）；
- 系统调用被改写为跳到运行时（runtime）的入口；
- SPEC 2017 上开销约 **7%**。

LFI 原本是 **编译期** 改写（汇编阶段），不能处理现成的二进制。我们的想法是 **在动态翻译时做同样的改写**：

```
Debian arm64 ELF（原样，不重编译）
        │  按基本块读取
        ▼
 翻译器（arm64 → arm64）
   · 访存：[xN, ...] → [x27, wN, uxtw]   ← 每个 Linux 进程一个 4 GiB 槽位
   · br/blr/ret：目标限制在槽内 + 查翻译缓存
   · svc #0 → 跳到 syscall 层
   · mrs/msr TPIDR_EL0 → 读写每线程上下文（不依赖 XNU 是否保存）
   · mrs MIDR_EL1 等 → 返回伪造值
        │  写入一次性 JIT 区域里的代码缓存
        ▼
 Linux syscall 层（参考 iSH 的 kernel/，GPL-3.0）
   · 文件系统：rootfs 目录 + 权限/所有者元数据数据库（iSH 的 fakefs 思路）
   · 进程：fork = 把父槽位复制到新槽位（vm_copy / COW）
   · exec = 清空槽位并加载新 ELF；信号、futex、epoll、socket、pty……
```

为什么 fork 在这里能成立：沙箱内的所有有效地址都是 `基址 + 低 32 位`。指针里存的值在复制到另一个槽位后，
低 32 位不变，换了基址寄存器就指向新槽位里对应的位置——**不需要修正内存里的任何指针**。
只有执行 fork 的那个线程的寄存器（`sp`、`x30` 等 LFI 保证 “在沙箱内” 的寄存器）要换成新基址，
这在 syscall 层里一步完成。

这也顺带解决了：

- **guest 的 JIT**：guest 写的代码只是普通数据，翻译器执行到它时才翻译。只需对 “已翻译过的代码页”
  做写保护，被写时作废对应的翻译。
- **TLS 和系统寄存器**：都由翻译器接管，不依赖 XNU 的行为。

代价与限制（需要原型测量）：

- 动态翻译本身的开销：块查找、间接跳转查表。目标是远低于 QEMU 整机（没有软件 MMU，没有跨 ISA）。
- 每个 Linux 进程最多 4 GiB 地址空间（手机上够用）。
- 槽位数受地址空间限制：63 GB 时约 10 个以内（还要给 iOS 自己留空间），512 GB（extended-virtual-addressing）时上百个。
  **所以 extended-virtual-addressing 能否用免费账号获得，直接决定 B2 能同时跑多少进程。**
  若免费账号拿不到：槽位可以从 4 GiB 缩小（LFI 的设计允许更小的槽，代价是每个进程能用的内存更少），
  或者让不活跃的进程换出到文件，腾出槽位。
- 槽位之间的隔离只是 “不会意外踩到”，不作为安全边界承诺（Spectre 等不在范围内）。

### C. x86-64 Linux 程序：FEXCore

和 B 共用同一个 syscall 层，CPU 部分换成 FEXCore（x86 → arm64）。Madeira 已经在 iPhone 上用 FEXCore
跑通了一个 x86-64 Linux 静态 hello world（`FEXBridge.mm`），说明这条路是通的。
问题：FEXCore 按 1:1 映射 guest 地址，不支持 LFI 式的槽位，所以 **x86 进程暂时只能单进程**。
优先级低：Debian/Ubuntu 的 arm64 软件包已经很全，真正需要 x86 的主要是闭源程序和 Steam 的 Linux 原生游戏。

### D. 解释器后备

JIT 是单点故障（StikDebug#476 说明它在 iOS 27 上可能随时坏掉）。B2 翻译器的前端可以复用为一个
arm64 解释器：没有 JIT 时也能跑 shell、apt、脚本，只是慢。

## 推荐：两阶段

| 阶段 | 做什么 | 理由 |
|---|---|---|
| **第一阶段** | **A：QEMU 整机 VM**，独立的一个 App 构建（GPLv2），复用 Husk 已验证的 iOS JIT 胶水与 QEMU 构建 | 最快让 Ubuntu/Debian 在 iPhone 18 Pro 上完整跑起来；兼容性没有疑问 |
| **第二阶段** | **B2：原生运行时原型**（GPLv3） | 性能才是长期价值所在；这也是业界还没人做好的部分 |

关键一点：**B2 的翻译器和 syscall 层可以先在任意 arm64 Linux / macOS 主机上开发和测试**（只有 JIT 区域的获取是 iOS 特有的）。
所以第二阶段不必等第一阶段，也不需要每次都上真机。

### 图形

- A：virtio-gpu + virglrenderer + ANGLE（Husk 已为 iOS 构建了这三者），或者先只用串口/终端。
- B2：在 App 内实现一个 Wayland 合成器，把窗口画到 `CAMetalLayer`；GPU 加速走 Mesa（Zink/Venus）→ MoltenVK。
  先做终端（pty + 终端模拟器），图形放在最后。

## `binscan` 实测数据（Debian 12 bookworm, arm64）

| 二进制 | 指令数 | `svc` | TPIDR_EL0 读 | 会陷入 XNU 的 sysreg | 访存占比 | 16K W+X 页 |
|---|---:|---:|---:|---|---:|---:|
| `busybox`（静态） | 444,466 | 279 | 847 | MIDR_EL1 ×1 | 25.1% | 0 |
| `bash` | 312,754 | 1 | 0 | — | 22.9% | 0 |
| `ls`（coreutils） | 34,792 | 0 | 0 | — | 18.9% | 0 |
| `python3.11` | 1,332,444 | 7 | 0 | — | 19.1% | 0 |
| `libc.so.6` | 405,031 | 513 | 1485 | — | 22.2% | 0 |
| `ld-linux-aarch64.so.1` | 39,096 | 49 | 20 | MIDR_EL1 ×1 | 25.4% | 0 |

（线性扫描，代码段中的数据也被计入，是估计值。复现方法见 `tools/binscan/README.md`。）

读法：

- 16 KiB 页对 Debian 不是问题（全部按 64 KiB 对齐）。
- 约 20–25% 的指令是访存，这是 B2 中需要加基址改写的部分；LFI 的论文说明这类改写的实际开销很小。
- `MIDR_EL1` 只出现在 ld.so 和静态 glibc 的 CPU 特性检测中，不设 HWCAP_CPUID 即可绕开。
