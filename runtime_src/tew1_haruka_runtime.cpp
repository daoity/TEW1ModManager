// TEW1 Haruka Runtime — Real-time Soft Hair Physics (XPBD/Verlet + 5 Bone Colliders)
// & Independent PMX Facial Expressions (15 Morphs + Auto-Blink + Live Skeleton Retargeting).
// Hooks D3D11 stably without touching dynamically-specialized Draw vtable slots.

#define NOMINMAX
#include <windows.h>
#include <d3d11.h>
#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <unordered_map>
#include <vector>

#pragma comment(lib, "d3d11.lib")
#pragma comment(lib, "user32.lib")

namespace {

constexpr uintptr_t kDeviceRva = 0x88c38c0;
constexpr uint32_t kNumMorphs = 15;
constexpr uint32_t kNumColliders = 5;
constexpr uint32_t kNumDrivers = 7;

// Morph channel indices matching build_haruka_runtime_pack.py
enum MorphChannel : uint32_t {
    M_BLINK = 0,
    M_WINK_L = 1,
    M_WINK_R = 2,
    M_A = 3,
    M_I = 4,
    M_U = 5,
    M_E = 6,
    M_O = 7,
    M_SMILE = 8,
    M_SMILE_EYES = 9,
    M_SURPRISED = 10,
    M_BROW_WORRIED = 11,
    M_BROW_ANGRY = 12,
    M_BROW_UP = 13,
    M_FROWN = 14
};

// ============================================================================
// Compact 3D Math Helpers
// ============================================================================

struct Vec3 {
    float x, y, z;
    Vec3() : x(0), y(0), z(0) {}
    Vec3(float a, float b, float c) : x(a), y(b), z(c) {}
    Vec3 operator+(const Vec3& o) const { return {x + o.x, y + o.y, z + o.z}; }
    Vec3 operator-(const Vec3& o) const { return {x - o.x, y - o.y, z - o.z}; }
    Vec3 operator*(float s) const { return {x * s, y * s, z * s}; }
    Vec3& operator+=(const Vec3& o) { x += o.x; y += o.y; z += o.z; return *this; }
    Vec3& operator-=(const Vec3& o) { x -= o.x; y -= o.y; z -= o.z; return *this; }
};

inline float Dot(const Vec3& a, const Vec3& b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
inline Vec3 Cross(const Vec3& a, const Vec3& b) {
    return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x};
}
inline float LenSq(const Vec3& v) { return Dot(v, v); }
inline float Len(const Vec3& v) { return std::sqrt(LenSq(v)); }
inline Vec3 Normalize(const Vec3& v) {
    float l = Len(v);
    return l > 1e-7f ? Vec3{v.x / l, v.y / l, v.z / l} : Vec3{0, 0, 1};
}
inline Vec3 Lerp(const Vec3& a, const Vec3& b, float t) {
    return {a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t, a.z + (b.z - a.z) * t};
}
inline float Clamp01(float v) { return v < 0.f ? 0.f : (v > 1.f ? 1.f : v); }

// 3x4 row-major affine matrix (matches HLSL float4[3] skinning & model matrices)
struct Mat34 {
    float m[12]; // row 0: [0..3], row 1: [4..7], row 2: [8..11]

    static Mat34 Identity() {
        Mat34 r{};
        r.m[0] = 1.f; r.m[5] = 1.f; r.m[10] = 1.f;
        return r;
    }
};

inline Vec3 MulPoint(const Mat34& a, const Vec3& p) {
    return {
        a.m[0] * p.x + a.m[1] * p.y + a.m[2] * p.z + a.m[3],
        a.m[4] * p.x + a.m[5] * p.y + a.m[6] * p.z + a.m[7],
        a.m[8] * p.x + a.m[9] * p.y + a.m[10] * p.z + a.m[11]
    };
}

inline Vec3 MulDir(const Mat34& a, const Vec3& v) {
    return {
        a.m[0] * v.x + a.m[1] * v.y + a.m[2] * v.z,
        a.m[4] * v.x + a.m[5] * v.y + a.m[6] * v.z,
        a.m[8] * v.x + a.m[9] * v.y + a.m[10] * v.z
    };
}

inline Mat34 MulMat(const Mat34& a, const Mat34& b) {
    Mat34 r{};
    for (int row = 0; row < 3; row++) {
        const float a0 = a.m[row * 4 + 0];
        const float a1 = a.m[row * 4 + 1];
        const float a2 = a.m[row * 4 + 2];
        const float a3 = a.m[row * 4 + 3];
        r.m[row * 4 + 0] = a0 * b.m[0] + a1 * b.m[4] + a2 * b.m[8];
        r.m[row * 4 + 1] = a0 * b.m[1] + a1 * b.m[5] + a2 * b.m[9];
        r.m[row * 4 + 2] = a0 * b.m[2] + a1 * b.m[6] + a2 * b.m[10];
        r.m[row * 4 + 3] = a0 * b.m[3] + a1 * b.m[7] + a2 * b.m[11] + a3;
    }
    return r;
}

inline bool IsValidRigid(const Mat34& a) {
    for (int i = 0; i < 12; i++) {
        if (!std::isfinite(a.m[i])) return false;
    }
    Vec3 r0(a.m[0], a.m[1], a.m[2]);
    Vec3 r1(a.m[4], a.m[5], a.m[6]);
    Vec3 r2(a.m[8], a.m[9], a.m[10]);
    float l0 = LenSq(r0), l1 = LenSq(r1), l2 = LenSq(r2);
    if (l0 < 0.7f || l0 > 1.4f || l1 < 0.7f || l1 > 1.4f || l2 < 0.7f || l2 > 1.4f)
        return false;
    float det = Dot(r0, Cross(r1, r2));
    return det > 0.6f && det < 1.5f;
}

inline Mat34 InvertRigid(const Mat34& a) {
    // General 3x3 inverse for small non-uniform scale safety + translation
    float a00 = a.m[0], a01 = a.m[1], a02 = a.m[2];
    float a10 = a.m[4], a11 = a.m[5], a12 = a.m[6];
    float a20 = a.m[8], a21 = a.m[9], a22 = a.m[10];
    float c00 = a11 * a22 - a12 * a21;
    float c01 = a02 * a21 - a01 * a22;
    float c02 = a01 * a12 - a02 * a11;
    float c10 = a12 * a20 - a10 * a22;
    float c11 = a00 * a22 - a02 * a20;
    float c12 = a02 * a10 - a00 * a12;
    float c20 = a10 * a21 - a11 * a20;
    float c21 = a01 * a20 - a00 * a21;
    float c22 = a00 * a11 - a01 * a10;
    float det = a00 * c00 + a01 * c10 + a02 * c20;
    if (std::fabs(det) < 1e-6f) return Mat34::Identity();
    float invD = 1.f / det;
    Mat34 r{};
    r.m[0] = c00 * invD; r.m[1] = c01 * invD; r.m[2] = c02 * invD;
    r.m[4] = c10 * invD; r.m[5] = c11 * invD; r.m[6] = c12 * invD;
    r.m[8] = c20 * invD; r.m[9] = c21 * invD; r.m[10] = c22 * invD;
    Vec3 t(a.m[3], a.m[7], a.m[11]);
    r.m[3] = -(r.m[0] * t.x + r.m[1] * t.y + r.m[2] * t.z);
    r.m[7] = -(r.m[4] * t.x + r.m[5] * t.y + r.m[6] * t.z);
    r.m[11] = -(r.m[8] * t.x + r.m[9] * t.y + r.m[10] * t.z);
    return r;
}

// Shortest-arc 3x3 rotation matrix mapping unit vector u -> unit vector v
inline void RotationBetween(const Vec3& u, const Vec3& v, float outR[9]) {
    float c = Dot(u, v);
    if (c > 0.99999f) {
        outR[0] = 1; outR[1] = 0; outR[2] = 0;
        outR[3] = 0; outR[4] = 1; outR[5] = 0;
        outR[6] = 0; outR[7] = 0; outR[8] = 1;
        return;
    }
    Vec3 axis = Cross(u, v);
    float s2 = LenSq(axis);
    if (c < -0.9999f || s2 < 1e-10f) {
        Vec3 perp = std::fabs(u.x) < 0.9f ? Vec3{1, 0, 0} : Vec3{0, 1, 0};
        axis = Normalize(Cross(u, perp));
        // 180-degree rotation around axis
        float x = axis.x, y = axis.y, z = axis.z;
        outR[0] = 2 * x * x - 1; outR[1] = 2 * x * y;     outR[2] = 2 * x * z;
        outR[3] = 2 * y * x;     outR[4] = 2 * y * y - 1; outR[5] = 2 * y * z;
        outR[6] = 2 * z * x;     outR[7] = 2 * z * y;     outR[8] = 2 * z * z - 1;
        return;
    }
    // Rodrigues: R = I + [k]_x + [k]_x^2 * (1 / (1 + c))
    float k = 1.f / (1.f + c);
    float vx = axis.x, vy = axis.y, vz = axis.z;
    outR[0] = 1.f - k * (vy * vy + vz * vz);
    outR[1] = -vz + k * (vx * vy);
    outR[2] =  vy + k * (vx * vz);
    outR[3] =  vz + k * (vx * vy);
    outR[4] = 1.f - k * (vx * vx + vz * vz);
    outR[5] = -vx + k * (vy * vz);
    outR[6] = -vy + k * (vx * vz);
    outR[7] =  vx + k * (vy * vz);
    outR[8] = 1.f - k * (vx * vx + vy * vy);
}

inline uint8_t PackNormComp(float v) {
    float scaled = (v * 0.5f + 0.5f) * 255.f;
    if (scaled < 0.f) return 0;
    if (scaled > 255.f) return 255;
    return static_cast<uint8_t>(scaled + 0.5f);
}

// ============================================================================
// Binary Pack Data Structures (matches build_haruka_runtime_pack.py v1)
// ============================================================================

struct DriverSpec {
    int16_t remap;
    Vec3 probe;
};

struct SkeletonProfile {
    uint8_t headRemap;
    int16_t colRemap[kNumColliders];
    Mat34 headAlign;
    DriverSpec drivers[kNumDrivers]; // 0:jaw, 1:lidL, 2:lidR, 3:browL, 4:browR, 5:mcL, 6:mcR
};

struct HairChainAsset {
    uint32_t numBones;
    float stiffness;
    float damping;
    float gravity;
    float radius;
    std::vector<Vec3> restNodes; // numBones + 1
};

struct ColliderAsset {
    uint32_t boneSlot;
    Vec3 startArm;
    Vec3 endArm;
    float radius;
};

struct HairFingerprint {
    uint8_t headRemap;
    uint32_t vertCount;
    float first3Pos[9];
};

struct HairSkinVert {
    uint8_t bone[4];
    uint8_t weight[4];
};

struct SparseMorphDelta {
    uint16_t vertIdx;
    Vec3 delta;
};

struct FaceAsset {
    uint8_t headRemap;
    uint8_t part;
    uint32_t vertCount;
    float first3Pos[9];
    std::vector<SparseMorphDelta> channels[kNumMorphs];
};

struct RuntimePack {
    bool loaded = false;
    std::vector<SkeletonProfile> skeletons;
    std::vector<HairChainAsset> chains;
    std::vector<ColliderAsset> colliders;
    std::vector<HairFingerprint> hairFps;
    std::vector<HairSkinVert> hairWeights;
    std::vector<FaceAsset> faces;
    uint32_t totalHairBones = 0;

