import MetalKit
import Observation
import QuartzCore

struct FrameStats {
    var fps: Double = 0
    var cpuFrameMs: Double = 0
    var gpuFrameMs: Double = 0
    var instances = 1
    var triangles = 0
    var drawableSize = CGSize.zero
}

/// State shared between the SwiftUI controls and the renderer.
@MainActor
@Observable
final class RenderSettings {
    var shape: ShapeKind = .torus
    var gridSide = 1
    var wireframe = false
    var paused = false
    var yaw: Float = 0.6
    var pitch: Float = 0.35
    var zoom: Float = 1
    var gpuName = "—"
    var stats = FrameStats()
}

/// Must match `Uniforms` in Shaders.metal.
private struct Uniforms {
    var viewProjection: simd_float4x4
    var cameraPosition: SIMD4<Float>
    var lightDirection: SIMD4<Float>
    var time: Float
    var gridSide: UInt32
    var spacing: Float
    var objectScale: Float
}

@MainActor
final class Renderer: NSObject, MTKViewDelegate {
    private let device: MTLDevice
    private let queue: MTLCommandQueue
    private let pipeline: MTLRenderPipelineState
    private let depthState: MTLDepthStencilState
    private let settings: RenderSettings
    private var meshes: [ShapeKind: Mesh] = [:]

    private var time: Float = 0
    private var lastFrame: CFTimeInterval = 0
    private var windowStart: CFTimeInterval = 0
    private var windowFrames = 0
    private var windowCPU: Double = 0
    private var lastGPUms: Double = 0

    private let spacing: Float = 2.4

    init?(view: MTKView, settings: RenderSettings) {
        guard let device = view.device,
              let queue = device.makeCommandQueue(),
              let library = device.makeDefaultLibrary()
        else { return nil }

        let vertexDescriptor = MTLVertexDescriptor()
        vertexDescriptor.attributes[0].format = .float3
        vertexDescriptor.attributes[0].offset = MemoryLayout<Vertex>.offset(of: \.position)!
        vertexDescriptor.attributes[0].bufferIndex = 0
        vertexDescriptor.attributes[1].format = .float3
        vertexDescriptor.attributes[1].offset = MemoryLayout<Vertex>.offset(of: \.normal)!
        vertexDescriptor.attributes[1].bufferIndex = 0
        vertexDescriptor.layouts[0].stride = MemoryLayout<Vertex>.stride

        let desc = MTLRenderPipelineDescriptor()
        desc.label = "Lit mesh"
        desc.vertexFunction = library.makeFunction(name: "vertex_main")
        desc.fragmentFunction = library.makeFunction(name: "fragment_main")
        desc.vertexDescriptor = vertexDescriptor
        desc.colorAttachments[0].pixelFormat = view.colorPixelFormat
        desc.depthAttachmentPixelFormat = view.depthStencilPixelFormat
        desc.rasterSampleCount = view.sampleCount

        let depthDesc = MTLDepthStencilDescriptor()
        depthDesc.depthCompareFunction = .less
        depthDesc.isDepthWriteEnabled = true

        guard let pipeline = try? device.makeRenderPipelineState(descriptor: desc),
              let depthState = device.makeDepthStencilState(descriptor: depthDesc)
        else { return nil }

        self.device = device
        self.queue = queue
        self.pipeline = pipeline
        self.depthState = depthState
        self.settings = settings
        super.init()

        for kind in ShapeKind.allCases {
            meshes[kind] = Mesh.make(kind, device: device)
        }
        settings.gpuName = device.name
    }

    func mtkView(_ view: MTKView, drawableSizeWillChange size: CGSize) {
        settings.stats.drawableSize = size
    }

    func draw(in view: MTKView) {
        let start = CACurrentMediaTime()
        let dt = lastFrame == 0 ? 0 : start - lastFrame
        lastFrame = start
        if !settings.paused { time += Float(min(dt, 0.1)) }

        guard let mesh = meshes[settings.shape],
              let passDescriptor = view.currentRenderPassDescriptor,
              let drawable = view.currentDrawable,
              let commandBuffer = queue.makeCommandBuffer(),
              let encoder = commandBuffer.makeRenderCommandEncoder(descriptor: passDescriptor)
        else { return }

        let side = max(settings.gridSide, 1)
        let instances = side * side * side
        let extent = Float(side - 1) * spacing
        let distance = (3.5 + extent * 1.1) / settings.zoom
        let pitch = settings.pitch, yaw = settings.yaw
        let eye = SIMD3<Float>(cos(pitch) * sin(yaw), sin(pitch), cos(pitch) * cos(yaw)) * distance

        let size = view.drawableSize
        let aspect = Float(size.width / max(size.height, 1))
        let projection = simd_float4x4.perspective(fovY: .pi / 3, aspect: aspect,
                                                   near: 0.05, far: distance + extent * 2 + 10)
        let viewMatrix = simd_float4x4.lookAt(eye: eye, center: .zero, up: [0, 1, 0])

        var uniforms = Uniforms(
            viewProjection: projection * viewMatrix,
            cameraPosition: SIMD4<Float>(eye, 1),
            lightDirection: SIMD4<Float>(normalize(SIMD3<Float>(-0.4, -1, -0.6)), 0),
            time: time,
            gridSide: UInt32(side),
            spacing: spacing,
            objectScale: 1
        )

        encoder.label = "Scene"
        encoder.setRenderPipelineState(pipeline)
        encoder.setDepthStencilState(depthState)
        encoder.setCullMode(.none)
        encoder.setTriangleFillMode(settings.wireframe ? .lines : .fill)
        encoder.setVertexBuffer(mesh.vertexBuffer, offset: 0, index: 0)
        encoder.setVertexBytes(&uniforms, length: MemoryLayout<Uniforms>.stride, index: 1)
        encoder.setFragmentBytes(&uniforms, length: MemoryLayout<Uniforms>.stride, index: 1)
        encoder.drawIndexedPrimitives(type: .triangle,
                                      indexCount: mesh.indexCount,
                                      indexType: .uint32,
                                      indexBuffer: mesh.indexBuffer,
                                      indexBufferOffset: 0,
                                      instanceCount: instances)
        encoder.endEncoding()

        commandBuffer.addCompletedHandler { [weak self] cb in
            let ms = (cb.gpuEndTime - cb.gpuStartTime) * 1000
            Task { @MainActor in self?.lastGPUms = ms }
        }
        commandBuffer.present(drawable)
        commandBuffer.commit()

        windowFrames += 1
        windowCPU += (CACurrentMediaTime() - start) * 1000
        if windowStart == 0 { windowStart = start }
        let elapsed = start - windowStart
        if elapsed >= 0.5 {
            var stats = settings.stats
            stats.fps = Double(windowFrames) / elapsed
            stats.cpuFrameMs = windowCPU / Double(windowFrames)
            stats.gpuFrameMs = lastGPUms
            stats.instances = instances
            stats.triangles = mesh.triangleCount * instances
            stats.drawableSize = size
            settings.stats = stats
            windowStart = start
            windowFrames = 0
            windowCPU = 0
        }
    }
}
