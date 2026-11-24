// TEW1 Generic Dynamic Physics, Facial Morph & Character Emissive Runtime (tew1_dyn_runtime.dll)
// Character-agnostic: loads any Mod's base/generated/tew1_dyn.bin (v1 or v2).
// - Present-locked VB updates: Depth Pre-Pass, Shadow Pass, Forward Lighting Pass, and Velocity Pass
//   always render identical geometry (zero darkening / Z-mismatch artifacts).
// - Mouth stays 100% on original bone skinning (zero mouth morph override).
// - Eyes/Brows drive 3 clean states: Natural Eye Blink, Hurt (auto on damage + F10 debug), Death (auto on death).
// - Character Material Self-Illumination Modes:
//     F7 = Soft Emissive (toggle ON/OFF)
//     F8 = Bright Anime Emissive (toggle ON/OFF)
//     F9 = Full Unlit Emissive (toggle ON/OFF)
//     F10 = Debug Hurt Expression (Shift+F10 lock Hurt, Ctrl+F10 lock Death)
//     F6 = Facial Morph Master Toggle

#define NOMINMAX
#include <windows.h>
#include <d3d11.h>
#include <d3dcompiler.h>
#include <dxgi.h>
#include <algorithm>
#include <atomic>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#pragma comment(lib, "d3d11.lib")
#pragma comment(lib, "dxgi.lib")
#pragma comment(lib, "user32.lib")

namespace {

constexpr uintptr_t kSwapChainRva     = 0x88c38a0;
constexpr uintptr_t kDeviceRva        = 0x88c38c0;
constexpr uintptr_t kXA2VoiceStartRva = 0x318AC0;

constexpr uint32_t kNumMorphs    = 15;
constexpr uint32_t kNumColliders = 5;
constexpr uint32_t kNumDrivers   = 7;

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
// 3D Math Helpers
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
inline float Smoothstep01(float t) {
    float u = Clamp01(t);
    return u * u * (3.f - 2.f * u);
}

struct Mat34 {
    float m[12];
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
        float x = axis.x, y = axis.y, z = axis.z;
        outR[0] = 2 * x * x - 1; outR[1] = 2 * x * y;     outR[2] = 2 * x * z;
        outR[3] = 2 * y * x;     outR[4] = 2 * y * y - 1; outR[5] = 2 * y * z;
        outR[6] = 2 * z * x;     outR[7] = 2 * z * y;     outR[8] = 2 * z * z - 1;
        return;
    }
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
// Generic Binary Pack Data Structures (tew1_dyn.bin v1 / v2 — TEWH)
// ============================================================================

struct DriverSpec {
    int16_t remap;
    Vec3 probe;
};

struct SkeletonProfile {
    uint8_t headRemap;
    int16_t colRemap[kNumColliders];
    Mat34 headAlign;
    DriverSpec drivers[kNumDrivers];
};

struct HairChainAsset {
    uint32_t numBones;
    float stiffness;
    float damping;
    float gravity;
    float radius;
    std::vector<Vec3> restNodes;
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

struct ExtraCharFingerprint {
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
    std::vector<ExtraCharFingerprint> extraCharFps;
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
    bool seenThisFrame = false;

    Mat34 capturedModelMat = Mat34::Identity();
    bool hasModelMat = false;
    std::vector<float> capturedC2;
    bool hasC2 = false;

    Vec3 prevHeadWorld{};
    bool hasPrevHead = false;

    std::vector<ChainSimState> chainStates;
    std::vector<BoneTransformBind> boneXforms;

    float morphWeights[kNumMorphs] = {};
    float blinkTimer = 1.8f;
    float blinkPhase = -1.f;
    bool doubleBlinkQueued = false;
    uint32_t rngState = 0x13579BDFu;

    uint32_t lastHurtSeq = 0;
    uint32_t lastDeathSeq = 0;
    float hurtPhase = -1.f;
    float deathEnv = 0.f;
    float deathHoldTimer = 0.f;
};

struct TrackedSurfaceVB {
    bool isHair = false;
    uint8_t headRemap = 0;
    uint32_t vertCount = 0;
    const FaceAsset* faceAsset = nullptr;
    std::vector<uint8_t> neutralVerts;
    std::vector<uint8_t> workVerts;
    bool seenThisFrame = false;
    bool dirtyNeutral = false;
};

// ============================================================================
// Globals & Logging
// ============================================================================

HANDLE g_log = INVALID_HANDLE_VALUE;
RuntimePack g_pack;
std::mutex g_mtx;
double g_qpcToSec = 0.0;
ID3D11Device* g_device = nullptr;
ID3D11DeviceContext* g_immCtx = nullptr;
bool g_presentHooked = false;
bool g_audioHooked = false;

// Hotkey / runtime switches
std::atomic<bool> g_enableHair{true};
std::atomic<bool> g_enableFace{true};
std::atomic<int>  g_facePreset{0};      // 0=Auto(Blink+Hurt+Death), 1=LockHurtPreview, 2=LockDeathPreview
std::atomic<int>  g_emissiveMode{0};    // 0=Off, 1=Soft(F7), 2=Bright(F8), 3=Full(F9)
std::atomic<bool> g_emissiveDirty{true};

// Audio-driven & debug Hurt / Death triggers
std::atomic<uint32_t> g_hurtEventSeq{0};
std::atomic<uint32_t> g_deathEventSeq{0};
std::atomic<bool>     g_isDeadState{false};

thread_local bool t_inInternalUpdate = false;
thread_local bool t_inInternalDraw   = false;

// Per-context D3D11 bound state (isolated per Immediate/Deferred ID3D11DeviceContext*, lock-free lookup!)
struct CtxBoundState {
    ID3D11DeviceContext* ctx = nullptr;
    ID3D11Buffer* boundVB0 = nullptr;
    ID3D11Buffer* boundVSCB[4] = {};
    ID3D11PixelShader* boundPS = nullptr;
    ID3D11Buffer* boundPSCB0 = nullptr;
    uint32_t boundPSCB0Size = 0;
    ID3D11ShaderResourceView* boundPSSRV[16] = {};
};

constexpr int kMaxCtxSlots = 128;
CtxBoundState g_ctxSlots[kMaxCtxSlots];
std::atomic<int> g_ctxSlotCount{0};
std::mutex g_ctxSlotMtx;

inline CtxBoundState& GetCtxState(ID3D11DeviceContext* ctx) {
    int n = g_ctxSlotCount.load(std::memory_order_acquire);
    for (int i = 0; i < n; i++) {
        if (g_ctxSlots[i].ctx == ctx) return g_ctxSlots[i];
    }
    std::lock_guard<std::mutex> lk(g_ctxSlotMtx);
    n = g_ctxSlotCount.load(std::memory_order_relaxed);
    for (int i = 0; i < n; i++) {
        if (g_ctxSlots[i].ctx == ctx) return g_ctxSlots[i];
    }
    if (n < kMaxCtxSlots) {
        g_ctxSlots[n] = CtxBoundState{};
        g_ctxSlots[n].ctx = ctx;
        g_ctxSlotCount.store(n + 1, std::memory_order_release);
        return g_ctxSlots[n];
    }
    return g_ctxSlots[kMaxCtxSlots - 1];
}

// Self-illumination GPU resources & telemetry
ID3D11PixelShader* g_emissivePS = nullptr;
ID3D11Buffer*      g_emissiveCB = nullptr;
std::atomic<uint64_t> g_frameCount{0};
std::atomic<uint64_t> g_drawIndexedCalls{0};
std::atomic<uint64_t> g_drawInstCalls{0};
std::atomic<uint64_t> g_charVBDraws{0};
std::atomic<uint64_t> g_emissiveDrawCount{0};
std::atomic<bool>     g_loggedCharDrawDiag{false};

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

bool ContainsAsciiCI(const char* haystack, const char* needle) {
    if (!haystack || !needle || !*needle) return false;
    size_t nLen = std::strlen(needle);
    for (const char* p = haystack; *p; p++) {
        size_t i = 0;
        while (i < nLen && p[i] && std::tolower((unsigned char)p[i]) == std::tolower((unsigned char)needle[i])) {
            i++;
        }
        if (i == nLen) return true;
    }
    return false;
}

bool ContainsBytes(const uint8_t* data, size_t len, const char* needle) {
    size_t nLen = std::strlen(needle);
    if (!data || len < nLen) return false;
    for (size_t i = 0; i + nLen <= len; i++) {
        if (memcmp(data + i, needle, nLen) == 0) return true;
    }
    return false;
}

// ============================================================================
// Binary Pack Loader (v1 & v2)
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
    if (!r.Read(version) || (version != 1 && version != 2)) return false;
    if (!r.Read(nSkel) || !r.Read(nChains) || !r.Read(nCols) || !r.Read(nHairFps) || !r.Read(nFaces) || !r.Read(nMorphs))
        return false;
    if (nMorphs != kNumMorphs || nCols > 16 || nChains > 32) return false;

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
    if (nHairVerts > 0 && !r.ReadBytes(pack.hairWeights.data(), nHairVerts * sizeof(HairSkinVert))) return false;

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

