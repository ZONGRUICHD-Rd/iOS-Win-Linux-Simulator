# 02 · Windows 软件 / 游戏方向

## 结论先说

**不要自己从头做 Wine-on-iOS。** Madeira 已经把最难的部分做完了：Wine ARM64EC 单进程化、
FEX 移植、DXMT 和自研 D3D12 到 Metal、Steam 登录/下载/云存档、手柄与触控、内置 JIT 和 iOS 27
App 内配对。重写这些要以人年计，而且它在快速迭代。

本仓库在 Windows 方向做三件事：

1. **在 iPhone 18 Pro 上把 Madeira 跑起来**，写清楚步骤（下文）。
2. **兼容性分诊**：用 `tools/binscan` 在装游戏之前判断它走哪条路、有没有已知的死路
   （反作弊、Vulkan/OpenGL、.NET）。
3. **补 Madeira 没有的东西**，作为给 Madeira 的上游贡献或我们自己的 fork（许可证相同，都是 GPL-3.0）。

## 在 iPhone 18 Pro 上运行 Madeira

前提：一台 Wi-Fi 网络、一个 Apple ID（免费即可）、一个侧载工具（SideStore/AltStore/Sideloadly/Plume）。

1. 从 [Madeira Releases](https://github.com/willfaust/Madeira/releases) 下载 IPA，用侧载工具安装。
   **保留 App 扩展**（有些工具会问；`MadeiraJITHelper.appex` 被删掉内置 JIT 就不能用）。
2. **加大内存上限**：用 GetMoreRam（或侧载工具自带的同类功能）登录同一个 Apple ID，找到 Madeira 的
   App ID，加 “Increased Memory Limit”，然后从侧载工具里 **重新安装** Madeira。
3. 从 App Store 装 **LocalDevVPN**。
4. 打开 Madeira 的 JIT 设置，选 **In-app**（iOS 27 App 内配对）：
   - 点 Start pairing，允许本地网络权限；
   - 去 设置 › 隐私与安全性 › 开发者模式，点 “Pair with Madeira”，输入 Madeira 显示的配对码；
   - 回到 Madeira，连接 LocalDevVPN，点 Check setup（会下载并挂载 Developer Disk Image），再点 Enable JIT。
5. 设置页里 JIT 和 Memory+ 都是绿勾，Madeira 会显示 “Ready to play”。
6. 部分 64 位游戏需要 VC++ 运行库，Madeira 不附带（微软许可证），需要自己提供。

**作者的决定（2026-10）：Madeira 直接侧载安装，不放进 LiveContainer。** 这样上面的步骤原样适用：
内存能力加在 Madeira 自己的 App ID 上，iOS 27 的 App 内配对和内置 StikJIT 都能用，不依赖 StikDebug
（它在 iOS 27.0 上有附加失败的报告）。LiveContainer 仍可用于其他 App，详见 [06](06-livecontainer.md)。

本仓库的 Madeira 修改版（导入 zip/7z、去掉 Steam、中文界面、液态玻璃图标）由 GitHub Actions 打包成 IPA，
见 [madeira/README.md](../madeira/README.md)。安装步骤同上，第 1 步改为从本仓库 Actions 的 `Madeira-ipa` 下载。

注意：开 JIT 时必须在 Wi-Fi 下（或完全断网），蜂窝数据下 LocalDevVPN 的回环不通。
Madeira 的 “Madeira JIT” 快捷指令可以自动关蜂窝、连 VPN、再恢复。

## 兼容性分诊

```sh
python3 tools/binscan/binscan.py "Game.exe" GameAssembly.dll
```

`binscan` 读 PE 头和导入表，给出：

| 字段 | 含义 |
|---|---|
| `arch` | x86-64 → Wine ARM64EC + FEX；i386 → WoW64 + FEX；arm64/arm64ec → 原生，无需翻译 |
| `graphics` | 从导入的 DLL 判断图形 API 及其在 Madeira 里的路径 |
| `dotnet` | .NET 程序集，需要 Wine Mono（Madeira 首次使用时下载） |
| `anticheat_hints` | EasyAntiCheat、BattlEye 等，基本可以判死刑 |

注意：很多游戏通过 `LoadLibrary` 动态加载图形 DLL，导入表里看不到；Unity/Unreal 等引擎游戏要扫
引擎 DLL（如 `UnityPlayer.dll`）而不仅是启动器 exe。`binscan` 的结论是 “初筛”，不是保证。

**原生 ARM64 的 Windows 程序** 值得特别关注：越来越多的软件发布 Windows on ARM 版本，这些在
Madeira 里完全不需要 FEX 翻译，性能接近原生。

Madeira 自己的游戏库在 **安装之后** 也会给游戏标出图形 API（`app/Madeira/Library.swift`），
`binscan` 的用处是在下载几十 GB 之前就先筛一遍，也能用于 Steam 之外的软件。

## Madeira 的空白（可做的贡献）

依据：Madeira 的 Wine 以 `--without-vulkan` 构建，构建脚本注释写明 “port (no OpenGL, --without-vulkan)”，
“graphics go through DXMT”（`build/wine-i386/build.sh`）。

按价值排序：

1. **Vulkan 游戏**：Wine 的 `winevulkan` → MoltenVK → Metal。MoltenVK 已经在 iOS 上被 Husk 和很多模拟器使用。
   也打开了 DXVK（D3D→Vulkan）作为 DXMT 之外的第二条路，便于对照。
2. **OpenGL 游戏**：wined3d 需要桌面 GL。可能的链路是 Mesa Zink（GL→Vulkan）→ MoltenVK。工作量大，排在后面。
3. **非游戏的 Windows 软件**：Madeira 的 UI 围绕游戏库设计。办公/工具类软件需要的是 “Windows 桌面 + 文件管理 +
   剪贴板 + 软键盘/外接键鼠”。Madeira 有 Windows desktop session，可以在此基础上做。
4. **Release 构建能跑**：目前只有 Debug 配置能跑游戏，Release 下崩溃，原因未知。查清楚对性能有直接好处。

每一项都应先在 Madeira 的 Discord / Issue 里确认没人在做，再动手。Madeira 欢迎 GPL-3.0 贡献；
它的 fork 中 AI 辅助代码很多，**不要把它们的改动转投 FEX-Emu 上游**（FEX 不接受 AI 生成的代码）。
