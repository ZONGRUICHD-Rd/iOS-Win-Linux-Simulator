# 04 · 路线图

每个阶段都有 **验证门槛**：只有在 iPhone 18 Pro 真机上看到结果，才能标为完成。

## P0 · 设备探针（iOS，最先做）

一个极小的探针 App，一次性测出 [01](01-platform-iphone18pro-ios27.md) 中所有 “待实测” 项，输出 JSON 报告提交到 `reports/`。

- [x] 授权：increased-memory-limit 免费账号可加（作者用 GetMoreRam 在 iPhone 18 Pro / iOS 27 上实测，2026-10）
- [ ] 授权：extended-virtual-addressing 免费账号能否加上（测试方法见 docs/01 第 4 节）
- [ ] `os_proc_available_memory()` 实际值
- [ ] 地址空间上限（63 GB / 512 GB），能否预留 `0x400000`、`0x140000000`
- [ ] 内置 StikJIT 在 iOS 27 上准备 256 MiB / 1 GiB / 2 GiB 区域的耗时与成功率
- [ ] `TPIDR_EL0` 跨线程切换和信号是否保留；x18 是否保留
- [ ] JIT 区域内 carve / place 两种映像布局是否可行

门槛：报告中 JIT 自测执行生成的代码并返回 42。

## P1 · Windows：Madeira 实测与分诊

- [ ] 按 [02](02-windows-path.md) 在 iPhone 18 Pro 上装好 Madeira，记录每一步的实际情况
- [ ] 建立兼容性表 `reports/windows-compat.md`：游戏、`binscan` 结果、能否启动、帧率、问题
- [ ] 选一项 Madeira 的空白（Vulkan → MoltenVK 优先），先与 Madeira 维护者确认

## P2 · Linux A：QEMU 整机 VM（独立 App 构建）

- [ ] 交叉编译 QEMU（UTM 的 `-Dshared_lib=true` 分支）与依赖到 `arm64-apple-ios`
- [ ] JIT 胶水：TCG split-W^X 指向调试器授予的区域（参考 Husk 的 `husk-ios-jit.c` 设计，自己实现）
- [ ] 启动 Debian 12 / Ubuntu 24.04 arm64 云镜像，串口终端可交互
- [ ] virtio-net 走 slirp；virtio-blk 磁盘放在 App 的 Documents
- [ ] 门槛：真机上 `apt update && apt install htop` 成功

## P3 · Linux B2：原生运行时原型（先在主机上开发）

在 arm64 Linux 或 macOS 主机上开发，不需要真机：

- [ ] ELF 加载器（静态、PIE、动态 + ld.so）
- [ ] 同构翻译器：基本块翻译、代码缓存、块链接、间接跳转查表
- [ ] LFI 式改写：访存、分支、`svc`、TPIDR_EL0、受限 sysreg
- [ ] syscall 层最小集：文件、内存、线程（clone）、futex、信号、时间
- [ ] 门槛（主机）：Debian 的静态 busybox、动态 bash 能交互运行
- [ ] fork / exec / wait / pipe / pty
- [ ] 门槛（主机）：在 rootfs 里 `apt install` 成功（dpkg 的维护脚本需要 fork+exec）
- [ ] 移植到 iOS：代码缓存放进一次性 JIT 区域；门槛：真机上同样的测试通过
- [ ] 性能对比：同一组 benchmark 在 原生 / B2 / QEMU(A) 下的耗时

## P4 · 体验

- [ ] 终端 UI（pty + 终端模拟器，外接键盘）
- [ ] rootfs 管理：下载、导入、多个发行版
- [ ] Wayland 合成器 → `CAMetalLayer`（B2）；virtio-gpu + virgl（A）
- [ ] 内置 GetMoreRam 式的授权申请，减少用户要装的 App 数量

## 不做 / 暂不做

- 越狱方案（Hypervisor.framework 需要私有授权）
- App Store 上架（调试器 JIT 不可能过审）
- 反作弊游戏