    const SkeletonProfile* FindSkeleton(uint8_t headRemap) const {
        for (const auto& s : skeletons)
            if (s.headRemap == headRemap) return &s;
        return nullptr;
    }
};

// ============================================================================
// Runtime Simulation State (per active skeleton headRemap)
// ============================================================================

struct ChainSimState {
    bool initialized = false;
    std::vector<Vec3> pos;
    std::vector<Vec3> prev;
    std::vector<Vec3> anchor;
    std::vector<float> lengths;
};

struct BoneTransformBind {
    Vec3 restHead;
    Vec3 solvedHead;
    float rot[9];
};

struct CharacterState {
    uint8_t headRemap = 0;
    int64_t lastQpc = 0;
    uint64_t frameGen = 0;
    Mat34 lastModelMat = Mat34::Identity();
    bool hasModelMat = false;
    Vec3 prevHeadWorld{};
    bool hasPrevHead = false;

    std::vector<ChainSimState> chainStates;
    std::vector<BoneTransformBind> boneXforms;

    // Facial state
    float morphWeights[kNumMorphs] = {};
    float blinkTimer = 1.8f;
    float blinkPhase = -1.f; // >= 0 while blinking
    bool doubleBlinkQueued = false;
    uint32_t rngState = 0x13579BDFu;
    float demoClock = 0.f;
};

// ============================================================================
// Globals & Logging
// ============================================================================

HANDLE g_log = INVALID_HANDLE_VALUE;
RuntimePack g_pack;
std::mutex g_mtx;
double g_qpcToSec = 0.0;

std::atomic<bool> g_enableHair{true};
std::atomic<bool> g_enableFace{true};
std::atomic<int> g_facePreset{0}; // 0=Auto, 1=Smile, 2=Wink, 3=Surprised, 4=Worried, 5=Angry, 6=VisemeDemo
std::atomic<bool> g_triggerBlink{false};
thread_local bool t_inInternalUpdate = false;

void LogFmt(const char* fmt, ...) {
    if (g_log == INVALID_HANDLE_VALUE) return;
    char buf[512];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    if (n > 0) {
        DWORD w = 0;
        WriteFile(g_log, buf, (DWORD)n, &w, nullptr);
    }
}

float Rand01(uint32_t& state) {
    state = state * 1664525u + 1013904223u;
    return float((state >> 8) & 0x00FFFFFFu) / 16777216.f;
}

// ============================================================================
// Binary Pack Loader
// ============================================================================

struct BinReader {
    const uint8_t* ptr;
    const uint8_t* end;
    template <typename T>
    bool Read(T& out) {
        if (ptr + sizeof(T) > end) return false;
        memcpy(&out, ptr, sizeof(T));
        ptr += sizeof(T);
        return true;
    }
    bool ReadBytes(void* dst, size_t n) {
        if (ptr + n > end) return false;
        memcpy(dst, ptr, n);
        ptr += n;
        return true;
    }
};

bool LoadRuntimePack(const wchar_t* path) {
    HANDLE f = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr);
    if (f == INVALID_HANDLE_VALUE) return false;
    LARGE_INTEGER sz{};
    if (!GetFileSizeEx(f, &sz) || sz.QuadPart <= 32 || sz.QuadPart > 64 * 1024 * 1024) {
        CloseHandle(f);
        return false;
    }
    std::vector<uint8_t> data(static_cast<size_t>(sz.QuadPart));
    DWORD rd = 0;
    bool ok = ReadFile(f, data.data(), static_cast<DWORD>(data.size()), &rd, nullptr) && rd == data.size();
    CloseHandle(f);
    if (!ok) return false;

