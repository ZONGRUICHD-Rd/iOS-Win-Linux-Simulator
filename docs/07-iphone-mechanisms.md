# 07 · iPhone 的运行机制

本文用尽量直白的话讲清楚：为什么在 iPhone 上跑 Windows 和 Linux 程序这么难，以及每一道限制在本项目里是怎么绕过去的。
具体的平台数据见 [01](01-platform-iphone18pro-ios27.md)，LiveContainer 的差异见 [06](06-livecontainer.md)。

核心可以概括成一句话：**iPhone 只执行苹果认可、签过名的代码，而且每个 App 被关在自己的笼子里。**
下面每一节，都是这句话的一个侧面。

## 1. 代码签名：手机上能跑的代码，必须事先签好名

在电脑上，下载一个程序就能运行。iPhone 不是这样：

- 每个可执行文件都带一份签名，里面有 **每一页代码的哈希值**。代码从闪存读进内存时，系统会逐页校验，对不上就杀进程。
- 签名有一条信任链：苹果 → 开发者证书 → **描述文件**（provisioning profile）。描述文件规定了三件事：
  - 这个 App 能装在哪些设备上；
  - 它是哪个 App ID；
  - 它有哪些 **权限声明**（entitlements）。
- 免费 Apple ID 签出来的描述文件 7 天过期，所以 SideStore/AltStore 要每周重签。免费账号同时只能激活 3 个 App、
  每周最多 10 个 App ID。LiveContainer 只占 1 个，所以能绕开这个限制。

**对项目的影响**：Windows 的 `.exe`、Linux 的程序都没有苹果签名，不可能直接执行。
只能用一个签了名的 App，在里面 **翻译** 或 **模拟** 这些代码。

## 2. 可写和可执行不能同时成立（W^X）

翻译器的工作方式是：把 x86 或 Linux 的代码翻译成 ARM 代码，**写进内存，再执行**。
这就要求一块内存先可写、后可执行。

iPhone 默认禁止这件事。一块内存要么能写、要么能执行，普通 App 无法把自己写的东西变成可执行代码。
只有苹果自己的程序（比如 Safari 的 JavaScript 引擎）有专门的权限。

这就是 **JIT 问题**。没有 JIT，模拟器只能逐条解释执行，慢 10 倍以上（UTM SE、iSH 就是这种情况）。

## 3. 唯一的后门：调试器

开发者用 Xcode 调试 App 时，调试器要能在代码里下断点，也就是 **修改代码页**。所以苹果留了一个口子：

- App 用开发证书签名时带有 `get-task-allow`，表示 “允许被调试”。所有侧载的 App 都满足。
- 调试器附加之后，进程被标记为 `CS_DEBUGGED`，调试器就可以改它的可执行内存。

**JIT 就是借这个口子拿到的。**

- **iOS 26 以前**：调试器附加一下，App 就能自己申请 “可写又可执行” 的内存。
- **iOS 26 起**（A15 以后的设备；iOS 27 起几乎所有设备）：苹果把代码签名的执行检查从内核挪到一个更高权限的监视器
  **TXM**（Trusted Execution Monitor）里，内核自己也不能随便把内存变成可执行。只剩一条很窄的路：
  1. App 执行一条断点指令 `brk #0xf00d`，相当于 “喊” 调试器（x16 放命令号，x0/x1 放参数）。
  2. 调试器在 App 里分配一块可执行内存，然后 **对每个 16 KB 的页各写 1 个字节**。被调试器写过的页，App 之后才能自己写。
  3. App 给同一块物理内存再映射一个 “可写” 的地址：写代码用可写地址，执行用可执行地址。
  4. 调试器断开。**之后再 “喊”，App 直接崩溃。**

所以 JIT 内存 **只能在启动时一次性申请够**，这是所有方案共同的设计铁律。
准备时间和区域大小成正比：Husk 在 iOS 27 上实测 256 MiB 需要 749 ms。

