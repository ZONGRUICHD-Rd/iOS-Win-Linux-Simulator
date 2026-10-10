#include <metal_stdlib>
using namespace metal;

// Must match `Uniforms` in Renderer.swift (112 bytes).
struct Uniforms {
    float4x4 viewProjection;
    float4   cameraPosition;
    float4   lightDirection;
    float    time;
    uint     gridSide;
    float    spacing;
    float    objectScale;
};

struct VertexIn {
    float3 position [[attribute(0)]];
    float3 normal   [[attribute(1)]];
};

struct VertexOut {
    float4 position [[position]];
    float3 worldPos;
    float3 normal;
    float3 color;
};

static float3x3 rotX(float a) {
    float c = cos(a), s = sin(a);
    return float3x3(float3(1, 0, 0), float3(0, c, s), float3(0, -s, c));
}

static float3x3 rotY(float a) {
    float c = cos(a), s = sin(a);
    return float3x3(float3(c, 0, -s), float3(0, 1, 0), float3(s, 0, c));
}

static float3 hsv2rgb(float3 c) {
    float3 p = abs(fract(c.xxx + float3(1.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0);
    return c.z * mix(float3(1.0), saturate(p - 1.0), c.y);
}

// Every instance sits in a gridSide^3 lattice and spins with its own phase,
// so the stress test needs no per-instance buffer.
vertex VertexOut vertex_main(VertexIn in [[stage_in]],
                             constant Uniforms &u [[buffer(1)]],
                             uint iid [[instance_id]])
{
    uint side = max(u.gridSide, 1u);
    uint3 cell = uint3(iid % side, (iid / side) % side, iid / (side * side));
    float3 offset = (float3(cell) - float(side - 1) * 0.5) * u.spacing;

    float phase = float(iid) * 0.618034;
    float3x3 rot = rotY(u.time * 0.9 + phase) * rotX(u.time * 0.6 + phase * 1.3);

    VertexOut out;
    float3 world = rot * (in.position * u.objectScale) + offset;
    out.position = u.viewProjection * float4(world, 1.0);
    out.worldPos = world;
    out.normal = rot * in.normal;
    out.color = hsv2rgb(float3(fract(phase * 0.15 + u.time * 0.04), 0.6, 1.0));
    return out;
}

fragment float4 fragment_main(VertexOut in [[stage_in]],
                              constant Uniforms &u [[buffer(1)]])
{
    float3 n = normalize(in.normal);
    float3 v = normalize(u.cameraPosition.xyz - in.worldPos);
    if (dot(n, v) < 0.0) n = -n;               // culling is off: light back faces too
    float3 l = normalize(-u.lightDirection.xyz);
    float3 h = normalize(l + v);

    float diffuse  = max(dot(n, l), 0.0);
    float specular = pow(max(dot(n, h), 0.0), 64.0);
    float rim      = pow(1.0 - max(dot(n, v), 0.0), 3.0);

    float3 color = in.color * 0.12 + float3(0.02, 0.03, 0.06)
                 + in.color * diffuse * 0.85
                 + specular * 0.6
                 + rim * float3(0.3, 0.5, 1.0) * 0.5;
    return float4(color, 1.0);
}