    BinReader r{data.data(), data.data() + data.size()};
    char magic[4];
    uint32_t version, nSkel, nChains, nCols, nHairFps, nFaces, nMorphs;
    if (!r.ReadBytes(magic, 4) || memcmp(magic, "TEWH", 4) != 0) return false;
    if (!r.Read(version) || version != 1) return false;
    if (!r.Read(nSkel) || !r.Read(nChains) || !r.Read(nCols) || !r.Read(nHairFps) || !r.Read(nFaces) || !r.Read(nMorphs))
        return false;
    if (nMorphs != kNumMorphs || nCols > 16 || nChains > 16) return false;

    RuntimePack pack;
    pack.skeletons.resize(nSkel);
    for (uint32_t i = 0; i < nSkel; i++) {
        auto& sk = pack.skeletons[i];
        uint8_t pad3[3];
        if (!r.Read(sk.headRemap) || !r.ReadBytes(pad3, 3)) return false;
        uint16_t pad2;
        if (!r.ReadBytes(sk.colRemap, sizeof(sk.colRemap)) || !r.Read(pad2)) return false;
        if (!r.ReadBytes(sk.headAlign.m, sizeof(sk.headAlign.m))) return false;
        for (uint32_t d = 0; d < kNumDrivers; d++) {
            uint16_t dp;
            if (!r.Read(sk.drivers[d].remap) || !r.Read(dp) || !r.Read(sk.drivers[d].probe)) return false;
        }
    }

    pack.chains.resize(nChains);
    pack.totalHairBones = 0;
    for (uint32_t i = 0; i < nChains; i++) {
        auto& ch = pack.chains[i];
        if (!r.Read(ch.numBones) || !r.Read(ch.stiffness) || !r.Read(ch.damping) || !r.Read(ch.gravity) || !r.Read(ch.radius))
            return false;
        ch.restNodes.resize(ch.numBones + 1);
        if (!r.ReadBytes(ch.restNodes.data(), ch.restNodes.size() * sizeof(Vec3))) return false;
        pack.totalHairBones += ch.numBones;
    }

    pack.colliders.resize(nCols);
    for (uint32_t i = 0; i < nCols; i++) {
        auto& c = pack.colliders[i];
        if (!r.Read(c.boneSlot) || !r.Read(c.startArm) || !r.Read(c.endArm) || !r.Read(c.radius)) return false;
    }

    pack.hairFps.resize(nHairFps);
    for (uint32_t i = 0; i < nHairFps; i++) {
        auto& fp = pack.hairFps[i];
        uint8_t pad3[3];
        if (!r.Read(fp.headRemap) || !r.ReadBytes(pad3, 3) || !r.Read(fp.vertCount) || !r.ReadBytes(fp.first3Pos, 36))
            return false;
    }

    uint32_t nHairVerts = 0;
    if (!r.Read(nHairVerts) || nHairVerts > 65536) return false;
    pack.hairWeights.resize(nHairVerts);
    if (!r.ReadBytes(pack.hairWeights.data(), nHairVerts * sizeof(HairSkinVert))) return false;

    pack.faces.resize(nFaces);
    for (uint32_t i = 0; i < nFaces; i++) {
        auto& fa = pack.faces[i];
        uint8_t pad2[2];
        if (!r.Read(fa.headRemap) || !r.Read(fa.part) || !r.ReadBytes(pad2, 2) || !r.Read(fa.vertCount) || !r.ReadBytes(fa.first3Pos, 36))
            return false;
        for (uint32_t m = 0; m < kNumMorphs; m++) {
            uint32_t cnt = 0;
            if (!r.Read(cnt) || cnt > 65535) return false;
            fa.channels[m].resize(cnt);
            for (uint32_t k = 0; k < cnt; k++) {
                uint16_t pad;
                if (!r.Read(fa.channels[m][k].vertIdx) || !r.Read(pad) || !r.Read(fa.channels[m][k].delta))
                    return false;
            }
        }
    }

    pack.loaded = true;
    g_pack = std::move(pack);
    LogFmt("Loaded runtime pack: skels=%u chains=%u bones=%u cols=%u hairFps=%u faceSurfs=%u\n",
           nSkel, nChains, g_pack.totalHairBones, nCols, nHairFps, nFaces);
    return true;
}

// ============================================================================
// Hair Physics Solver (exact port of Blender hair_solver.py in world space)
// ============================================================================

struct WorldCapsule {
    Vec3 start;
    Vec3 end;
    float radius;
};

inline Vec3 ClosestPointOnSegment(const Vec3& p, const Vec3& a, const Vec3& b) {
    Vec3 ab = b - a;
    float l2 = LenSq(ab);
    if (l2 < 1e-10f) return a;
    float t = Dot(p - a, ab) / l2;
    t = Clamp01(t);
    return a + ab * t;
}

inline Vec3 PushOutCapsule(const Vec3& p, const WorldCapsule& cap, float limit, const Vec3& fallback) {
    Vec3 nearest = ClosestPointOnSegment(p, cap.start, cap.end);
    Vec3 sep = p - nearest;
    float distSq = LenSq(sep);
    if (distSq >= limit * limit) return {0, 0, 0};
    Vec3 dir = distSq > 1e-10f ? sep : (fallback - nearest);
    if (LenSq(dir) < 1e-10f) dir = Cross(cap.end - cap.start, Vec3{1, 0, 0});
    if (LenSq(dir) < 1e-10f) dir = Vec3{0, 1, 0};
    dir = Normalize(dir);
    return (nearest + dir * limit) - p;
}

