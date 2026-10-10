import MetalKit
import SwiftUI

struct MetalView: UIViewRepresentable {
    let settings: RenderSettings

    final class Coordinator {
        var renderer: Renderer?
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> MTKView {
        let view = MTKView(frame: .zero, device: MTLCreateSystemDefaultDevice())
        view.colorPixelFormat = .bgra8Unorm
        view.depthStencilPixelFormat = .depth32Float
        view.sampleCount = 4
        view.clearColor = MTLClearColor(red: 0.04, green: 0.05, blue: 0.08, alpha: 1)
        view.preferredFramesPerSecond = 120
        context.coordinator.renderer = Renderer(view: view, settings: settings)
        view.delegate = context.coordinator.renderer
        return view
    }

    func updateUIView(_ uiView: MTKView, context: Context) {}
}

struct ContentView: View {
    @State private var settings = RenderSettings()
    @State private var dragOrigin: (yaw: Float, pitch: Float)?
    @State private var zoomOrigin: Float?
    @State private var showControls = true

    var body: some View {
        ZStack {
            MetalView(settings: settings)
                .ignoresSafeArea()
                .gesture(orbit)
                .simultaneousGesture(zoom)

            VStack(spacing: 12) {
                statsCard
                Spacer()
                if showControls { controlsCard }
            }
            .padding()
        }
        .preferredColorScheme(.dark)
        .statusBarHidden()
    }

    private var orbit: some Gesture {
        DragGesture(minimumDistance: 2)
            .onChanged { value in
                let origin = dragOrigin ?? (settings.yaw, settings.pitch)
                dragOrigin = origin
                settings.yaw = origin.yaw - Float(value.translation.width) * 0.008
                settings.pitch = min(max(origin.pitch + Float(value.translation.height) * 0.008, -1.45), 1.45)
            }
            .onEnded { _ in dragOrigin = nil }
    }

    private var zoom: some Gesture {
        MagnifyGesture()
            .onChanged { value in
                let origin = zoomOrigin ?? settings.zoom
                zoomOrigin = origin
                settings.zoom = min(max(origin * Float(value.magnification), 0.3), 5)
            }
            .onEnded { _ in zoomOrigin = nil }
    }

    private var statsCard: some View {
        let s = settings.stats
        return HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 4) {
                Text(String(format: "%.0f FPS", s.fps))
                    .font(.system(.title2, design: .rounded).weight(.bold))
                Text(String(format: "CPU %.2f ms · GPU %.2f ms", s.cpuFrameMs, s.gpuFrameMs))
                Text("\(settings.gpuName)")
                Text("实例 \(s.instances) · 三角形 \(s.triangles.formatted())")
                Text("\(Int(s.drawableSize.width))×\(Int(s.drawableSize.height)) · MSAA 4×")
            }
            .font(.system(.footnote, design: .monospaced))
            .monospacedDigit()
            Spacer(minLength: 0)
            Button {
                withAnimation(.snappy) { showControls.toggle() }
            } label: {
                Image(systemName: showControls ? "chevron.down" : "slider.horizontal.3")
                    .font(.title3)
                    .padding(8)
            }
            .buttonStyle(.glass)
        }
        .padding(14)
        .glassEffect(.regular, in: .rect(cornerRadius: 20))
    }

    private var controlsCard: some View {
        VStack(spacing: 12) {
            Picker("形状", selection: $settings.shape) {
                ForEach(ShapeKind.allCases) { Text($0.rawValue).tag($0) }
            }
            .pickerStyle(.segmented)

            Stepper(value: $settings.gridSide, in: 1...16) {
                let n = settings.gridSide
                Text("实例网格 \(n)³ = \(n * n * n)")
                    .monospacedDigit()
            }

            HStack {
                Toggle("线框", isOn: $settings.wireframe)
                Divider().frame(height: 24)
                Toggle("暂停", isOn: $settings.paused)
            }

            Button("重置视角") {
                withAnimation {
                    settings.yaw = 0.6
                    settings.pitch = 0.35
                    settings.zoom = 1
                }
            }
            .buttonStyle(.glass)
        }
        .padding(16)
        .glassEffect(.regular, in: .rect(cornerRadius: 24))
        .transition(.move(edge: .bottom).combined(with: .opacity))
    }
}