    if (version >= 2 && r.ptr + 4 <= r.end) {
        uint32_t nExtra = 0;
        if (r.Read(nExtra) && nExtra <= 4096) {
            pack.extraCharFps.resize(nExtra);
            for (uint32_t i = 0; i < nExtra; i++) {
                if (!r.Read(pack.extraCharFps[i].vertCount) || !r.ReadBytes(pack.extraCharFps[i].first3Pos, 36)) {
                    pack.extraCharFps.clear();
                    break;
                }
            }
        }
    }

    pack.loaded = true;
    g_pack = std::move(pack);
    LogFmt("Loaded tew1_dyn pack v%u: skels=%u chains=%u bones=%u cols=%u hairFps=%u faceSurfs=%u extraCharVBs=%u\n",
           version, nSkel, nChains, g_pack.totalHairBones, nCols, nHairFps, nFaces,
           (uint32_t)g_pack.extraCharFps.size());
    return true;
}

// ============================================================================
// Hair Physics Solver (World-Space XPBD/Verlet + 5 Bone Capsule Colliders)
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
    float t = Clamp01(Dot(p - a, ab) / l2);
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
    if (nChains == 0) return;
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

    WorldCapsule capsules[16];
    uint32_t capCount = 0;
    for (const auto& col : g_pack.colliders) {
        if (capCount >= 16) break;
        int16_t bRemap = (col.boneSlot < kNumColliders) ? skel.colRemap[col.boneSlot] : -1;
        Mat34 colSkin{};
        if (!readBoneSkin(bRemap, colSkin)) {
            if (!readBoneSkin(skel.colRemap[2], colSkin)) colSkin = headSkin;
        }
        Mat34 colWorld = MulMat(modelMat, colSkin);
        Vec3 sBind = MulPoint(skel.headAlign, col.startArm);
        Vec3 eBind = MulPoint(skel.headAlign, col.endArm);
        capsules[capCount++] = {MulPoint(colWorld, sBind), MulPoint(colWorld, eBind), col.radius};
    }

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
// Simplified 3-State Facial Controller & Dedicated Self-Illumination Hotkeys
//   F6  = Facial Morph Master Toggle
//   F7  = Soft Self-Illumination   (toggle ON / OFF)
//   F8  = Bright Self-Illumination (toggle ON / OFF)
//   F9  = Full Self-Illumination   (toggle ON / OFF)
//   F10 = Debug Hurt Expression pulse (Shift+F10 lock Hurt, Ctrl+F10 lock Death)
// ============================================================================

void ToggleEmissiveMode(int mode, const char* keyName, const char* modeName) {
    int cur = g_emissiveMode.load();
    int next = (cur == mode) ? 0 : mode;
    g_emissiveMode.store(next);
    g_emissiveDirty.store(true);
    LogFmt("Hotkey %s: Self-Illumination = %d (%s) [draws=%llu charDraws=%llu emDraws=%llu]\n",
           keyName, next, next == 0 ? "OFF(VanillaLighting)" : modeName,
           (unsigned long long)g_drawIndexedCalls.load(),
           (unsigned long long)g_charVBDraws.load(),
           (unsigned long long)g_emissiveDrawCount.load());
}

void PollHotkeys() {
    static bool prevF7 = false, prevF8 = false, prevF9 = false, prevF10 = false;

    bool f7  = (GetAsyncKeyState(VK_F7)  & 0x8000) != 0;
    bool f8  = (GetAsyncKeyState(VK_F8)  & 0x8000) != 0;
    bool f9  = (GetAsyncKeyState(VK_F9)  & 0x8000) != 0;
    bool f10 = (GetAsyncKeyState(VK_F10) & 0x8000) != 0;

    if (f7 && !prevF7) {
        ToggleEmissiveMode(1, "F7", "SoftEmissive");
    }
    if (f8 && !prevF8) {
        ToggleEmissiveMode(2, "F8", "BrightAnimeEmissive");
    }
    if (f9 && !prevF9) {
        ToggleEmissiveMode(3, "F9", "FullUnlitEmissive");
    }
    if (f10 && !prevF10) {
        bool shift = (GetAsyncKeyState(VK_SHIFT) & 0x8000) != 0;
        bool ctrl  = (GetAsyncKeyState(VK_CONTROL) & 0x8000) != 0;
        if (ctrl) {
            int next = (g_facePreset.load() == 2) ? 0 : 2;
            g_facePreset.store(next);
            LogFmt("Hotkey Ctrl+F10: Lock Death Preview = %s\n", next == 2 ? "ON" : "OFF");
        } else if (shift) {
            int next = (g_facePreset.load() == 1) ? 0 : 1;
            g_facePreset.store(next);
            LogFmt("Hotkey Shift+F10: Lock Hurt Preview = %s\n", next == 1 ? "ON" : "OFF");
        } else {
            g_facePreset.store(0);
            g_isDeadState.store(false);
            g_hurtEventSeq.fetch_add(1);
            LogFmt("Hotkey F10: Debug Trigger HURT Expression pulse\n");
        }
    }

    prevF7 = f7; prevF8 = f8; prevF9 = f9; prevF10 = f10;
}

void StepFacialMorphs(CharacterState& st, float dt, bool teleported) {
    // Mouth morphs (M_A, M_I, M_U, M_E, M_O, M_SMILE, M_FROWN) are ALWAYS 0.0f
    // so the mouth follows the original jaw bone skinning cleanly!
    float target[kNumMorphs] = {};

    if (teleported) {
        g_isDeadState.store(false);
        st.deathEnv = 0.f;
        st.deathHoldTimer = 0.f;
    }

    // 1. Natural periodic eye blink
    float autoBlink = 0.f;
    if (st.blinkPhase >= 0.f) {
        st.blinkPhase += dt;
        if (st.blinkPhase < 0.065f) {
            autoBlink = Smoothstep01(st.blinkPhase / 0.065f);
        } else if (st.blinkPhase < 0.095f) {
            autoBlink = 1.f;
        } else if (st.blinkPhase < 0.230f) {
            autoBlink = 1.f - Smoothstep01((st.blinkPhase - 0.095f) / 0.135f);
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
        if (st.blinkTimer <= 0.f) st.blinkPhase = 0.f;
    }

    // 2. Track Hurt & Death events from audio hook or F10 debug trigger
    uint32_t curHurtSeq = g_hurtEventSeq.load();
    if (curHurtSeq != st.lastHurtSeq) {
        st.lastHurtSeq = curHurtSeq;
        st.hurtPhase = 0.f;
    }
    uint32_t curDeathSeq = g_deathEventSeq.load();
    if (curDeathSeq != st.lastDeathSeq) {
        st.lastDeathSeq = curDeathSeq;
        st.deathHoldTimer = 7.5f;
        st.hurtPhase = -1.f;
    }

    float hurtEnv = 0.f;
    if (st.hurtPhase >= 0.f) {
        st.hurtPhase += dt;
        if (st.hurtPhase < 0.06f) {
            hurtEnv = Smoothstep01(st.hurtPhase / 0.06f);
        } else if (st.hurtPhase < 0.55f) {
            hurtEnv = 1.f;
        } else if (st.hurtPhase < 1.45f) {
            hurtEnv = 1.f - Smoothstep01((st.hurtPhase - 0.55f) / 0.90f);
        } else {
            st.hurtPhase = -1.f;
            hurtEnv = 0.f;
        }
    }

    bool deadActive = g_isDeadState.load() && st.deathHoldTimer > 0.f;
    if (st.deathHoldTimer > 0.f) {
        st.deathHoldTimer = std::max(0.f, st.deathHoldTimer - dt);
        if (st.deathHoldTimer <= 0.f) g_isDeadState.store(false);
    }
    float deadTarget = deadActive ? 1.f : 0.f;
    st.deathEnv += (deadTarget - st.deathEnv) * (1.f - std::exp(-dt * (deadActive ? 9.f : 6.f)));
    if (st.deathEnv < 0.001f) st.deathEnv = 0.f;

    int preset = g_facePreset.load();
    if (preset == 1) {
        // Locked Hurt expression preview (eyes winced + agonized brows + gentle pain gasp, zero lower-teeth clipping)
        target[M_BLINK]        = 0.88f;
        target[M_SMILE_EYES]   = 0.32f;
        target[M_BROW_WORRIED] = 0.95f;
        target[M_BROW_ANGRY]   = 0.55f;
        target[M_A]            = 0.28f;
    } else if (preset == 2) {
        // Locked Death expression preview (lifeless closed eyes + relaxed slightly parted mouth)
        target[M_BLINK]        = 1.00f;
        target[M_BROW_WORRIED] = 0.65f;
        target[M_A]            = 0.12f;
    } else {
        // Idle/CG: mouth morphs stay 0.0f so native skeleton mouth animation drives CG & gameplay!
        target[M_BLINK] = autoBlink;

        if (hurtEnv > 0.001f) {
            target[M_BLINK]        = std::max(target[M_BLINK], 0.88f * hurtEnv);
            target[M_SMILE_EYES]   = 0.32f * hurtEnv;
            target[M_BROW_WORRIED] = 0.95f * hurtEnv;
            target[M_BROW_ANGRY]   = 0.55f * hurtEnv;
            target[M_A]            = 0.28f * hurtEnv;
        }
        if (st.deathEnv > 0.001f) {
            target[M_BLINK]        = std::max(target[M_BLINK], 1.00f * st.deathEnv);
            target[M_SMILE_EYES]   = target[M_SMILE_EYES] * (1.f - st.deathEnv);
            target[M_BROW_WORRIED] = std::max(target[M_BROW_WORRIED] * (1.f - st.deathEnv), 0.65f * st.deathEnv);
            target[M_BROW_ANGRY]   = target[M_BROW_ANGRY] * (1.f - st.deathEnv);
            target[M_A]            = std::max(target[M_A] * (1.f - st.deathEnv), 0.12f * st.deathEnv);
        }
    }

    const float blend = 1.f - std::exp(-dt * 28.f);
    for (uint32_t m = 0; m < kNumMorphs; m++) {
        st.morphWeights[m] += (target[m] - st.morphWeights[m]) * blend;
        if (st.morphWeights[m] < 0.0005f) st.morphWeights[m] = 0.f;
    }
}

// ============================================================================
// Vertex Buffer Deformers
// ============================================================================

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
        if (hw.bone[0] == 255 && hw.weight[0] == 255) continue;

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
            Vec3 ortho = rt - rn * Dot(rt, rn);
            if (LenSq(ortho) > 1e-6f) {
                rt = Normalize(ortho);
                dv[24] = PackNormComp(rt.x);
                dv[25] = PackNormComp(rt.y);
                dv[26] = PackNormComp(rt.z);
            }
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
// Character Material Self-Illumination Pixel Shader (F7 / F8 / F9)
// ============================================================================

static const char* kEmissivePSHlsl = R"HLSL(
cbuffer constantBufferP : register(b0) {
    float4 renderpositiontoviewtexture;
};
cbuffer EmissiveParams : register(b4) {
    float4 u_emissive; // x=emissiveFloor, y=sceneWeight, z=hemiMin, w=rolloff
};
Texture2D texBump : register(t0);
SamplerState sampBump : register(s0);
Texture2D texAlbedo : register(t1);
SamplerState sampAlbedo : register(s1);
Texture2D texLightBuf : register(t10);
SamplerState sampLightBuf : register(s7);

struct PS_IN {
    float4 texcoord0  : TEXCOORD0;
    float4 htexcoord1 : TEXCOORD1;
    float4 htexcoord2 : TEXCOORD2;
    float4 htexcoord3 : TEXCOORD3;
    float4 htexcoord4 : TEXCOORD4;
    float4 position   : SV_Position;
    bool   facing     : SV_IsFrontFace;
};

float4 main(PS_IN input) : SV_Target {
    float2 uv = input.texcoord0.xy;
    float4 albedo = texAlbedo.Sample(sampAlbedo, uv);
    float opacity = albedo.a;
    float3 linAlbedo = albedo.rgb * albedo.rgb;

    float3 bumpN = texBump.Sample(sampBump, uv).xyz * 2.0 - 1.0;
    float3 N;
    N.x = dot(bumpN, input.htexcoord1.xyz);
    N.y = dot(bumpN, input.htexcoord2.xyz);
    N.z = dot(bumpN, input.htexcoord3.xyz);
    float nLen = length(N);
    N = (nLen > 1e-4) ? (N / nLen) : float3(0.0, 0.0, 1.0);
    float3 V = normalize(-input.htexcoord4.xyz);

    float2 screenUV = input.position.xy * renderpositiontoviewtexture.zw + renderpositiontoviewtexture.xy;
    float3 sceneLight = max(texLightBuf.SampleLevel(sampLightBuf, screenUV, 0).rgb, float3(0.0, 0.0, 0.0));

    float hemi = lerp(u_emissive.z, 1.0, N.z * 0.5 + 0.5);
    float ndv = saturate(abs(dot(N, V)));
    float softRim = pow(1.0 - ndv, 2.6) * 0.14 * u_emissive.x;

    float3 selfLit = (u_emissive.x * hemi + softRim).xxx;
    float3 combined = selfLit + sceneLight * u_emissive.y;
    combined = combined / (1.0 + combined * u_emissive.w) * (1.0 + u_emissive.w);

    float3 outRgb = linAlbedo * combined;
    return float4(outRgb * opacity, opacity);
}
)HLSL";

struct EmissiveCBData {
    float emissiveFloor;
    float sceneWeight;
    float hemiMin;
    float rolloff;
};

bool InitEmissiveResources(ID3D11Device* dev,
                           HRESULT(STDMETHODCALLTYPE* rawCreateBuf)(ID3D11Device*, const D3D11_BUFFER_DESC*, const D3D11_SUBRESOURCE_DATA*, ID3D11Buffer**),
                           HRESULT(STDMETHODCALLTYPE* rawCreatePS)(ID3D11Device*, const void*, SIZE_T, ID3D11ClassLinkage*, ID3D11PixelShader**)) {
    HMODULE hComp = LoadLibraryW(L"d3dcompiler_47.dll");
    if (!hComp) {
        LogFmt("Emissive init skipped: d3dcompiler_47.dll not available.\n");
        return false;
    }
    auto fnCompile = reinterpret_cast<pD3DCompile>(GetProcAddress(hComp, "D3DCompile"));
    if (!fnCompile) {
        LogFmt("Emissive init skipped: D3DCompile export missing.\n");
        return false;
    }

    ID3DBlob* code = nullptr;
    ID3DBlob* errs = nullptr;
    HRESULT hr = fnCompile(kEmissivePSHlsl, std::strlen(kEmissivePSHlsl), "tew1_char_emissive.hlsl",
                           nullptr, nullptr, "main", "ps_5_0", D3DCOMPILE_OPTIMIZATION_LEVEL3, 0, &code, &errs);
    if (FAILED(hr) || !code) {
        if (errs) {
            LogFmt("Emissive PS compile error: %s\n", static_cast<const char*>(errs->GetBufferPointer()));
            errs->Release();
        }
        return false;
    }
    if (errs) errs->Release();

    hr = rawCreatePS(dev, code->GetBufferPointer(), code->GetBufferSize(), nullptr, &g_emissivePS);
    code->Release();
    if (FAILED(hr) || !g_emissivePS) {
        LogFmt("Emissive CreatePixelShader failed: hr=0x%08X\n", (unsigned)hr);
        return false;
    }

    D3D11_BUFFER_DESC bd{};
    bd.ByteWidth = sizeof(EmissiveCBData);
    bd.Usage = D3D11_USAGE_DEFAULT;
    bd.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
    EmissiveCBData initData{0.28f, 0.85f, 0.84f, 0.22f};
    D3D11_SUBRESOURCE_DATA srd{&initData, 0, 0};
    hr = rawCreateBuf(dev, &bd, &srd, &g_emissiveCB);
    if (FAILED(hr) || !g_emissiveCB) {
        LogFmt("Emissive CreateBuffer failed: hr=0x%08X\n", (unsigned)hr);
        g_emissivePS->Release();
        g_emissivePS = nullptr;
        return false;
    }

    LogFmt("Character Self-Illumination PS compiled & ready (F7=Soft, F8=Bright, F9=Full).\n");
    return true;
}

// ============================================================================
// XA2_SoundVoice::Start Inline Hook (Auto Hurt/Death Facial Triggers + Audio Log)
// ============================================================================

using FnXA2VoiceStart = void(__fastcall*)(void* voice, int startSample, int flags, uint8_t reverb);
FnXA2VoiceStart origXA2VoiceStart = nullptr;

void __fastcall HookXA2VoiceStart(void* voice, int startSample, int flags, uint8_t reverb) {
    if (voice) {
        void* sample = *reinterpret_cast<void**>(reinterpret_cast<uint8_t*>(voice) + 0xA0);
        if (sample) {
            const char* name = *reinterpret_cast<const char**>(reinterpret_cast<uint8_t*>(sample) + 0x08);
            if (name && *name) {
                bool isSebVoice = ContainsAsciiCI(name, "ingame_voice/sebastian/");
                bool isPlDamage = ContainsAsciiCI(name, "player/damage/");
                bool isPlDead   = ContainsAsciiCI(name, "player/dead/");

                if (isSebVoice || isPlDamage || isPlDead) {
                    int ts = *reinterpret_cast<int*>(reinterpret_cast<uint8_t*>(sample) + 0x48);
                    uint32_t playLen = *reinterpret_cast<uint32_t*>(reinterpret_cast<uint8_t*>(sample) + 0x50);
                    uint32_t bufSz   = *reinterpret_cast<uint32_t*>(reinterpret_cast<uint8_t*>(sample) + 0x58);
                    LogFmt("SoundStart: %s (ts=%d playLen=%u bufSz=%u)\n", name, ts, playLen, bufSz);

                    if ((isSebVoice && ContainsAsciiCI(name, "/death_")) || isPlDead) {
                        g_isDeadState.store(true);
                        g_deathEventSeq.fetch_add(1);
                    } else if ((isSebVoice && ContainsAsciiCI(name, "/damage_")) || isPlDamage) {
                        g_isDeadState.store(false);
                        g_hurtEventSeq.fetch_add(1);
                    } else if (isSebVoice && (ContainsAsciiCI(name, "/action_") ||
                                              ContainsAsciiCI(name, "/attack_") ||
                                              ContainsAsciiCI(name, "/breath") ||
                                              ContainsAsciiCI(name, "/syringe"))) {
                        g_isDeadState.store(false);
                    }
                }
            }
        }
    }
    origXA2VoiceStart(voice, startSample, flags, reverb);
}

bool InstallXA2VoiceStartHook(uintptr_t imageBase) {
    uint8_t* target = reinterpret_cast<uint8_t*>(imageBase + kXA2VoiceStartRva);
    static const uint8_t kExpected[15] = {
        0x48, 0x89, 0x5C, 0x24, 0x18,
        0x48, 0x89, 0x6C, 0x24, 0x20,
        0x57, 0x41, 0x56, 0x41, 0x57
    };
    if (memcmp(target, kExpected, sizeof(kExpected)) != 0) {
        LogFmt("XA2_SoundVoice::Start signature mismatch at +0x%llX; skipping audio hook.\n",
               (unsigned long long)kXA2VoiceStartRva);
        return false;
    }

    uint8_t* tramp = static_cast<uint8_t*>(VirtualAlloc(nullptr, 64, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE));
    if (!tramp) return false;

    memcpy(tramp, target, 15);
    tramp[15] = 0xFF;
    tramp[16] = 0x25;
    uint32_t zero = 0;
    memcpy(tramp + 17, &zero, 4);
    uint64_t retAddr = reinterpret_cast<uint64_t>(target + 15);
    memcpy(tramp + 21, &retAddr, 8);
    FlushInstructionCache(GetCurrentProcess(), tramp, 32);

    origXA2VoiceStart = reinterpret_cast<FnXA2VoiceStart>(tramp);

    DWORD oldProt = 0;
    if (!VirtualProtect(target, 16, PAGE_EXECUTE_READWRITE, &oldProt)) return false;
    target[0] = 0xFF;
    target[1] = 0x25;
    memcpy(target + 2, &zero, 4);
    uint64_t hookAddr = reinterpret_cast<uint64_t>(&HookXA2VoiceStart);
    memcpy(target + 6, &hookAddr, 8);
    target[14] = 0x90;
    FlushInstructionCache(GetCurrentProcess(), target, 16);
    DWORD ignored = 0;
    VirtualProtect(target, 16, oldProt, &ignored);

    LogFmt("Hooked XA2_SoundVoice::Start at %p (auto Hurt/Death facial triggers active)\n", target);
    return true;
}

// ============================================================================
// Multi-Vtable-Safe D3D11 + DXGI Present Hooks
// (Handles Win10/11 dynamic CContext vtable swapping & Deferred Contexts!)
// ============================================================================

struct TrackedCB {
    uint32_t byteWidth = 0;
    std::vector<uint8_t> shadow;
    void* mappedPtr = nullptr;
};

std::unordered_map<ID3D11Buffer*, TrackedCB> g_cbs;
std::unordered_map<ID3D11Buffer*, TrackedSurfaceVB> g_vbs;
std::unordered_set<ID3D11Buffer*> g_charVBs;
std::unordered_set<ID3D11PixelShader*> g_forwardAlbedoPS;
std::unordered_map<uint8_t, CharacterState> g_chars;

using FnCreateBuffer          = HRESULT(STDMETHODCALLTYPE*)(ID3D11Device*, const D3D11_BUFFER_DESC*, const D3D11_SUBRESOURCE_DATA*, ID3D11Buffer**);
using FnCreatePixelShader     = HRESULT(STDMETHODCALLTYPE*)(ID3D11Device*, const void*, SIZE_T, ID3D11ClassLinkage*, ID3D11PixelShader**);
using FnCreateDeferredContext = HRESULT(STDMETHODCALLTYPE*)(ID3D11Device*, UINT, ID3D11DeviceContext**);
using FnVSSetCB               = void(STDMETHODCALLTYPE*)(ID3D11DeviceContext*, UINT, UINT, ID3D11Buffer* const*);
using FnPSSetSRV              = void(STDMETHODCALLTYPE*)(ID3D11DeviceContext*, UINT, UINT, ID3D11ShaderResourceView* const*);
using FnPSSetShader           = void(STDMETHODCALLTYPE*)(ID3D11DeviceContext*, ID3D11PixelShader*, ID3D11ClassInstance* const*, UINT);
using FnVSSetShader           = void(STDMETHODCALLTYPE*)(ID3D11DeviceContext*, ID3D11VertexShader*, ID3D11ClassInstance* const*, UINT);
using FnDrawIndexed           = void(STDMETHODCALLTYPE*)(ID3D11DeviceContext*, UINT, UINT, INT);
using FnMap                   = HRESULT(STDMETHODCALLTYPE*)(ID3D11DeviceContext*, ID3D11Resource*, UINT, D3D11_MAP, UINT, D3D11_MAPPED_SUBRESOURCE*);
using FnUnmap                 = void(STDMETHODCALLTYPE*)(ID3D11DeviceContext*, ID3D11Resource*, UINT);
using FnPSSetCB               = void(STDMETHODCALLTYPE*)(ID3D11DeviceContext*, UINT, UINT, ID3D11Buffer* const*);
using FnIASetVB               = void(STDMETHODCALLTYPE*)(ID3D11DeviceContext*, UINT, UINT, ID3D11Buffer* const*, const UINT*, const UINT*);
using FnDrawIndexedInstanced  = void(STDMETHODCALLTYPE*)(ID3D11DeviceContext*, UINT, UINT, UINT, INT, UINT);
using FnUpdateSub             = void(STDMETHODCALLTYPE*)(ID3D11DeviceContext*, ID3D11Resource*, UINT, const D3D11_BOX*, const void*, UINT, UINT);
using FnPresent               = HRESULT(STDMETHODCALLTYPE*)(IDXGISwapChain*, UINT, UINT);

struct CtxVtableOrig {
    FnVSSetCB              vsSetCB = nullptr;
    FnPSSetSRV             psSetSRV = nullptr;
    FnPSSetShader          psSetShader = nullptr;
    FnVSSetShader          vsSetShader = nullptr;
    FnDrawIndexed          drawIndexed = nullptr;
    FnMap                  map = nullptr;
    FnUnmap                unmap = nullptr;
    FnPSSetCB              psSetCB = nullptr;
    FnIASetVB              iaSetVB = nullptr;
    FnDrawIndexedInstanced drawIndexedInstanced = nullptr;
    FnUpdateSub            updateSub = nullptr;
    bool                   heapWritable = false;
};

std::mutex g_vtMtx;
std::unordered_map<void**, CtxVtableOrig> g_ctxVtables;
CtxVtableOrig g_fallbackOrig{};

FnCreateBuffer          origCreateBuffer = nullptr;
FnCreatePixelShader     origCreatePS = nullptr;
FnCreateDeferredContext origCreateDeferredCtx = nullptr;
FnPresent               origPresent = nullptr;

template <typename T>
void PatchVtableSlot(void** table, int index, T hookFn, T& outOrig) {
    if (table[index] == reinterpret_cast<void*>(hookFn)) return;
    DWORD oldProt = 0;
    if (VirtualProtect(table + index, sizeof(void*), PAGE_READWRITE, &oldProt)) {
        outOrig = reinterpret_cast<T>(table[index]);
        InterlockedExchangePointer(table + index, reinterpret_cast<void*>(hookFn));
        DWORD ignored = 0;
        VirtualProtect(table + index, sizeof(void*), oldProt, &ignored);
    }
}

CtxVtableOrig GetCtxOrig(ID3D11DeviceContext* ctx) {
    void** vt = *reinterpret_cast<void***>(ctx);
    std::lock_guard<std::mutex> lk(g_vtMtx);
    auto it = g_ctxVtables.find(vt);
    if (it != g_ctxVtables.end()) return it->second;
    return g_fallbackOrig;
}

// Forward declarations of context hooks
void STDMETHODCALLTYPE HookVSSetCB(ID3D11DeviceContext*, UINT, UINT, ID3D11Buffer* const*);
void STDMETHODCALLTYPE HookPSSetSRV(ID3D11DeviceContext*, UINT, UINT, ID3D11ShaderResourceView* const*);
void STDMETHODCALLTYPE HookPSSetShader(ID3D11DeviceContext*, ID3D11PixelShader*, ID3D11ClassInstance* const*, UINT);
void STDMETHODCALLTYPE HookVSSetShader(ID3D11DeviceContext*, ID3D11VertexShader*, ID3D11ClassInstance* const*, UINT);
void STDMETHODCALLTYPE HookDrawIndexed(ID3D11DeviceContext*, UINT, UINT, INT);
HRESULT STDMETHODCALLTYPE HookMap(ID3D11DeviceContext*, ID3D11Resource*, UINT, D3D11_MAP, UINT, D3D11_MAPPED_SUBRESOURCE*);
void STDMETHODCALLTYPE HookUnmap(ID3D11DeviceContext*, ID3D11Resource*, UINT);
void STDMETHODCALLTYPE HookPSSetCB(ID3D11DeviceContext*, UINT, UINT, ID3D11Buffer* const*);
void STDMETHODCALLTYPE HookIASetVB(ID3D11DeviceContext*, UINT, UINT, ID3D11Buffer* const*, const UINT*, const UINT*);
void STDMETHODCALLTYPE HookDrawIndexedInstanced(ID3D11DeviceContext*, UINT, UINT, UINT, INT, UINT);
void STDMETHODCALLTYPE HookUpdateSub(ID3D11DeviceContext*, ID3D11Resource*, UINT, const D3D11_BOX*, const void*, UINT, UINT);

// Win10/11 d3d11.dll dynamically overwrites vt[12] (DrawIndexed) & vt[20] (DrawIndexedInstanced)
// inside its inline heap vtable whenever shaders/state change. Reassert immediately after state calls!
inline void ReassertDrawHooks(ID3D11DeviceContext* ctx) {
    if (!ctx) return;
    void** vt = *reinterpret_cast<void***>(ctx);
    if (!vt) return;
    void* cur12 = vt[12];
    void* cur20 = vt[20];
    if (cur12 == reinterpret_cast<void*>(HookDrawIndexed) &&
        cur20 == reinterpret_cast<void*>(HookDrawIndexedInstanced)) {
        return;
    }
    std::lock_guard<std::mutex> lk(g_vtMtx);
    auto it = g_ctxVtables.find(vt);
    if (it == g_ctxVtables.end()) return;
    auto& orig = it->second;
    if (cur12 != reinterpret_cast<void*>(HookDrawIndexed)) {
        orig.drawIndexed = reinterpret_cast<FnDrawIndexed>(cur12);
        if (orig.heapWritable) {
            InterlockedExchangePointer(vt + 12, reinterpret_cast<void*>(HookDrawIndexed));
        } else {
            PatchVtableSlot(vt, 12, HookDrawIndexed, orig.drawIndexed);
        }
    }
    if (cur20 != reinterpret_cast<void*>(HookDrawIndexedInstanced)) {
        orig.drawIndexedInstanced = reinterpret_cast<FnDrawIndexedInstanced>(cur20);
        if (orig.heapWritable) {
            InterlockedExchangePointer(vt + 20, reinterpret_cast<void*>(HookDrawIndexedInstanced));
        } else {
            PatchVtableSlot(vt, 20, HookDrawIndexedInstanced, orig.drawIndexedInstanced);
        }
    }
}

void EnsureContextVtableHooked(ID3D11DeviceContext* ctx, const char* tag) {
    if (!ctx) return;
    void** vt = *reinterpret_cast<void***>(ctx);
    if (!vt) return;
    {
        std::lock_guard<std::mutex> lk(g_vtMtx);
        if (g_ctxVtables.find(vt) != g_ctxVtables.end()) {
            // Already registered; just fast-reassert draw hooks without log spam!
            goto reassert_only;
        }
    }
    {
        std::lock_guard<std::mutex> lk(g_vtMtx);
        if (g_ctxVtables.find(vt) != g_ctxVtables.end()) goto reassert_only;

        CtxVtableOrig orig{};
        MEMORY_BASIC_INFORMATION mbi{};
        if (VirtualQuery(vt + 12, &mbi, sizeof(mbi))) {
            orig.heapWritable = (mbi.Protect & (PAGE_READWRITE | PAGE_EXECUTE_READWRITE)) != 0;
        }

        PatchVtableSlot(vt, 7,  HookVSSetCB, orig.vsSetCB);
        PatchVtableSlot(vt, 8,  HookPSSetSRV, orig.psSetSRV);
        PatchVtableSlot(vt, 9,  HookPSSetShader, orig.psSetShader);
        PatchVtableSlot(vt, 11, HookVSSetShader, orig.vsSetShader);
        PatchVtableSlot(vt, 12, HookDrawIndexed, orig.drawIndexed);
        PatchVtableSlot(vt, 14, HookMap, orig.map);
        PatchVtableSlot(vt, 15, HookUnmap, orig.unmap);
        PatchVtableSlot(vt, 16, HookPSSetCB, orig.psSetCB);
        PatchVtableSlot(vt, 18, HookIASetVB, orig.iaSetVB);
        PatchVtableSlot(vt, 20, HookDrawIndexedInstanced, orig.drawIndexedInstanced);
        PatchVtableSlot(vt, 48, HookUpdateSub, orig.updateSub);

        g_ctxVtables[vt] = orig;
        if (!g_fallbackOrig.drawIndexed) g_fallbackOrig = orig;
        LogFmt("Hooked Context vtable %p (%s, writable=%d, totalVtables=%zu)\n",
               vt, tag, orig.heapWritable ? 1 : 0, g_ctxVtables.size());
        return;
    }
reassert_only:
    ReassertDrawHooks(ctx);
}

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

HRESULT STDMETHODCALLTYPE HookCreateDeferredContext(ID3D11Device* dev, UINT flags, ID3D11DeviceContext** outCtx) {
    HRESULT hr = origCreateDeferredCtx(dev, flags, outCtx);
    if (SUCCEEDED(hr) && outCtx && *outCtx) {
        EnsureContextVtableHooked(*outCtx, "DeferredCtx");
    }
    return hr;
}

HRESULT STDMETHODCALLTYPE HookCreatePixelShader(ID3D11Device* dev, const void* bytecode, SIZE_T len,
                                                ID3D11ClassLinkage* linkage, ID3D11PixelShader** outPS) {
    HRESULT hr = origCreatePS(dev, bytecode, len, linkage, outPS);
    if (SUCCEEDED(hr) && outPS && *outPS && bytecode && len > 64) {
        const uint8_t* b = static_cast<const uint8_t*>(bytecode);
        // Strictly tag ONLY forward character/hair lighting shaders (lppalbedoalphaforwardanisotropic* / lppalbedoalphahair)
        // NEVER tag depth-fill (occluderhairtrans), shadow (occludershadowblendhair), or velocity (velocityhair) shaders!
        bool isForwardAlbedo = ContainsBytes(b, len, "samp_tex_transmap") &&
                               ContainsBytes(b, len, "samp_tex_lightprepasslightbuffer") &&
                               ContainsBytes(b, len, "samp_tex_hairlut");
        std::lock_guard<std::mutex> lk(g_mtx);
        if (isForwardAlbedo) {
            g_forwardAlbedoPS.insert(*outPS);
            LogFmt("Tagged Character Forward Color PS %p (size=%zu)\n", *outPS, len);
        } else {
            g_forwardAlbedoPS.erase(*outPS);
        }
    }
    return hr;
}

HRESULT STDMETHODCALLTYPE HookCreateBuffer(ID3D11Device* dev, const D3D11_BUFFER_DESC* desc,
                                           const D3D11_SUBRESOURCE_DATA* init, ID3D11Buffer** outBuf) {
    HRESULT hr = origCreateBuffer(dev, desc, init, outBuf);
    if (FAILED(hr) || !desc || !outBuf || !*outBuf) return hr;

    {
        std::lock_guard<std::mutex> lk(g_mtx);
        g_vbs.erase(*outBuf);
        g_charVBs.erase(*outBuf);
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
                g_charVBs.insert(*outBuf);
                LogFmt("Hooked Dynamic HAIR VB %p (verts=%u, headRemap=%u)\n", *outBuf, vc, headRemap);
                return hr;
            }
        }

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
                g_charVBs.insert(*outBuf);
                LogFmt("Hooked Dynamic FACE part=%u VB %p (verts=%u, headRemap=%u)\n", fa.part, *outBuf, vc, headRemap);
                return hr;
            }
        }

        for (const auto& efp : g_pack.extraCharFps) {
            if (efp.vertCount == vc && MatchFirst3Pos(raw, efp.first3Pos)) {
                std::lock_guard<std::mutex> lk(g_mtx);
                g_charVBs.insert(*outBuf);
                LogFmt("Tagged Character Body/Acc VB %p (verts=%u)\n", *outBuf, vc);
                return hr;
            }
        }
    }
    return hr;
}