void StepHairPhysics(CharacterState& st, const SkeletonProfile& skel, const Mat34& modelMat,
                     const float* c2Floats, size_t c2Bytes, float dt, bool teleported) {
    const size_t nChains = g_pack.chains.size();
    if (st.chainStates.size() != nChains) {
        st.chainStates.resize(nChains);
        st.boneXforms.resize(g_pack.totalHairBones);
    }

    auto readBoneSkin = [&](int16_t remap, Mat34& out) -> bool {
        if (remap < 0) return false;
        size_t off = (size_t)remap * 12;
        if ((off + 12) * sizeof(float) > c2Bytes) return false;
        memcpy(out.m, c2Floats + off, 12 * sizeof(float));
        return IsValidRigid(out);
    };

    Mat34 headSkin{};
    if (!readBoneSkin(skel.headRemap, headSkin)) return;

    Mat34 headWorld = MulMat(modelMat, headSkin);
    Mat34 headWorldInv = InvertRigid(headWorld);

    // Build live world-space capsules for all 5 anatomical colliders
    WorldCapsule capsules[kNumColliders];
    uint32_t capCount = 0;
    for (const auto& col : g_pack.colliders) {
        if (capCount >= kNumColliders) break;
        int16_t bRemap = (col.boneSlot < kNumColliders) ? skel.colRemap[col.boneSlot] : -1;
        Mat34 colSkin{};
        if (!readBoneSkin(bRemap, colSkin)) {
            // Fallback for head-only cutscene skeletons missing shoulder bones
            if (!readBoneSkin(skel.colRemap[2], colSkin)) colSkin = headSkin;
        }
        Mat34 colWorld = MulMat(modelMat, colSkin);
        Vec3 sBind = MulPoint(skel.headAlign, col.startArm);
        Vec3 eBind = MulPoint(skel.headAlign, col.endArm);
        capsules[capCount++] = {MulPoint(colWorld, sBind), MulPoint(colWorld, eBind), col.radius};
    }

    // Check teleport / huge camera cut
    Vec3 headPosW{headWorld.m[3], headWorld.m[7], headWorld.m[11]};
    if (!st.hasPrevHead || Len(headPosW - st.prevHeadWorld) > 65.f) {
        teleported = true;
    }
    st.prevHeadWorld = headPosW;
    st.hasPrevHead = true;

    const int substeps = std::max(2, std::min(12, static_cast<int>(std::lround(dt * 240.f))));
    const float h = dt / float(substeps);
    uint32_t boneCursor = 0;

    for (size_t ci = 0; ci < nChains; ci++) {
        const auto& ch = g_pack.chains[ci];
        auto& cs = st.chainStates[ci];
        const size_t nNodes = ch.restNodes.size();

        std::vector<Vec3> restBind(nNodes);
        std::vector<Vec3> targetW(nNodes);
        for (size_t i = 0; i < nNodes; i++) {
            restBind[i] = MulPoint(skel.headAlign, ch.restNodes[i]);
            targetW[i] = MulPoint(headWorld, restBind[i]);
        }

        if (!cs.initialized || teleported || cs.pos.size() != nNodes) {
            cs.pos = targetW;
            cs.prev = targetW;
            cs.anchor = targetW;
            cs.lengths.resize(nNodes - 1);
            for (size_t i = 0; i + 1 < nNodes; i++) {
                cs.lengths[i] = std::max(0.01f, Len(restBind[i + 1] - restBind[i]));
            }
            cs.initialized = true;
        }

        const float retention = std::pow(1.f - ch.damping, h * 60.f);
        const Vec3 grav(0.f, 0.f, -ch.gravity);
        std::vector<Vec3> stepAnchor(nNodes);

        for (int s = 1; s <= substeps; s++) {
            float alpha = float(s) / float(substeps);
            for (size_t i = 0; i < nNodes; i++)
                stepAnchor[i] = Lerp(cs.anchor[i], targetW[i], alpha);

            cs.pos[0] = stepAnchor[0];
            for (size_t i = 1; i < nNodes; i++) {
                Vec3 vel = (cs.pos[i] - cs.prev[i]) * retention;
                // Clamp max single-substep velocity for rock-solid explosion resistance
                float vLen = Len(vel);
                if (vLen > 8.f) vel = vel * (8.f / vLen);
                cs.prev[i] = cs.pos[i];
                Vec3 force = (stepAnchor[i] - cs.pos[i]) * ch.stiffness + grav;
                cs.pos[i] += vel + force * (h * h);
            }

            for (int iter = 0; iter < 9; iter++) {
                for (size_t i = 0; i + 1 < nNodes; i++) {
                    Vec3 delta = cs.pos[i + 1] - cs.pos[i];
                    float d = Len(delta);
                    if (d < 1e-6f) continue;
                    Vec3 off = delta * (1.f - cs.lengths[i] / d);
                    if (i > 0) {
                        cs.pos[i] += off * 0.5f;
                        cs.pos[i + 1] -= off * 0.5f;
                    } else {
                        cs.pos[i + 1] -= off;
                    }
                }
                for (uint32_t k = 0; k < capCount; k++) {
                    const float limit = capsules[k].radius + ch.radius;
                    for (size_t i = 1; i < nNodes; i++) {
                        cs.pos[i] += PushOutCapsule(cs.pos[i], capsules[k], limit, stepAnchor[i]);
                    }
                    // Mid-segment capsule checks (t = 0.33, 0.67) matching hair_solver.py
                    for (size_t i = 1; i < nNodes; i++) {
                        const float ts[2] = {0.33f, 0.67f};
                        for (float t : ts) {
                            Vec3 mid = Lerp(cs.pos[i - 1], cs.pos[i], t);
                            Vec3 corr = PushOutCapsule(mid, capsules[k], limit, stepAnchor[i]);
                            if (LenSq(corr) < 1e-10f) continue;
                            float a = (i > 1) ? (1.f - t) : 0.f;
                            float denom = a * a + t * t;
                            if (a > 0.f) cs.pos[i - 1] += corr * (a / denom);
                            cs.pos[i] += corr * (t / denom);
                        }
                    }
                }
            }
        }

        cs.anchor = targetW;

        // Convert solved chain back into bind-pose head space for vertex skinning
        std::vector<Vec3> solvedBind(nNodes);
        for (size_t i = 0; i < nNodes; i++) {
            solvedBind[i] = MulPoint(headWorldInv, cs.pos[i]);
        }

        for (uint32_t bi = 0; bi < ch.numBones; bi++) {
            auto& bx = st.boneXforms[boneCursor++];
            bx.restHead = restBind[bi];
            bx.solvedHead = solvedBind[bi];
            Vec3 rDir = Normalize(restBind[bi + 1] - restBind[bi]);
            Vec3 sDir = Normalize(solvedBind[bi + 1] - solvedBind[bi]);
            RotationBetween(rDir, sDir, bx.rot);
        }
    }
}

// ============================================================================
// Independent Facial Morph Controller (Auto-Blink + Live Skeleton Retargeting + Hotkeys)
// ============================================================================

void PollHotkeys() {
    static bool prevF6 = false, prevF7 = false, prevF8 = false, prevF9 = false;
    bool f6 = (GetAsyncKeyState(VK_F6) & 0x8000) != 0;
    bool f7 = (GetAsyncKeyState(VK_F7) & 0x8000) != 0;
    bool f8 = (GetAsyncKeyState(VK_F8) & 0x8000) != 0;
    bool f9 = (GetAsyncKeyState(VK_F9) & 0x8000) != 0;

    if (f6 && !prevF6) {
        bool v = !g_enableFace.load();
        g_enableFace.store(v);
        LogFmt("Hotkey F6: Independent Face = %s\n", v ? "ON" : "OFF");
    }
    if (f7 && !prevF7) {
        int next = (g_facePreset.load() + 1) % 7;
        g_facePreset.store(next);
        static const char* names[7] = {"Auto (Blink+Retarget)", "Smile", "Wink", "Surprised", "Worried", "Angry", "Viseme Demo"};
        LogFmt("Hotkey F7: Face Preset = %d (%s)\n", next, names[next]);
    }
    if (f8 && !prevF8) {
        g_triggerBlink.store(true);
        LogFmt("Hotkey F8: Trigger Blink\n");
    }
    if (f9 && !prevF9) {
        bool v = !g_enableHair.load();
        g_enableHair.store(v);
        LogFmt("Hotkey F9: Soft Hair Physics = %s\n", v ? "ON" : "OFF");
    }
    prevF6 = f6; prevF7 = f7; prevF8 = f8; prevF9 = f9;
}