（协议细节见 StikDebug 的 `Scripts/universal.js` 和 [StikJIT 集成文档](https://github.com/StikDebug/StikJIT/blob/main/INTEGRATION.md)。）

## 4. 调试器是怎么 “在手机上” 出现的

正常情况下，调试需要一台 Mac。Mac 通过 USB 连接手机上的 `lockdownd` 服务，用 **配对记录** 认证，
挂载 Developer Disk Image（里面带有 `debugserver`），然后附加到 App。

StikDebug 的做法是 **让手机自己扮演那台 Mac**：

- **LocalDevVPN** 建立一个回环隧道，让发往 `10.7.0.1` 的流量绕回本机。手机就像在跟一台外部电脑说话。
- **配对文件** 就是那份配对记录。iOS 27 新增了 “在手机上配对”，Madeira 和 Husk 用它实现了不需要电脑。
  但这个功能依赖 App 扩展，**在 LiveContainer 里用不了**。
- 必须打开 **开发者模式**。
- 蜂窝网络下回环不通，开 JIT 时要连 Wi-Fi 或完全断网。

## 5. 沙箱：每个 App 一个笼子

- 每个 App 只能访问自己的文件夹，看不到别的 App。
- **不能创建进程**：没有 `fork`、`exec`、`posix_spawn`。就算能创建，新程序也得有签名。
- 唯一的 “多进程” 是 **App 扩展**：由系统按需启动的另一个进程。Madeira 的内置 JIT 助手、
  LiveContainer 的多任务（LiveProcess）都利用了这一点。

**对项目的影响**：

- Windows：Madeira 把 `wineserver` 这个本该独立的程序改成了一个线程。
- Linux：这是最难的地方。Linux 软件到处在 `fork`，比如 shell 执行命令、`apt` 装包。
  所以我们的设计要把多个 Linux 进程塞进同一个 iOS 进程里，每个进程分一个 4 GB 的地址槽位（见 [03](03-linux-path.md)）。

## 6. 内存：没有交换空间，超限就杀

- iPhone 不把 App 内存换到硬盘，只做内存压缩。每个 App 有内存上限，超过就被系统的 **jetsam** 机制直接杀掉。
- 提高内存上限（`increased-memory-limit`）这项权限可以提高上限，免费账号已在 iPhone 18 Pro / iOS 27 上实测可加。
- **地址空间** 也有上限，和物理内存是两回事：默认 63 GB，加了扩展地址空间（`extended-virtual-addressing`）可以到 512 GB。
  它决定了 Linux 方案能开多少个 4 GB 的槽位。
- 内存页是 **16 KB**（Linux 和 Windows 通常是 4 KB），所以加载外来程序时要重新排布。

## 7. 权限（entitlements）：能力要在三个地方都对上

一项特殊能力要生效，必须三处一致：

1. 苹果服务器上，这个 **App ID 开通了该能力**。GetMoreRam 做的就是这一步。
2. **描述文件** 里包含这项权限。重装 App 时，侧载工具会重新下载描述文件。
3. App 二进制的 **签名里声明了** 这项权限。

缺任何一处都不生效。这也解释了 LiveContainer 的两个情况：

- 被运行 App 的权限不生效，只看 LiveContainer 自己的。
- LiveContainer 的 iOS 版没有在签名里声明扩展地址空间，所以要自己编译、加上声明才能用。

## 8. LiveContainer 为什么能 “不安装就运行”

iOS 允许 App 加载 **同一开发者签名** 的动态库。LiveContainer 把别的 App 的主程序改造成动态库
（修改 Mach-O 头：`MH_EXECUTE` 改为 `MH_DYLIB`，`__PAGEZERO` 缩小），用同一张证书重签，
然后 `dlopen` 进自己的进程，跳到它的入口。

所以从系统看来，一直只有 LiveContainer 这一个 App 在运行。权限、内存上限、JIT 都按 LiveContainer 算。

## 9. 后台和图形

- **后台**：App 切到后台几秒后就会被挂起。Linux 里的服务进程、长时间下载，在后台都会停。
  调试器进程也可能被系统因为 CPU 占用杀掉，所以 JIT 必须在前台一次性准备好。
- **图形**：GPU 基本只能通过 Metal 访问。DirectX 要经过 DXMT 转成 Metal，Vulkan 要经过 MoltenVK，
  OpenGL ES（已废弃）一般经过 ANGLE。

## 汇总：每个机制给项目带来的限制

| 机制 | 结果 | 我们的对策 |
|---|---|---|
| 代码签名 | 外来程序不能直接跑 | 翻译 / 模拟 |
| W^X | 默认没有 JIT | 借调试器（StikDebug） |
| TXM（iOS 26+） | JIT 只能一次性申请 | 启动时划好固定大小的代码缓存 |
| 沙箱 + 不能建进程 | 不能 fork | 单进程 + 每个 Linux 进程一个 4 GB 槽位 |
| jetsam | 内存超限被杀 | 提高内存上限权限（已验证） |
| 地址空间上限 | 槽位数有限 | 扩展地址空间（待验证，LiveContainer 需自编译） |
| 16 KB 页 | 外来程序要重新排布 | 加载器处理；Debian arm64 已兼容 |
| 只有 Metal | DirectX/Vulkan 要转换 | DXMT、MoltenVK、ANGLE |
| 后台挂起 | 不适合跑常驻服务 | 前台使用为主 |