void CaptureBoundSurfaceState(CtxBoundState& cs) {
    if (!g_pack.loaded || !cs.boundVB0 || !cs.boundVSCB[2]) return;

    std::lock_guard<std::mutex> lk(g_mtx);
    auto vbit = g_vbs.find(cs.boundVB0);
    if (vbit == g_vbs.end()) return;

    auto c2it = g_cbs.find(cs.boundVSCB[2]);
    if (c2it == g_cbs.end()) return;

    TrackedSurfaceVB& tvb = vbit->second;
    const auto& c2 = c2it->second;
    const size_t needC2Bytes = ((size_t)tvb.headRemap * 3 + 3) * 16;
    if (c2.byteWidth < needC2Bytes) return;

    const float* c2f = reinterpret_cast<const float*>(c2.shadow.data());
    Mat34 headSkin{};
    memcpy(headSkin.m, c2f + (size_t)tvb.headRemap * 12, 12 * sizeof(float));
    if (!IsValidRigid(headSkin)) return;

    tvb.seenThisFrame = true;

    CharacterState& st = g_chars[tvb.headRemap];
    st.headRemap = tvb.headRemap;
    st.seenThisFrame = true;

    size_t nFloats = c2.byteWidth / sizeof(float);
    if (st.capturedC2.size() != nFloats) st.capturedC2.resize(nFloats);
    memcpy(st.capturedC2.data(), c2f, nFloats * sizeof(float));
    st.hasC2 = true;

    if (cs.boundVSCB[0]) {
        auto c0it = g_cbs.find(cs.boundVSCB[0]);
        if (c0it != g_cbs.end() && c0it->second.byteWidth >= 10 * 16) {
            const float* c0f = reinterpret_cast<const float*>(c0it->second.shadow.data());
            Mat34 candidate{};
            memcpy(candidate.m, c0f + 7 * 4, 12 * sizeof(float));
            if (IsValidRigid(candidate)) {
                st.capturedModelMat = candidate;
                st.hasModelMat = true;
            }
        }
    }
}

