import Metal
import simd

struct Vertex {
    var position: SIMD3<Float>
    var normal: SIMD3<Float>
}

enum ShapeKind: String, CaseIterable, Identifiable {
    case torus = "圆环"
    case sphere = "球体"
    case cube = "立方体"

    var id: Self { self }
}

struct Mesh {
    let vertexBuffer: MTLBuffer
    let indexBuffer: MTLBuffer
    let indexCount: Int

    var triangleCount: Int { indexCount / 3 }

    init?(device: MTLDevice, vertices: [Vertex], indices: [UInt32]) {
        guard let vb = device.makeBuffer(bytes: vertices,
                                         length: MemoryLayout<Vertex>.stride * vertices.count,
                                         options: .storageModeShared),
              let ib = device.makeBuffer(bytes: indices,
                                         length: MemoryLayout<UInt32>.stride * indices.count,
                                         options: .storageModeShared)
        else { return nil }
        vertexBuffer = vb
        indexBuffer = ib
        indexCount = indices.count
    }

    static func make(_ kind: ShapeKind, device: MTLDevice) -> Mesh? {
        let (v, i): ([Vertex], [UInt32])
        switch kind {
        case .torus: (v, i) = torus(majorRadius: 0.7, minorRadius: 0.3, rings: 64, sides: 32)
        case .sphere: (v, i) = sphere(radius: 0.9, stacks: 48, slices: 64)
        case .cube: (v, i) = cube(size: 1.3)
        }
        return Mesh(device: device, vertices: v, indices: i)
    }

    /// Index a (rows + 1) x (cols + 1) vertex grid into triangles.
    private static func gridIndices(rows: Int, cols: Int) -> [UInt32] {
        var indices: [UInt32] = []
        indices.reserveCapacity(rows * cols * 6)
        let stride = cols + 1
        for r in 0..<rows {
            for c in 0..<cols {
                let a = UInt32(r * stride + c)
                let b = a + UInt32(stride)
                indices += [a, b, a + 1, a + 1, b, b + 1]
            }
        }
        return indices
    }

    static func torus(majorRadius R: Float, minorRadius r: Float, rings: Int, sides: Int) -> ([Vertex], [UInt32]) {
        var vertices: [Vertex] = []
        for i in 0...rings {
            let u = Float(i) / Float(rings) * 2 * .pi
            let center = SIMD3<Float>(cos(u) * R, 0, sin(u) * R)
            for j in 0...sides {
                let v = Float(j) / Float(sides) * 2 * .pi
                let normal = SIMD3<Float>(cos(u) * cos(v), sin(v), sin(u) * cos(v))
                vertices.append(Vertex(position: center + normal * r, normal: normal))
            }
        }
        return (vertices, gridIndices(rows: rings, cols: sides))
    }

    static func sphere(radius: Float, stacks: Int, slices: Int) -> ([Vertex], [UInt32]) {
        var vertices: [Vertex] = []
        for i in 0...stacks {
            let phi = Float(i) / Float(stacks) * .pi
            for j in 0...slices {
                let theta = Float(j) / Float(slices) * 2 * .pi
                let n = SIMD3<Float>(sin(phi) * cos(theta), cos(phi), sin(phi) * sin(theta))
                vertices.append(Vertex(position: n * radius, normal: n))
            }
        }
        return (vertices, gridIndices(rows: stacks, cols: slices))
    }

    static func cube(size: Float) -> ([Vertex], [UInt32]) {
        let h = size / 2
        // (normal, tangent u, tangent v) per face
        let faces: [(SIMD3<Float>, SIMD3<Float>, SIMD3<Float>)] = [
            ([1, 0, 0], [0, 0, -1], [0, 1, 0]),
            ([-1, 0, 0], [0, 0, 1], [0, 1, 0]),
            ([0, 1, 0], [1, 0, 0], [0, 0, -1]),
            ([0, -1, 0], [1, 0, 0], [0, 0, 1]),
            ([0, 0, 1], [1, 0, 0], [0, 1, 0]),
            ([0, 0, -1], [-1, 0, 0], [0, 1, 0]),
        ]
        var vertices: [Vertex] = []
        var indices: [UInt32] = []
        for (n, u, v) in faces {
            let base = UInt32(vertices.count)
            for (su, sv) in [(-1, -1), (1, -1), (1, 1), (-1, 1)] as [(Float, Float)] {
                vertices.append(Vertex(position: (n + u * su + v * sv) * h, normal: n))
            }
            indices += [base, base + 1, base + 2, base, base + 2, base + 3]
        }
        return (vertices, indices)
    }
}