void StepFacialMorphs(CharacterState& st, const SkeletonProfile& skel,
                      const float* c2Floats, size_t c2Bytes, float dt) {
    float target[kNumMorphs] = {};

    // 1. Natural auto-blink timer (asymmetric realistic human/anime blink)
    if (g_triggerBlink.exchange(false)) {
        st.blinkPhase = 0.f;
        st.doubleBlinkQueued = false;
    }
    float autoBlink = 0.f;
    if (st.blinkPhase >= 0.f) {
        st.blinkPhase += dt;
        // 0..0.065s close, 0.065..0.095s hold, 0.095..0.230s open
        if (st.blinkPhase < 0.065f) {
            float u = st.blinkPhase / 0.065f;
            autoBlink = u * u * (3.f - 2.f * u);
        } else if (st.blinkPhase < 0.095f) {
            autoBlink = 1.f;
        } else if (st.blinkPhase < 0.230f) {
            float u = (st.blinkPhase - 0.095f) / 0.135f;
            autoBlink = 1.f - (u * u * (3.f - 2.f * u));
        } else {
            st.blinkPhase = -1.f;
            if (st.doubleBlinkQueued) {
                st.doubleBlinkQueued = false;
                st.blinkTimer = 0.14f;
            } else {
                st.blinkTimer = 2.6f + Rand01(st.rngState) * 2.8f;
                st.doubleBlinkQueued = (Rand01(st.rngState) < 0.18f);
            }
        }
    } else {
        st.blinkTimer -= dt;
        if (st.blinkTimer <= 0.f) {
            st.blinkPhase = 0.f;
        }
    }

    int preset = g_facePreset.load();
    if (preset == 0) {
        // Auto mode: Natural Blink + Live Sebastian Skeleton Retargeting
        target[M_BLINK] = autoBlink;

        // Read head inverse skin matrix to measure facial bone deviations relative to head
        auto readSkin = [&](int16_t remap, Mat34& out) -> bool {
            if (remap < 0) return false;
            size_t off = (size_t)remap * 12;
            if ((off + 12) * sizeof(float) > c2Bytes) return false;
            memcpy(out.m, c2Floats + off, 12 * sizeof(float));
            return IsValidRigid(out);
        };

        Mat34 headSkin{};
        if (readSkin(skel.headRemap, headSkin)) {
            Mat34 headSkinInv = InvertRigid(headSkin);
            auto driverDelta = [&](int dIdx, Vec3& outDelta) -> bool {
                const auto& drv = skel.drivers[dIdx];
                Mat34 dSkin{};
                if (!readSkin(drv.remap, dSkin)) return false;
                Vec3 liveModel = MulPoint(dSkin, drv.probe);
                Vec3 liveInHead = MulPoint(headSkinInv, liveModel);
                outDelta = liveInHead - drv.probe;
                return LenSq(outDelta) < 25.f; // sanity guard
            };

            // Eyelids (drivers 1, 2): Sebastian eyelid downward drop (-Z) drives Haruka_Blink
            Vec3 dLidL, dLidR;
            bool hasL = driverDelta(1, dLidL);
            bool hasR = driverDelta(2, dLidR);
            if (hasL || hasR) {
                float dropL = hasL ? Clamp01((-dLidL.z - 0.045f) / 0.36f) : 0.f;
                float dropR = hasR ? Clamp01((-dLidR.z - 0.045f) / 0.36f) : 0.f;
                float gameBlink = (hasL && hasR) ? 0.5f * (dropL + dropR) : std::max(dropL, dropR);
                target[M_BLINK] = std::max(target[M_BLINK], gameBlink);
            }

            // Mouth corners (drivers 5, 6 — present on cutscene close-up heads pl0010/pl0011)
            Vec3 dMcL, dMcR;
            bool hasMc = driverDelta(5, dMcL) && driverDelta(6, dMcR);
            float lipWidth = hasMc ? (dMcL.y - dMcR.y) : 0.f; // +Y is left, -Y is right
            float lipLift = hasMc ? 0.5f * (dMcL.z + dMcR.z) : 0.f;

            // Jaw (driver 0): downward chin drop (-Z) drives clean Haruka PMX vowels (A/O/E/I)
            Vec3 dJaw;
            if (driverDelta(0, dJaw)) {
                float jawOpen = Clamp01((-dJaw.z - 0.09f) / 1.25f);
                if (jawOpen > 0.01f) {
                    if (hasMc) {
                        float roundness = Clamp01((-lipWidth - 0.04f) / 0.35f);
                        float wideness = Clamp01((lipWidth - 0.04f) / 0.35f);
                        float aShare = Clamp01(1.f - 0.65f * roundness - 0.55f * wideness);
                        target[M_A] = jawOpen * aShare;
                        target[M_O] = jawOpen * roundness * 0.90f;
                        target[M_E] = jawOpen * wideness * 0.85f;
                    } else {
                        // Smooth natural speech shaping on gameplay rigs
                        target[M_A] = jawOpen * 0.85f;
                        target[M_O] = jawOpen * 0.20f;
                    }
                } else if (hasMc) {
                    if (lipLift > 0.07f) target[M_SMILE] = Clamp01((lipLift - 0.07f) / 0.32f) * 0.85f;
                    else if (lipLift < -0.07f) target[M_FROWN] = Clamp01((-lipLift - 0.07f) / 0.32f) * 0.85f;
                }
            }

            // Eyebrows (drivers 3, 4)
            Vec3 dBrL, dBrR;
            bool hasBL = driverDelta(3, dBrL);
            bool hasBR = driverDelta(4, dBrR);
            if (hasBL || hasBR) {
                float bz = (hasBL && hasBR) ? 0.5f * (dBrL.z + dBrR.z) : (hasBL ? dBrL.z : dBrR.z);
                if (bz > 0.055f) {
                    float up = Clamp01((bz - 0.055f) / 0.35f);
                    target[M_BROW_UP] = up;
                    if (up > 0.55f) target[M_SURPRISED] = (up - 0.55f) * 1.1f;
                } else if (bz < -0.055f) {
                    float down = Clamp01((-bz - 0.055f) / 0.35f);
                    target[M_BROW_WORRIED] = down * 0.75f;
                    target[M_BROW_ANGRY] = down * 0.35f;
                }
            }
        }
    } else if (preset == 1) {
        // Smile
        target[M_SMILE] = 0.92f;
        target[M_SMILE_EYES] = 0.75f;
        target[M_BLINK] = autoBlink * 0.25f;
    } else if (preset == 2) {
        // Wink + Smile
        target[M_WINK_L] = 1.0f;
        target[M_SMILE] = 0.85f;
    } else if (preset == 3) {
        // Surprised
        target[M_SURPRISED] = 0.95f;
        target[M_BROW_UP] = 0.90f;
        target[M_O] = 0.72f;
    } else if (preset == 4) {
        // Worried / horror tension
        target[M_BROW_WORRIED] = 0.95f;
        target[M_FROWN] = 0.70f;
        target[M_BLINK] = autoBlink;
    } else if (preset == 5) {
        // Angry / fierce
        target[M_BROW_ANGRY] = 0.95f;
        target[M_FROWN] = 0.85f;
        target[M_BLINK] = autoBlink;
    } else if (preset == 6) {
        // Animated Viseme + Blink Demo loop (cycles Blink -> A -> I -> U -> E -> O -> Smile every 6s)
        st.demoClock = std::fmod(st.demoClock + dt, 6.0f);
        auto pulse = [&](float center, float halfW) {
            float d = std::fabs(st.demoClock - center);
            if (d >= halfW) return 0.f;
            float u = 1.f - d / halfW;
            return u * u * (3.f - 2.f * u);
        };
        target[M_BLINK] = std::max(pulse(0.55f, 0.35f), pulse(5.55f, 0.30f));
        target[M_A] = pulse(1.45f, 0.45f);
        target[M_I] = pulse(2.25f, 0.42f);
        target[M_U] = pulse(3.00f, 0.42f);
        target[M_E] = pulse(3.75f, 0.42f);
        target[M_O] = pulse(4.50f, 0.45f);
        target[M_SMILE] = pulse(5.25f, 0.50f);
    }

    // Smooth exponential filter (fast response ~28Hz, zero popping)
    const float blend = 1.f - std::exp(-dt * 28.f);
    for (uint32_t m = 0; m < kNumMorphs; m++) {
        st.morphWeights[m] += (target[m] - st.morphWeights[m]) * blend;
        if (st.morphWeights[m] < 0.0005f) st.morphWeights[m] = 0.f;
    }
}

// ============================================================================
// Vertex Buffer Deformers (32-byte TEW1 GPU Vertex Layout)
// ============================================================================

struct TrackedSurfaceVB {
    bool isHair = false;
    uint8_t headRemap = 0;
    uint32_t vertCount = 0;
    const FaceAsset* faceAsset = nullptr;
    std::vector<uint8_t> neutralVerts;
    std::vector<uint8_t> workVerts;
    uint64_t lastUploadedGen = 0;
    bool dirtyNeutral = false;
};

