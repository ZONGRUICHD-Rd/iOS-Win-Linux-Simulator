# Madeira（本仓库的修改版）

基于 [willfaust/Madeira](https://github.com/willfaust/Madeira)（在 iPhone 上运行 Windows 程序：Wine + FEX + Metal）的修改版。
相对上游的改动：

| 改动 | 说明 |
|---|---|
| **导入压缩包** | 资料库的 **+** 菜单 →「导入压缩包（zip 或 7z）」。程序解压到 `C:\Programs\<名称>`，只有一个主程序时自动加入资料库，否则列出所有 `.exe` / `.bat` / `.cmd` 供选择（安装、卸载程序排在最后） |
| **去掉 Steam** | Steam 登录、Madeira Dock、Steam 资料库 / 云存档 / 下载、「在 Steam 上查找」全部关闭 |
| **简体中文界面** | 442 条界面文字已翻译；IPA 只带中文本地化，按设计无论 iPhone 语言设置为何都显示中文（尚未在真机上验证） |
| **液态玻璃图标** | Icon Composer 分层图标，iOS 26 上有浅色、深色、着色三种外观 |
| **GitHub Actions 打包 IPA** | `.github/workflows/madeira-ipa.yml` |

## 获取 IPA

1. 打开仓库的 **Actions → Madeira IPA**，选最新一次成功的运行。
2. 在 **Artifacts** 里下载 `Madeira-ipa`（zip 里就是 `Madeira.ipa`）。
3. 用 SideStore / AltStore / Sideloadly **直接安装**（不放进 LiveContainer）。安装时 **保留 App 扩展**，
   内置 JIT 助手（`MadeiraJITHelper.appex`）要靠它。

IPA 是 ad-hoc 签名并带有权限声明（`get-task-allow`、提高内存上限），侧载工具会用你的证书重签，
并据此为 App ID 申请对应能力。之后的设置见 [docs/02](../docs/02-windows-path.md)。

注意：这是 **Debug** 构建。上游说明 Release 构建会让游戏崩溃，只有 Debug 能正常运行游戏。

## 导入程序

- 支持 `.zip`（含 ZIP64、无 UTF-8 标记的 GBK 中文文件名）和 `.7z`（LZMA、LZMA2、BCJ、BCJ2、ARM64 等滤镜、PPMd）。
- 7z 的固实压缩块是**流式解压**的，不会把整个块读进内存。在 Linux 上实测：一个 464 MB 的 Ultra（BCJ2，256 MB 字典）压缩包解压时峰值内存约 260 MB（主要是 LZMA 字典本身），同样内容的 zip 约 11 MB。
- 不支持：加密压缩包（会提示先在电脑上去掉密码）、分卷压缩包、rar。
- 压缩包里只有一个顶层文件夹时，就用这个文件夹；否则用压缩包的文件名作为文件夹名。重名时自动加上「 2」「 3」。
- 程序 x86 / x64 均可；32 位程序走 WoW64。

## 目录结构

| 路径 | 内容 |
|---|---|
| `UPSTREAM` | 上游 Madeira 的固定提交 |
| `patches/` | 本修改版的补丁序列（`git format-patch` 格式） |
| `prepare.sh` | 下载上游 + 子模块（Wine、FEX、DXMT、Madeira Dock），应用补丁，得到完整源码树 |
| `ci/build-native.sh` | 构建上游仓库里没有的原生库：LLVM 15（iOS）、GnuTLS、FFmpeg、Wine 配置与 unix 侧、DXMT、FEX、配对库 |
| `ci/package-ipa.sh` | ad-hoc 签名并打包 IPA |
| `l10n/` | 中文翻译（`zh-Hans.json`）、字符串提取与字符串目录生成脚本 |
| `tests/archive/` | 压缩包解压器的测试（Linux/macOS，AddressSanitizer） |

## 修改这个版本

```sh
madeira/prepare.sh                     # 得到 madeira/work/Madeira（分支 iwls）
# 在 madeira/work/Madeira 里修改、git commit
git -C madeira/work/Madeira format-patch --no-numbered --zero-commit \
    -o madeira/patches "$(cat madeira/UPSTREAM)"..iwls   # 先删掉旧的 patches/*.patch
```

改了界面文字时：

```sh
python3 madeira/l10n/build_catalog.py madeira/work/Madeira   # 列出缺少的翻译并生成 Localizable.xcstrings
```

把新文字的翻译加进 `l10n/zh-Hans.json` 后再运行一次，然后提交。

测试解压器：

```sh
python3 madeira/tests/archive/test_archive.py madeira/work/Madeira /path/to/7zz
```

## 许可证

上游 Madeira 是 GPL-3.0-or-later（附 Madeira Converter Exception），本修改版沿用。
`app/Madeira/Archive/lzma/` 是 7-Zip 25.01 的 C 解码器，公有领域。
