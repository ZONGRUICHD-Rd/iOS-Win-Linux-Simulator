# Metal 测试（iOS 26）

一个最小的 iOS 26 测试 App：SwiftUI 界面 + 原生 Metal 渲染 3D 图形，GitHub Actions 打包 IPA。

- 三种网格：圆环、球体、立方体（Swift 里程序化生成）
- Blinn-Phong 光照 + 边缘光，4× MSAA，深度缓冲，最高 120 Hz（ProMotion）
- 压力测试：实例网格 1³–16³（最多 4096 个实例，GPU 实例化绘制）
- 实时数据：FPS、CPU/GPU 帧时间、GPU 名称、三角形数、分辨率
- 手势：拖动旋转视角、双指缩放；线框模式、暂停
- 控件使用 iOS 26 液态玻璃（`glassEffect`、`.buttonStyle(.glass)`）

## 文件

| 文件 | 内容 |
|---|---|
| `project.yml` | XcodeGen 工程描述（部署目标 iOS 26.0） |
| `MetalTest/Shaders.metal` | 顶点 / 片元着色器 |
| `MetalTest/Renderer.swift` | `MTKViewDelegate`：管线、绘制、帧统计 |
| `MetalTest/Mesh.swift` | 网格生成 |
| `MetalTest/ContentView.swift` | SwiftUI 界面与手势 |

## 构建

**GitHub Actions**：改动 `metal-test/` 后自动运行 [`Metal Test IPA`](../.github/workflows/metal-test-ipa.yml)，
也可以在 Actions 页手动触发。产物 `MetalTest-ipa` 里是 `MetalTest.ipa`（未用证书签名，仅 ad-hoc），
用 AltStore / SideStore / Sideloadly 等工具以自己的 Apple ID 重签后安装。

**本地（macOS + Xcode 26）**：

```sh
brew install xcodegen
cd metal-test && xcodegen generate && open MetalTest.xcodeproj
```