void DeformHairVertices(TrackedSurfaceVB& tvb, const CharacterState& st) {
    const uint32_t vc = tvb.vertCount;
    memcpy(tvb.workVerts.data(), tvb.neutralVerts.data(), (size_t)vc * 32);
    if (!g_enableHair.load() || st.boneXforms.size() < g_pack.totalHairBones || g_pack.hairWeights.size() != vc)
        return;

    const uint8_t* src = tvb.neutralVerts.data();
    uint8_t* dst = tvb.workVerts.data();
    const auto& weights = g_pack.hairWeights;
    const auto& xforms = st.boneXforms;

    for (uint32_t i = 0; i < vc; i++) {
        const auto& hw = weights[i];
        if (hw.bone[0] == 255 && hw.weight[0] == 255) continue; // Rigid scalp vertex

        const uint8_t* sv = src + (size_t)i * 32;
        uint8_t* dv = dst + (size_t)i * 32;

        float px, py, pz;
        memcpy(&px, sv + 0, 4);
        memcpy(&py, sv + 4, 4);
        memcpy(&pz, sv + 8, 4);
        Vec3 pRest(px, py, pz);

        Vec3 outPos(0, 0, 0);
        uint8_t primaryBone = 255;
        uint8_t primaryW = 0;

        for (int k = 0; k < 4; k++) {
            uint8_t w8 = hw.weight[k];
            if (w8 == 0) continue;
            float wf = float(w8) * (1.f / 255.f);
            uint8_t bi = hw.bone[k];
            if (bi == 255 || bi >= xforms.size()) {
                outPos += pRest * wf;
            } else {
                if (w8 > primaryW) { primaryW = w8; primaryBone = bi; }
                const auto& bx = xforms[bi];
                Vec3 rel = pRest - bx.restHead;
                Vec3 rotP{
                    bx.rot[0] * rel.x + bx.rot[1] * rel.y + bx.rot[2] * rel.z,
                    bx.rot[3] * rel.x + bx.rot[4] * rel.y + bx.rot[5] * rel.z,
                    bx.rot[6] * rel.x + bx.rot[7] * rel.y + bx.rot[8] * rel.z
                };
                outPos += (bx.solvedHead + rotP) * wf;
            }
        }

        memcpy(dv + 0, &outPos.x, 4);
        memcpy(dv + 4, &outPos.y, 4);
        memcpy(dv + 8, &outPos.z, 4);

        // Rotate normal & tangent by primary hair bone for consistent lighting
        if (primaryBone < xforms.size()) {
            const float* R = xforms[primaryBone].rot;
            Vec3 n{(float(sv[20]) - 127.5f), (float(sv[21]) - 127.5f), (float(sv[22]) - 127.5f)};
            n = Normalize(n);
            Vec3 rn = Normalize(Vec3{
                R[0] * n.x + R[1] * n.y + R[2] * n.z,
                R[3] * n.x + R[4] * n.y + R[5] * n.z,
                R[6] * n.x + R[7] * n.y + R[8] * n.z
            });
            dv[20] = PackNormComp(rn.x);
            dv[21] = PackNormComp(rn.y);
            dv[22] = PackNormComp(rn.z);

            Vec3 t{(float(sv[24]) - 127.5f), (float(sv[25]) - 127.5f), (float(sv[26]) - 127.5f)};
            t = Normalize(t);
            Vec3 rt = Vec3{
                R[0] * t.x + R[1] * t.y + R[2] * t.z,
                R[3] * t.x + R[4] * t.y + R[5] * t.z,
                R[6] * t.x + R[7] * t.y + R[8] * t.z
            };
            rt = Normalize(rt - rn * Dot(rt, rn));
            dv[24] = PackNormComp(rt.x);
            dv[25] = PackNormComp(rt.y);
            dv[26] = PackNormComp(rt.z);
        }
    }
}

void DeformFaceVertices(TrackedSurfaceVB& tvb, const CharacterState& st) {
    const uint32_t vc = tvb.vertCount;
    memcpy(tvb.workVerts.data(), tvb.neutralVerts.data(), (size_t)vc * 32);
    if (!g_enableFace.load() || !tvb.faceAsset) return;

    uint8_t* dst = tvb.workVerts.data();
    const FaceAsset& fa = *tvb.faceAsset;

    for (uint32_t m = 0; m < kNumMorphs; m++) {
        float w = st.morphWeights[m];
        if (w < 0.001f) continue;
        const auto& entries = fa.channels[m];
        for (const auto& e : entries) {
            if (e.vertIdx >= vc) continue;
            uint8_t* v = dst + (size_t)e.vertIdx * 32;
            float p[3];
            memcpy(p, v, 12);
            p[0] += e.delta.x * w;
            p[1] += e.delta.y * w;
            p[2] += e.delta.z * w;
            memcpy(v, p, 12);
        }
    }
}

// ============================================================================
// D3D11 Hooks (Zero Reliance on Mutated Draw Vtable Slots!)
// ============================================================================

struct TrackedCB {
    uint32_t byteWidth = 0;
    std::vector<uint8_t> shadow;
    void* mappedPtr = nullptr;
};

std::unordered_map<ID3D11Buffer*, TrackedCB> g_cbs;
std::unordered_map<ID3D11Buffer*, TrackedSurfaceVB> g_vbs;
std::unordered_map<uint8_t, CharacterState> g_chars;

ID3D11Buffer* g_boundVB0 = nullptr;
ID3D11Buffer* g_boundVSCB[4] = {};

using FnCreateBuffer = HRESULT(STDMETHODCALLTYPE*)(ID3D11Device*, const D3D11_BUFFER_DESC*, const D3D11_SUBRESOURCE_DATA*, ID3D11Buffer**);
using FnVSSetCB = void(STDMETHODCALLTYPE*)(ID3D11DeviceContext*, UINT, UINT, ID3D11Buffer* const*);
using FnIASetVB = void(STDMETHODCALLTYPE*)(ID3D11DeviceContext*, UINT, UINT, ID3D11Buffer* const*, const UINT*, const UINT*);
using FnMap = HRESULT(STDMETHODCALLTYPE*)(ID3D11DeviceContext*, ID3D11Resource*, UINT, D3D11_MAP, UINT, D3D11_MAPPED_SUBRESOURCE*);
using FnUnmap = void(STDMETHODCALLTYPE*)(ID3D11DeviceContext*, ID3D11Resource*, UINT);
using FnUpdateSub = void(STDMETHODCALLTYPE*)(ID3D11DeviceContext*, ID3D11Resource*, UINT, const D3D11_BOX*, const void*, UINT, UINT);

FnCreateBuffer origCreateBuffer = nullptr;
FnVSSetCB origVSSetCB = nullptr;
FnIASetVB origIASetVB = nullptr;
FnMap origMap = nullptr;
FnUnmap origUnmap = nullptr;
FnUpdateSub origUpdateSub = nullptr;

bool MatchFirst3Pos(const uint8_t* vbBytes, const float expected[9]) {
    for (int v = 0; v < 3; v++) {
        float p[3];
        memcpy(p, vbBytes + v * 32, 12);
        for (int c = 0; c < 3; c++) {
            if (std::fabs(p[c] - expected[v * 3 + c]) > 0.005f) return false;
        }
    }
    return true;
}