void UpdateEmissiveCBIfNeeded() {
    if (!g_emissiveCB || !g_immCtx) return;
    if (!g_emissiveDirty.exchange(false)) return;

    int mode = g_emissiveMode.load();
    EmissiveCBData cb{};
    if (mode == 1) {
        // F7 Soft Emissive: keeps dramatic lighting while lifting dark shadows clearly
        cb = {0.28f, 0.85f, 0.84f, 0.22f};
    } else if (mode == 2) {
        // F8 Bright Anime Emissive: vivid luminous character look in any room
        cb = {0.62f, 0.55f, 0.88f, 0.28f};
    } else {
        // F9 Full Unlit Glow: showcase-grade maximum self-illumination
        cb = {1.05f, 0.22f, 0.92f, 0.30f};
    }
    auto orig = GetCtxOrig(g_immCtx);
    if (orig.updateSub) {
        t_inInternalUpdate = true;
        orig.updateSub(g_immCtx, g_emissiveCB, 0, nullptr, &cb, 0, 0);
        t_inInternalUpdate = false;
    }
}

void UpdateAllAtFrameBoundary() {
    if (!g_pack.loaded || !g_immCtx) return;

    // Re-check immediate context vtable in case d3d11.dll swapped CContext::lpVtbl dynamically!
    EnsureContextVtableHooked(g_immCtx, "PresentCheck");

    uint64_t fc = g_frameCount.fetch_add(1) + 1;
    if (fc == 120) {
        LogFmt("Frame 120 telemetry: drawIndexed=%llu drawInst=%llu charDraws=%llu emDraws=%llu\n",
               (unsigned long long)g_drawIndexedCalls.load(),
               (unsigned long long)g_drawInstCalls.load(),
               (unsigned long long)g_charVBDraws.load(),
               (unsigned long long)g_emissiveDrawCount.load());
    }

    PollHotkeys();
    UpdateEmissiveCBIfNeeded();

    LARGE_INTEGER now{};
    QueryPerformanceCounter(&now);

    auto orig = GetCtxOrig(g_immCtx);
    if (!orig.updateSub) return;

    std::lock_guard<std::mutex> lk(g_mtx);

    for (auto& kv : g_chars) {
        CharacterState& st = kv.second;
        if (!st.seenThisFrame || !st.hasC2) continue;
        st.seenThisFrame = false;

        const SkeletonProfile* skel = g_pack.FindSkeleton(st.headRemap);
        if (!skel) continue;

        double elapsed = (st.lastQpc == 0) ? 0.016 : double(now.QuadPart - st.lastQpc) * g_qpcToSec;
        bool bigGap = (st.lastQpc == 0 || elapsed > 0.4);
        float dt = bigGap ? 0.016f : std::max(0.002f, std::min(0.05f, float(elapsed)));
        st.lastQpc = now.QuadPart;

        const Mat34& modelMat = st.hasModelMat ? st.capturedModelMat : Mat34::Identity();
        size_t c2Bytes = st.capturedC2.size() * sizeof(float);

        if (g_enableHair.load()) {
            StepHairPhysics(st, *skel, modelMat, st.capturedC2.data(), c2Bytes, dt, bigGap);
        }
        if (g_enableFace.load()) {
            StepFacialMorphs(st, dt, bigGap);
        }
    }

    for (auto& kv : g_vbs) {
        ID3D11Buffer* vbPtr = kv.first;
        TrackedSurfaceVB& tvb = kv.second;
        if (!tvb.seenThisFrame) continue;
        tvb.seenThisFrame = false;

        auto cit = g_chars.find(tvb.headRemap);
        if (cit == g_chars.end()) continue;
        const CharacterState& st = cit->second;

        if (tvb.isHair) {
            if (g_enableHair.load()) {
                DeformHairVertices(tvb, st);
                tvb.dirtyNeutral = true;
            } else if (tvb.dirtyNeutral) {
                memcpy(tvb.workVerts.data(), tvb.neutralVerts.data(), tvb.neutralVerts.size());
                tvb.dirtyNeutral = false;
            } else {
                continue;
            }
        } else {
            if (g_enableFace.load()) {
                DeformFaceVertices(tvb, st);
                tvb.dirtyNeutral = true;
            } else if (tvb.dirtyNeutral) {
                memcpy(tvb.workVerts.data(), tvb.neutralVerts.data(), tvb.neutralVerts.size());
                tvb.dirtyNeutral = false;
            } else {
                continue;
            }
        }

        t_inInternalUpdate = true;
        orig.updateSub(g_immCtx, vbPtr, 0, nullptr, tvb.workVerts.data(), 0, 0);
        t_inInternalUpdate = false;
    }
}

