# 06 · 在 LiveContainer 里运行

项目作者全程使用 [LiveContainer](https://github.com/LiveContainer/LiveContainer)（AGPL-3.0）。
它是一个 “App 启动器”：把别的 App 的可执行文件当成 dylib `dlopen` 到自己进程里运行，
所以只占 **一个 App ID**，绕过免费账号 “3 个 App / 每周 10 个 App ID” 的限制。

这对本项目的影响很大，下面每条都标了来源。源码读自 LiveContainer `4dbe0f9`（2026-09-19）。

## 1. 授权看的是 LiveContainer 自己的，不是被运行的 App 的

LiveContainer README：“Entitlements from the guest app are not applied to the host app.”

- **increased-memory-limit**：要加在 **LiveContainer 的 App ID** 上（GetMoreRam 里选 LiveContainer 那一项）。
  LiveContainer 的 `entitlements.xml` 已经声明了 `com.apple.developer.kernel.increased-memory-limit`，
  所以 App ID 上加了能力、重装之后就会生效。Madeira 的 App ID 在 LiveContainer 里不起作用。
- **extended-virtual-addressing**：LiveContainer 的 iOS `entitlements.xml` **没有** 声明它，只有 Mac Catalyst 版
  （`entitlements.catalyst.xml`）有。也就是说，**即使 App ID 加上了这个能力，官方 LiveContainer 也不会带上它**。
  要用的话得自己编译 LiveContainer：在 `entitlements.xml` 里加上
  `<key>com.apple.developer.kernel.extended-virtual-addressing</key><true/>`。
- `get-task-allow`：LiveContainer 已声明，开发证书侧载时满足，调试器能附加。

## 2. JIT：只能用 StikDebug，并且每个 App 需要一个 JIT 脚本

LiveContainer 文档：“Only StikDebug/StikDebug(Another LiveContainer) works for iOS 26+”；
TXM 设备（A15+/M2+）上 “you'll also need a JIT script for each app”。

- **Madeira 的内置 StikJIT 在 LiveContainer 里不可用**。Madeira 源码 `JITBuiltInHost.swift` 明确返回
  “Built-in JIT is unavailable inside LiveContainer. Choose StikDebug instead.” 原因是内置 StikJIT 依赖一个
  App 扩展（`MadeiraJITHelper.appex`），而 LiveContainer README 写明 “App extensions aren't supported”。
  因此 **iOS 27 的 App 内配对（不需要电脑）这条路在 LiveContainer 里也没有**。
- 可用的路线：
  - **StikDebug**（单独安装），或
  - **StikDebug (Another LiveContainer)**：把 StikDebug 本身装进 LiveContainer 并设为 shared app，
    由另一个空闲的 LiveContainer 实例运行它（需要装多个 LiveContainer）。
  - 两种都需要配对文件 + LocalDevVPN。
- 操作：长按 App → 设置 → 加载该 App 的 **JIT 脚本** → 打开 **Launch with JIT**。
  LiveContainer 会用 `stikjit://enable-jit?bundle-id=<LiveContainer>&pid=<pid>&script-data=<脚本>` 交给 StikDebug。
  对 Madeira 来说，脚本就是它仓库里的 `app/Madeira/madeira-jit.js`。

**最大的风险**：[StikDebug#476](https://github.com/StikDebug/StikDebug/issues/476)（2026-10-05）报告
StikDebug 3.1.13 在 iOS 27.0 上对所有 App 附加失败（E96），已被关为 “not planned”。
在 LiveContainer 里没有内置 StikJIT 可以兜底，**所以 StikDebug 在你的 iOS 27 上能不能附加，决定了整个项目能不能在 LiveContainer 里跑**。
这是现在最需要实测的一项。

## 3. 地址空间

LiveContainer 把被运行 App 的 `__PAGEZERO` 改成 `0xFFFFC000` 起、大小 `0x4000`，并把它从 `MH_EXECUTE` 改成 `MH_DYLIB` 加载。
被运行的 App 是在 LiveContainer 自己初始化之后才被加载的，所以：

- Madeira 用 constructor 在映像加载时抢占 `0x140000000` 附近的窗口（Windows PE 默认基址）。在 LiveContainer 里
  这个时机变晚了，窗口有可能已经被占用。Madeira 会把窗口的抢占结果写进它的日志（`JITAllocator.c` 中的早期窗口报告）。**待实测**。
- 本项目的 Linux 运行时同理：要尽早预留 4 GiB 槽位，否则地址空间可能已经碎片化。

## 4. 对本项目设计的约束

如果本项目的 App 要在 LiveContainer 里运行（作者的使用方式），设计上必须：

1. **不依赖 App 扩展**：不能照搬 Madeira 的内置 StikJIT；JIT 只走 StikDebug 的 universal 协议
   （`brk #0xf00d`），并随 App 提供一个固定的 JIT 脚本。
2. **授权由 LiveContainer 提供**：启动时自检，缺 increased-memory-limit 时提示用户给 LiveContainer 的 App ID 加；
   extended-virtual-addressing 不能假设存在，Linux 运行时要能在 63 GB 地址空间下工作（槽位数少一些）。
3. **不依赖自己的 Bundle ID**：LiveContainer 下 `NSBundle.mainBundle` 被替换成被运行 App 的 bundle，
   而调试器附加的进程是 LiveContainer。凡是要传 bundle ID 给 StikDebug 的地方，以 LiveContainer 的为准。
4. **数据隔离**：LiveContainer 里各 App 的容器互相可读（README：“Guest app containers are not sandboxed”）。
   Linux rootfs 和 Windows 前缀里如果有凭据，要知道其他 App 也读得到。

## 5. 一个可能有用的发现：LiveProcess

LiveContainer 的多任务模式把 App 跑在 `LiveProcess` 扩展里，即 **单独的 iOS 进程**（Madeira 的 JIT 助手也借用了同样的
`com.apple.ar.viewer` 扩展点）。理论上这是 “在 iOS 上拿到多个进程” 的一种办法，但每个进程都要单独让 StikDebug 附加、
单独申请 JIT 区域，代价很高。Linux 方向仍以单进程内的 LFI 槽位为主（[03](03-linux-path.md)），这里只记作备选。

## 待实测清单（LiveContainer 版）

- [ ] GetMoreRam 是加在 LiveContainer 的 App ID 上的吗？Madeira 在 LiveContainer 里运行时，设置页 Memory+ 是否为绿勾
- [ ] StikDebug 在 iPhone 18 Pro / iOS 27 上，用 Launch with JIT + `madeira-jit.js` 能否附加成功（对照 StikDebug#476）
- [ ] 若失败：StikDebug (Another LiveContainer) 方式是否可行
- [ ] Madeira 日志里 `0x140000000` 早期窗口是否拿到
- [ ] 自己编译加了 extended-virtual-addressing 的 LiveContainer 后，Madeira 日志中 `address-map` 是否为 512GB