HRESULT STDMETHODCALLTYPE HookCreateBuffer(ID3D11Device* dev, const D3D11_BUFFER_DESC* desc,
                                           const D3D11_SUBRESOURCE_DATA* init, ID3D11Buffer** outBuf) {
    HRESULT hr = origCreateBuffer(dev, desc, init, outBuf);
    if (FAILED(hr) || !desc || !outBuf || !*outBuf) return hr;

    // Evict any stale entries if D3D11 reused a previously freed buffer pointer across chapter loads
    {
        std::lock_guard<std::mutex> lk(g_mtx);
        g_vbs.erase(*outBuf);
        g_cbs.erase(*outBuf);
    }

    if (desc->BindFlags & D3D11_BIND_CONSTANT_BUFFER) {
        std::lock_guard<std::mutex> lk(g_mtx);
        TrackedCB cb;
        cb.byteWidth = desc->ByteWidth;
        cb.shadow.resize(desc->ByteWidth);
        if (init && init->pSysMem) memcpy(cb.shadow.data(), init->pSysMem, desc->ByteWidth);
        g_cbs[*outBuf] = std::move(cb);
    } else if (g_pack.loaded && (desc->BindFlags & D3D11_BIND_VERTEX_BUFFER) &&
               init && init->pSysMem && (desc->ByteWidth % 32 == 0) && desc->ByteWidth >= 96) {
        const uint32_t vc = desc->ByteWidth / 32;
        const uint8_t* raw = static_cast<const uint8_t*>(init->pSysMem);
        const uint8_t headRemap = raw[28];

        // Check Hair fingerprints
        for (const auto& fp : g_pack.hairFps) {
            if (fp.vertCount == vc && fp.headRemap == headRemap && MatchFirst3Pos(raw, fp.first3Pos)) {
                std::lock_guard<std::mutex> lk(g_mtx);
                TrackedSurfaceVB tvb;
                tvb.isHair = true;
                tvb.headRemap = headRemap;
                tvb.vertCount = vc;
                tvb.neutralVerts.assign(raw, raw + desc->ByteWidth);
                tvb.workVerts = tvb.neutralVerts;
                g_vbs[*outBuf] = std::move(tvb);
                LogFmt("Hooked Haruka HAIR VB %p (verts=%u, headRemap=%u, usage=%u)\n",
                       *outBuf, vc, headRemap, (unsigned)desc->Usage);
                return hr;
            }
        }

        // Check Face fingerprints
        for (const auto& fa : g_pack.faces) {
            if (fa.vertCount == vc && fa.headRemap == headRemap && MatchFirst3Pos(raw, fa.first3Pos)) {
                std::lock_guard<std::mutex> lk(g_mtx);
                TrackedSurfaceVB tvb;
                tvb.isHair = false;
                tvb.headRemap = headRemap;
                tvb.vertCount = vc;
                tvb.faceAsset = &fa;
                tvb.neutralVerts.assign(raw, raw + desc->ByteWidth);
                tvb.workVerts = tvb.neutralVerts;
                g_vbs[*outBuf] = std::move(tvb);
                LogFmt("Hooked Haruka FACE mat_0%u VB %p (verts=%u, headRemap=%u, usage=%u)\n",
                       fa.part, *outBuf, vc, headRemap, (unsigned)desc->Usage);
                return hr;
            }
        }
    }
    return hr;
}

void TryUpdateBoundHarukaVB(ID3D11DeviceContext* ctx) {
    if (!g_pack.loaded || !g_boundVB0 || !g_boundVSCB[2]) return;

    std::lock_guard<std::mutex> lk(g_mtx);
    auto vbit = g_vbs.find(g_boundVB0);
    if (vbit == g_vbs.end()) return;

    auto c2it = g_cbs.find(g_boundVSCB[2]);
    if (c2it == g_cbs.end()) return;

    TrackedSurfaceVB& tvb = vbit->second;
    const SkeletonProfile* skel = g_pack.FindSkeleton(tvb.headRemap);
    if (!skel) return;

    const auto& c2 = c2it->second;
    const size_t needC2Bytes = ((size_t)tvb.headRemap * 3 + 3) * 16;
    if (c2.byteWidth < needC2Bytes) return;

    const float* c2f = reinterpret_cast<const float*>(c2.shadow.data());
    Mat34 headSkin{};
    memcpy(headSkin.m, c2f + (size_t)tvb.headRemap * 12, 12 * sizeof(float));
    if (!IsValidRigid(headSkin)) return;

    CharacterState& st = g_chars[tvb.headRemap];
    st.headRemap = tvb.headRemap;

    // Extract valid world model matrix from c0[7..9] if present
    if (g_boundVSCB[0]) {
        auto c0it = g_cbs.find(g_boundVSCB[0]);
        if (c0it != g_cbs.end() && c0it->second.byteWidth >= 10 * 16) {
            const float* c0f = reinterpret_cast<const float*>(c0it->second.shadow.data());
            Mat34 candidate{};
            memcpy(candidate.m, c0f + 7 * 4, 12 * sizeof(float));
            if (IsValidRigid(candidate)) {
                st.lastModelMat = candidate;
                st.hasModelMat = true;
            }
        }
    }

    // Advance character simulation at most once per frame (~>=6ms)
    LARGE_INTEGER now{};
    QueryPerformanceCounter(&now);
    double elapsed = (st.lastQpc == 0) ? 0.016 : double(now.QuadPart - st.lastQpc) * g_qpcToSec;
    if (st.lastQpc == 0 || elapsed >= 0.006) {
        PollHotkeys();
        bool bigGap = (st.lastQpc == 0 || elapsed > 0.4);
        float dt = bigGap ? 0.016f : std::min(0.05f, float(elapsed));
        st.lastQpc = now.QuadPart;

        const Mat34& modelMat = st.hasModelMat ? st.lastModelMat : Mat34::Identity();
        if (g_enableHair.load()) {
            StepHairPhysics(st, *skel, modelMat, c2f, c2.byteWidth, dt, bigGap);
        }
        if (g_enableFace.load()) {
            StepFacialMorphs(st, *skel, c2f, c2.byteWidth, dt);
        }
        st.frameGen++;
    }

    // Upload deformed vertices once per frameGen
    if (tvb.lastUploadedGen != st.frameGen) {
        if (tvb.isHair) {
            if (g_enableHair.load()) {
                DeformHairVertices(tvb, st);
                tvb.dirtyNeutral = true;
            } else if (tvb.dirtyNeutral) {
                memcpy(tvb.workVerts.data(), tvb.neutralVerts.data(), tvb.neutralVerts.size());
                tvb.dirtyNeutral = false;
            } else {
                tvb.lastUploadedGen = st.frameGen;
                return;
            }
        } else {
            if (g_enableFace.load()) {
                DeformFaceVertices(tvb, st);
                tvb.dirtyNeutral = true;
            } else if (tvb.dirtyNeutral) {
                memcpy(tvb.workVerts.data(), tvb.neutralVerts.data(), tvb.neutralVerts.size());
                tvb.dirtyNeutral = false;
            } else {
                tvb.lastUploadedGen = st.frameGen;
                return;
            }
        }

        t_inInternalUpdate = true;
        origUpdateSub(ctx, g_boundVB0, 0, nullptr, tvb.workVerts.data(), 0, 0);
        t_inInternalUpdate = false;
        tvb.lastUploadedGen = st.frameGen;
    }
}

void STDMETHODCALLTYPE HookIASetVB(ID3D11DeviceContext* ctx, UINT startSlot, UINT numBufs,
                                   ID3D11Buffer* const* bufs, const UINT* strides, const UINT* offsets) {
    if (startSlot == 0 && numBufs >= 1 && bufs) {
        g_boundVB0 = bufs[0];
        if (g_boundVB0) TryUpdateBoundHarukaVB(ctx);
    }
    origIASetVB(ctx, startSlot, numBufs, bufs, strides, offsets);
}