bool ShouldApplyEmissiveNow(const CtxBoundState& cs) {
    if (!cs.boundVB0) return false;

    bool isChar = false;
    bool isFwdPS = false;
    {
        std::lock_guard<std::mutex> lk(g_mtx);
        isChar = (g_charVBs.find(cs.boundVB0) != g_charVBs.end());
        if (isChar && cs.boundPS) {
            isFwdPS = (g_forwardAlbedoPS.find(cs.boundPS) != g_forwardAlbedoPS.end());
        }
    }
    if (!isChar) return false;

    g_charVBDraws.fetch_add(1);

    if (g_emissiveMode.load() <= 0 || !g_emissivePS || !g_emissiveCB) return false;
    // STRICTLY require exact forward color PS (never hijack depthfill/shadow/velocity passes -> zero black face artifacts!)
    return isFwdPS;
}

HRESULT STDMETHODCALLTYPE HookPresent(IDXGISwapChain* sc, UINT sync, UINT flags) {
    HRESULT hr = origPresent(sc, sync, flags);
    UpdateAllAtFrameBoundary();
    return hr;
}

void STDMETHODCALLTYPE HookIASetVB(ID3D11DeviceContext* ctx, UINT startSlot, UINT numBufs,
                                   ID3D11Buffer* const* bufs, const UINT* strides, const UINT* offsets) {
    if (startSlot == 0 && numBufs >= 1 && bufs) {
        auto& cs = GetCtxState(ctx);
        cs.boundVB0 = bufs[0];
        if (cs.boundVB0) CaptureBoundSurfaceState(cs);
    }
    GetCtxOrig(ctx).iaSetVB(ctx, startSlot, numBufs, bufs, strides, offsets);
    ReassertDrawHooks(ctx);
}

void STDMETHODCALLTYPE HookVSSetCB(ID3D11DeviceContext* ctx, UINT startSlot, UINT numBufs, ID3D11Buffer* const* bufs) {
    if (bufs) {
        auto& cs = GetCtxState(ctx);
        for (UINT i = 0; i < numBufs && (startSlot + i) < 4; i++) {
            cs.boundVSCB[startSlot + i] = bufs[i];
        }
        if (cs.boundVB0 && startSlot <= 2 && (startSlot + numBufs) > 2) {
            CaptureBoundSurfaceState(cs);
        }
    }
    GetCtxOrig(ctx).vsSetCB(ctx, startSlot, numBufs, bufs);
    ReassertDrawHooks(ctx);
}

void STDMETHODCALLTYPE HookVSSetShader(ID3D11DeviceContext* ctx, ID3D11VertexShader* vs,
                                       ID3D11ClassInstance* const* cls, UINT numCls) {
    GetCtxOrig(ctx).vsSetShader(ctx, vs, cls, numCls);
    ReassertDrawHooks(ctx);
}

void STDMETHODCALLTYPE HookPSSetSRV(ID3D11DeviceContext* ctx, UINT startSlot, UINT numViews,
                                    ID3D11ShaderResourceView* const* views) {
    if (views) {
        auto& cs = GetCtxState(ctx);
        for (UINT i = 0; i < numViews && (startSlot + i) < 16; i++) {
            cs.boundPSSRV[startSlot + i] = views[i];
        }
    }
    GetCtxOrig(ctx).psSetSRV(ctx, startSlot, numViews, views);
    ReassertDrawHooks(ctx);
}