void STDMETHODCALLTYPE HookVSSetCB(ID3D11DeviceContext* ctx, UINT startSlot, UINT numBufs, ID3D11Buffer* const* bufs) {
    if (bufs) {
        for (UINT i = 0; i < numBufs && (startSlot + i) < 4; i++) {
            g_boundVSCB[startSlot + i] = bufs[i];
        }
        if (g_boundVB0 && startSlot <= 2 && (startSlot + numBufs) > 2) {
            TryUpdateBoundHarukaVB(ctx);
        }
    }
    origVSSetCB(ctx, startSlot, numBufs, bufs);
}

HRESULT STDMETHODCALLTYPE HookMap(ID3D11DeviceContext* ctx, ID3D11Resource* res, UINT sub,
                                  D3D11_MAP mapType, UINT flags, D3D11_MAPPED_SUBRESOURCE* mapped) {
    HRESULT hr = origMap(ctx, res, sub, mapType, flags, mapped);
    if (SUCCEEDED(hr) && mapped && res) {
        std::lock_guard<std::mutex> lk(g_mtx);
        auto it = g_cbs.find(reinterpret_cast<ID3D11Buffer*>(res));
        if (it != g_cbs.end()) it->second.mappedPtr = mapped->pData;
    }
    return hr;
}

void STDMETHODCALLTYPE HookUnmap(ID3D11DeviceContext* ctx, ID3D11Resource* res, UINT sub) {
    bool updatedBoundC2 = false;
    if (res) {
        std::lock_guard<std::mutex> lk(g_mtx);
        auto it = g_cbs.find(reinterpret_cast<ID3D11Buffer*>(res));
        if (it != g_cbs.end() && it->second.mappedPtr) {
            memcpy(it->second.shadow.data(), it->second.mappedPtr, it->second.byteWidth);
            it->second.mappedPtr = nullptr;
            if (reinterpret_cast<ID3D11Buffer*>(res) == g_boundVSCB[2] && g_boundVB0) {
                updatedBoundC2 = true;
            }
        }
    }
    origUnmap(ctx, res, sub);
    if (updatedBoundC2) {
        TryUpdateBoundHarukaVB(ctx);
    }
}

void STDMETHODCALLTYPE HookUpdateSub(ID3D11DeviceContext* ctx, ID3D11Resource* dst, UINT sub,
                                     const D3D11_BOX* box, const void* src, UINT rowPitch, UINT depthPitch) {
    if (!t_inInternalUpdate && dst && src && !box) {
        std::lock_guard<std::mutex> lk(g_mtx);
        auto it = g_cbs.find(reinterpret_cast<ID3D11Buffer*>(dst));
        if (it != g_cbs.end()) memcpy(it->second.shadow.data(), src, it->second.byteWidth);
    }
    origUpdateSub(ctx, dst, sub, box, src, rowPitch, depthPitch);
}

template <typename T>
void PatchVtable(void** table, int index, T hookFn, T& outOrig) {
    DWORD oldProt = 0;
    if (VirtualProtect(table + index, sizeof(void*), PAGE_READWRITE, &oldProt)) {
        outOrig = reinterpret_cast<T>(table[index]);
        InterlockedExchangePointer(table + index, reinterpret_cast<void*>(hookFn));
        DWORD ignored = 0;
        VirtualProtect(table + index, sizeof(void*), oldProt, &ignored);
    }
}

DWORD WINAPI InitThread(void* param) {
    HMODULE self = static_cast<HMODULE>(param);

    LARGE_INTEGER freq{};
    QueryPerformanceFrequency(&freq);
    g_qpcToSec = freq.QuadPart > 0 ? (1.0 / double(freq.QuadPart)) : (1.0 / 10000000.0);

    wchar_t dllDir[MAX_PATH] = {};
    GetModuleFileNameW(self, dllDir, MAX_PATH);
    wchar_t* slash = wcsrchr(dllDir, L'\\');
    if (slash) *(slash + 1) = L'\0';

    wchar_t logPath[MAX_PATH] = {};
    swprintf_s(logPath, L"%sharuka_runtime.log", dllDir);
    g_log = CreateFileW(logPath, GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, CREATE_ALWAYS, 0, nullptr);
    LogFmt("TEW1 Haruka Runtime v1.0 starting...\n");

    // Read optional env toggles from TEW1ModManager
    wchar_t envVal[32] = {};
    if (GetEnvironmentVariableW(L"TEW1_HARUKA_HAIR", envVal, 32) > 0 && envVal[0] == L'0') g_enableHair.store(false);
    if (GetEnvironmentVariableW(L"TEW1_HARUKA_FACE", envVal, 32) > 0 && envVal[0] == L'0') g_enableFace.store(false);

    // Locate haruka_runtime.bin (env override -> next to DLL)
    wchar_t packPath[MAX_PATH] = {};
    bool packLoaded = false;
    if (GetEnvironmentVariableW(L"TEW1_HARUKA_PACK", packPath, MAX_PATH) > 0) {
        packLoaded = LoadRuntimePack(packPath);
    }
    if (!packLoaded) {
        swprintf_s(packPath, L"%sharuka_runtime.bin", dllDir);
        packLoaded = LoadRuntimePack(packPath);
    }
    if (!packLoaded) {
        LogFmt("ERROR: Could not load haruka_runtime.bin\n");
        return 1;
    }

    LogFmt("Config: HairPhysics=%s, IndependentFace=%s (Hotkeys: F6=Face On/Off, F7=Cycle Preset, F8=Blink, F9=Hair On/Off)\n",
           g_enableHair.load() ? "ON" : "OFF", g_enableFace.load() ? "ON" : "OFF");

    auto image = reinterpret_cast<uintptr_t>(GetModuleHandleW(L"EvilWithin.exe"));
    if (!image) return 2;

    for (int retry = 0; retry < 400; retry++) {
        ID3D11Device* dev = nullptr;
        SIZE_T rd = 0;
        if (ReadProcessMemory(GetCurrentProcess(), reinterpret_cast<void*>(image + kDeviceRva), &dev, sizeof(dev), &rd) && dev) {
            void** devVt = *reinterpret_cast<void***>(dev);
            if (devVt && devVt[3]) {
                HMODULE owner = nullptr;
                if (GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                                       reinterpret_cast<LPCWSTR>(devVt[3]), &owner) &&
                    owner == GetModuleHandleW(L"d3d11.dll")) {
                    ID3D11DeviceContext* ctx = nullptr;
                    dev->GetImmediateContext(&ctx);
                    if (ctx) {
                        void** ctxVt = *reinterpret_cast<void***>(ctx);
                        PatchVtable(devVt, 3, HookCreateBuffer, origCreateBuffer);
                        PatchVtable(ctxVt, 7, HookVSSetCB, origVSSetCB);
                        PatchVtable(ctxVt, 14, HookMap, origMap);
                        PatchVtable(ctxVt, 15, HookUnmap, origUnmap);
                        PatchVtable(ctxVt, 18, HookIASetVB, origIASetVB);
                        PatchVtable(ctxVt, 48, HookUpdateSub, origUpdateSub);
                        ctx->Release();
                        LogFmt("D3D11 hooks active (dev=%p, ctx=%p). Ready for Haruka!\n", dev, ctx);
                        return 0;
                    }
                }
            }
        }
        Sleep(50);
    }
    LogFmt("Timed out waiting for D3D11 device.\n");
    return 3;
}

} // namespace

BOOL WINAPI DllMain(HMODULE self, DWORD reason, void*) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(self);
        HANDLE th = CreateThread(nullptr, 0, InitThread, self, 0, nullptr);
        if (th) CloseHandle(th);
    }
    return TRUE;
}