void STDMETHODCALLTYPE HookPSSetShader(ID3D11DeviceContext* ctx, ID3D11PixelShader* ps,
                                       ID3D11ClassInstance* const* cls, UINT numCls) {
    if (!t_inInternalDraw) {
        GetCtxState(ctx).boundPS = ps;
    }
    GetCtxOrig(ctx).psSetShader(ctx, ps, cls, numCls);
    if (!t_inInternalDraw) {
        ReassertDrawHooks(ctx);
    }
}

void STDMETHODCALLTYPE HookPSSetCB(ID3D11DeviceContext* ctx, UINT startSlot, UINT numBufs, ID3D11Buffer* const* bufs) {
    if (!t_inInternalDraw && bufs && startSlot == 0 && numBufs >= 1) {
        auto& cs = GetCtxState(ctx);
        cs.boundPSCB0 = bufs[0];
        uint32_t sz = 0;
        if (bufs[0]) {
            std::lock_guard<std::mutex> lk(g_mtx);
            auto it = g_cbs.find(bufs[0]);
            if (it != g_cbs.end()) sz = it->second.byteWidth;
        }
        cs.boundPSCB0Size = sz;
    }
    GetCtxOrig(ctx).psSetCB(ctx, startSlot, numBufs, bufs);
    if (!t_inInternalDraw) {
        ReassertDrawHooks(ctx);
    }
}

void STDMETHODCALLTYPE HookDrawIndexed(ID3D11DeviceContext* ctx, UINT indexCount, UINT startIndex, INT baseVertex) {
    g_drawIndexedCalls.fetch_add(1);
    auto orig = GetCtxOrig(ctx);
    auto& cs = GetCtxState(ctx);
    if (ShouldApplyEmissiveNow(cs)) {
        t_inInternalDraw = true;
        orig.psSetShader(ctx, g_emissivePS, nullptr, 0);
        orig.psSetCB(ctx, 4, 1, &g_emissiveCB);
        void** vt = *reinterpret_cast<void***>(ctx);
        FnDrawIndexed realDraw = (vt && vt[12] != reinterpret_cast<void*>(HookDrawIndexed))
                                 ? reinterpret_cast<FnDrawIndexed>(vt[12])
                                 : orig.drawIndexed;
        realDraw(ctx, indexCount, startIndex, baseVertex);
        ID3D11Buffer* nullCB = nullptr;
        orig.psSetCB(ctx, 4, 1, &nullCB);
        orig.psSetShader(ctx, cs.boundPS, nullptr, 0);
        t_inInternalDraw = false;
        ReassertDrawHooks(ctx);
        if (g_emissiveDrawCount.fetch_add(1) == 0) {
            LogFmt("First Character Self-Illumination DrawIndexed executed (ctx=%p, VB=%p, origPS=%p, mode=%d)!\n",
                   ctx, cs.boundVB0, cs.boundPS, g_emissiveMode.load());
        }
        return;
    }
    orig.drawIndexed(ctx, indexCount, startIndex, baseVertex);
    ReassertDrawHooks(ctx);
}

void STDMETHODCALLTYPE HookDrawIndexedInstanced(ID3D11DeviceContext* ctx, UINT indexCountPerInst, UINT instCount,
                                                UINT startIndex, INT baseVertex, UINT startInst) {
    g_drawInstCalls.fetch_add(1);
    auto orig = GetCtxOrig(ctx);
    auto& cs = GetCtxState(ctx);
    if (ShouldApplyEmissiveNow(cs)) {
        t_inInternalDraw = true;
        orig.psSetShader(ctx, g_emissivePS, nullptr, 0);
        orig.psSetCB(ctx, 4, 1, &g_emissiveCB);
        void** vt = *reinterpret_cast<void***>(ctx);
        FnDrawIndexedInstanced realDraw = (vt && vt[20] != reinterpret_cast<void*>(HookDrawIndexedInstanced))
                                          ? reinterpret_cast<FnDrawIndexedInstanced>(vt[20])
                                          : orig.drawIndexedInstanced;
        realDraw(ctx, indexCountPerInst, instCount, startIndex, baseVertex, startInst);
        ID3D11Buffer* nullCB = nullptr;
        orig.psSetCB(ctx, 4, 1, &nullCB);
        orig.psSetShader(ctx, cs.boundPS, nullptr, 0);
        t_inInternalDraw = false;
        ReassertDrawHooks(ctx);
        if (g_emissiveDrawCount.fetch_add(1) == 0) {
            LogFmt("First Character Self-Illumination DrawIndexedInstanced executed (ctx=%p, VB=%p, origPS=%p, mode=%d)!\n",
                   ctx, cs.boundVB0, cs.boundPS, g_emissiveMode.load());
        }
        return;
    }
    orig.drawIndexedInstanced(ctx, indexCountPerInst, instCount, startIndex, baseVertex, startInst);
    ReassertDrawHooks(ctx);
}

HRESULT STDMETHODCALLTYPE HookMap(ID3D11DeviceContext* ctx, ID3D11Resource* res, UINT sub,
                                  D3D11_MAP mapType, UINT flags, D3D11_MAPPED_SUBRESOURCE* mapped) {
    HRESULT hr = GetCtxOrig(ctx).map(ctx, res, sub, mapType, flags, mapped);
    if (SUCCEEDED(hr) && mapped && res) {
        std::lock_guard<std::mutex> lk(g_mtx);
        auto it = g_cbs.find(reinterpret_cast<ID3D11Buffer*>(res));
        if (it != g_cbs.end()) it->second.mappedPtr = mapped->pData;
    }
    return hr;
}

void STDMETHODCALLTYPE HookUnmap(ID3D11DeviceContext* ctx, ID3D11Resource* res, UINT sub) {
    bool updatedBoundC2 = false;
    auto& cs = GetCtxState(ctx);
    if (res) {
        std::lock_guard<std::mutex> lk(g_mtx);
        auto it = g_cbs.find(reinterpret_cast<ID3D11Buffer*>(res));
        if (it != g_cbs.end() && it->second.mappedPtr) {
            memcpy(it->second.shadow.data(), it->second.mappedPtr, it->second.byteWidth);
            it->second.mappedPtr = nullptr;
            if (reinterpret_cast<ID3D11Buffer*>(res) == cs.boundVSCB[2] && cs.boundVB0) {
                updatedBoundC2 = true;
            }
        }
    }
    GetCtxOrig(ctx).unmap(ctx, res, sub);
    if (updatedBoundC2) CaptureBoundSurfaceState(cs);
}

void STDMETHODCALLTYPE HookUpdateSub(ID3D11DeviceContext* ctx, ID3D11Resource* dst, UINT sub,
                                     const D3D11_BOX* box, const void* src, UINT rowPitch, UINT depthPitch) {
    if (!t_inInternalUpdate && dst && src && !box) {
        std::lock_guard<std::mutex> lk(g_mtx);
        auto it = g_cbs.find(reinterpret_cast<ID3D11Buffer*>(dst));
        if (it != g_cbs.end()) memcpy(it->second.shadow.data(), src, it->second.byteWidth);
    }
    GetCtxOrig(ctx).updateSub(ctx, dst, sub, box, src, rowPitch, depthPitch);
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
    swprintf_s(logPath, L"%stew1_dyn_runtime.log", dllDir);
    g_log = CreateFileW(logPath, GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, CREATE_ALWAYS, 0, nullptr);
    LogFmt("TEW1 Generic Dynamic Runtime v2.2 (Clean Emissive F7/F8/F9 + HurtMouthOpen F10 + NativeMouthRig) starting...\n");

    wchar_t envVal[32] = {};
    if (GetEnvironmentVariableW(L"TEW1_DYN_HAIR", envVal, 32) > 0 && envVal[0] == L'0') g_enableHair.store(false);
    if (GetEnvironmentVariableW(L"TEW1_DYN_FACE", envVal, 32) > 0 && envVal[0] == L'0') g_enableFace.store(false);
    if (GetEnvironmentVariableW(L"TEW1_DYN_EMISSIVE", envVal, 32) > 0) {
        int em = _wtoi(envVal);
        if (em >= 0 && em <= 3) g_emissiveMode.store(em);
    }
    LogFmt("Initial switches: HairPhysics=%s, FacialMorphs=%s, SelfIllumination=%d\n",
           g_enableHair.load() ? "ON" : "OFF", g_enableFace.load() ? "ON" : "OFF", g_emissiveMode.load());
    LogFmt("Hotkeys: F7=SoftEmissive F8=BrightEmissive F9=FullEmissive F10=DebugHurt(Shift/Ctrl=Lock) [Face=ManagerToggleOnly]\n");

    wchar_t packPath[MAX_PATH] = {};
    bool packLoaded = false;
    if (GetEnvironmentVariableW(L"TEW1_DYN_PACK", packPath, MAX_PATH) > 0) {
        packLoaded = LoadRuntimePack(packPath);
    }
    if (!packLoaded) {
        swprintf_s(packPath, L"%stew1_dyn.bin", dllDir);
        packLoaded = LoadRuntimePack(packPath);
    }
    if (!packLoaded) {
        LogFmt("No tew1_dyn.bin found; runtime staying idle.\n");
        return 1;
    }

    auto image = reinterpret_cast<uintptr_t>(GetModuleHandleW(L"EvilWithin.exe"));
    if (!image) return 2;

    g_audioHooked = InstallXA2VoiceStartHook(image);

    bool d3dHooked = false;
    for (int retry = 0; retry < 4000; retry++) {
        if (!d3dHooked) {
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
                            g_device = dev;
                            g_immCtx = ctx;

                            PatchVtableSlot(devVt, 3,  HookCreateBuffer, origCreateBuffer);
                            PatchVtableSlot(devVt, 15, HookCreatePixelShader, origCreatePS);
                            PatchVtableSlot(devVt, 27, HookCreateDeferredContext, origCreateDeferredCtx);

                            InitEmissiveResources(dev, origCreateBuffer, origCreatePS);
                            EnsureContextVtableHooked(ctx, "ImmCtxInit");

                            d3dHooked = true;
                            LogFmt("D3D11 hooks active (dev=%p, ctx=%p, audioHook=%d, emissivePS=%p)\n",
                                   dev, ctx, g_audioHooked ? 1 : 0, g_emissivePS);
                        }
                    }
                }
            }
        }
        if (d3dHooked && !g_presentHooked) {
            IDXGISwapChain* sc = nullptr;
            SIZE_T rd = 0;
            if (ReadProcessMemory(GetCurrentProcess(), reinterpret_cast<void*>(image + kSwapChainRva), &sc, sizeof(sc), &rd) && sc) {
                void** scVt = *reinterpret_cast<void***>(sc);
                if (scVt && scVt[8]) {
                    PatchVtableSlot(scVt, 8, HookPresent, origPresent);
                    g_presentHooked = true;
                    LogFmt("IDXGISwapChain::Present hooked (sc=%p). All runtime systems active!\n", sc);
                    return 0;
                }
            }
        }
        Sleep(d3dHooked ? 50 : 5);
    }
    LogFmt("Init finished (d3dHooked=%d, presentHooked=%d)\n", d3dHooked ? 1 : 0, g_presentHooked ? 1 : 0);
    return 0;
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
