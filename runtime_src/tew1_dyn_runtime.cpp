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
constexpr uint32_t kMaxVariants  = 16;

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
    uint8_t anchorSlot = 0; // 0 = head, 1..5 = colRemap[anchorSlot - 1] (e.g. 3 = spine_02 for chest!)
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
    uint8_t matchAnyBone = 0;   // v3 fallback: 1 if VB vert[0] bone != headRemap
    uint8_t vert0Remap = 0;     // v3.1: exact expected raw[28] bone remap
    uint8_t useVert0Remap = 0;  // v3.1: 1 when vert0Remap (+ vertLastRemap) is populated
    uint8_t vertLastRemap = 0;  // v3.2: exact expected raw[(vc-1)*32 + 28] bone remap
    uint32_t vertCount;
    uint32_t weightOffset = 0;  // v3: offset into RuntimePack::hairWeights
    float first3Pos[9];
};

struct ExtraCharFingerprint {
    uint32_t vertCount;
    float first3Pos[9];
};

struct VariantGroup {
    wchar_t label[48] = {};
    bool hidden = false;
    std::vector<ExtraCharFingerprint> fps;
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
    uint32_t version = 1;
    std::vector<SkeletonProfile> skeletons;
    std::vector<HairChainAsset> chains;
    std::vector<ColliderAsset> colliders;
    std::vector<HairFingerprint> hairFps;
    std::vector<HairSkinVert> hairWeights;
    std::vector<FaceAsset> faces;
    std::vector<ExtraCharFingerprint> extraCharFps;
    std::vector<VariantGroup> variants;
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
    bool boneXformsValid = false;

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
    uint32_t weightOffset = 0;
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
    UINT boundVB0Stride = 32;
    UINT boundVB0Offset = 0;
    ID3D11Buffer* boundVSCB[4] = {};
    ID3D11PixelShader* boundPS = nullptr;
    ID3D11Buffer* boundPSCB0 = nullptr;
    uint32_t boundPSCB0Size = 0;
    ID3D11ShaderResourceView* boundPSSRV[16] = {};
};

constexpr int kMaxCtxSlots = 512;
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

// Self-illumination & Sheer-Cloth GPU resources & telemetry
ID3D11PixelShader* g_emissivePS = nullptr;
ID3D11Buffer*      g_emissiveCB = nullptr;
ID3D11PixelShader* g_sheerPS = nullptr;
ID3D11Buffer*      g_sheerCB = nullptr;
ID3D11BlendState*  g_sheerBlend = nullptr;
ID3D11BlendState*  g_opaqueBlend = nullptr;
std::unordered_map<uint64_t, ID3D11DepthStencilState*> g_sheerDSSCache;
std::unordered_map<uint64_t, ID3D11RasterizerState*>   g_sheerRSCache;
std::unordered_set<ID3D11Buffer*> g_loggedSheerVBs;
std::unordered_map<ID3D11Buffer*, uint64_t> g_pinnedVBs; // AddRef'd VBs so chapter unload NEVER causes UAF in nvwgf2umx.dll!
std::atomic<bool>  g_depthDirKnown{false};
std::atomic<bool>  g_depthIsReverseZ{false};
std::atomic<int>   g_sheerClothMode{2};      // 0=不透明, 1=高透薄纱(22-45%), 2=中透轻纱(默认42-62%), 3=微透奶纱(62-78%)
std::atomic<uint64_t> g_frameCount{0};
std::atomic<uint64_t> g_drawIndexedCalls{0};
std::atomic<uint64_t> g_drawInstCalls{0};
std::atomic<uint64_t> g_charVBDraws{0};
std::atomic<uint64_t> g_emissiveDrawCount{0};
std::atomic<uint64_t> g_sheerDrawCount{0};
std::atomic<bool>     g_loggedCharDrawDiag{false};

// In-game Insert Variant Overlay state & D3D11 resources
struct VariantVBState {
    int groupIdx = -1;
    bool isSheerCloth = false;
    bool seenThisFrame = false;
    bool origHasNaN = false;
    ID3D11Buffer* sheerVB = nullptr;
    std::vector<uint8_t> neutralVerts;
    std::vector<uint8_t> hiddenVerts;
};
std::atomic<bool> g_overlayOpen{false};
std::atomic<bool> g_overlayDirty{true};
std::atomic<int>  g_overlayCursor{0};
std::atomic<UINT> g_panelToggleVK{VK_OEM_3}; // Default: ` (~ key below Esc, 0xC0); customizable in-panel or tew1_dyn_hotkey.ini!
std::atomic<bool> g_rebindingKey{false};
std::atomic<bool> g_rebindWaitRelease{false};
wchar_t           g_dllDir[MAX_PATH] = {};
std::atomic<bool> g_variantHidden[kMaxVariants] = {};
std::unordered_map<ID3D11Buffer*, int> g_vbVariantGroup;
std::unordered_map<ID3D11Buffer*, VariantVBState> g_variantVBs;

inline bool IsSheerVariantLabel(const wchar_t* label) {
    if (!label || !*label) return false;
    return (wcsstr(label, L"睡衣") != nullptr) || (wcsstr(label, L"透明") != nullptr) || (wcsstr(label, L"Sheer") != nullptr);
}

inline bool HasAnySheerVariant() {
    for (const auto& vg : g_pack.variants) {
        if (IsSheerVariantLabel(vg.label)) return true;
    }
    return false;
}

void GetVkLabelW(UINT vk, wchar_t* out, size_t cap) {
    if (vk == VK_OEM_3) { swprintf_s(out, cap, L"`"); return; }
    if (vk == VK_INSERT) { swprintf_s(out, cap, L"Insert"); return; }
    if (vk == VK_HOME) { swprintf_s(out, cap, L"Home"); return; }
    if (vk == VK_END) { swprintf_s(out, cap, L"End"); return; }
    if (vk == VK_DELETE) { swprintf_s(out, cap, L"Del"); return; }
    if (vk == VK_PRIOR) { swprintf_s(out, cap, L"PgUp"); return; }
    if (vk == VK_NEXT) { swprintf_s(out, cap, L"PgDn"); return; }
    if (vk == VK_TAB) { swprintf_s(out, cap, L"Tab"); return; }
    if (vk == VK_CAPITAL) { swprintf_s(out, cap, L"Caps"); return; }
    if (vk == VK_OEM_MINUS) { swprintf_s(out, cap, L"-"); return; }
    if (vk == VK_OEM_PLUS) { swprintf_s(out, cap, L"="); return; }
    if (vk == VK_OEM_4) { swprintf_s(out, cap, L"["); return; }
    if (vk == VK_OEM_6) { swprintf_s(out, cap, L"]"); return; }
    if (vk == VK_OEM_5) { swprintf_s(out, cap, L"\\"); return; }
    if (vk >= VK_F1 && vk <= VK_F12) { swprintf_s(out, cap, L"F%u", vk - VK_F1 + 1); return; }
    if ((vk >= 'A' && vk <= 'Z') || (vk >= '0' && vk <= '9')) { swprintf_s(out, cap, L"%c", (wchar_t)vk); return; }
    if (vk >= VK_NUMPAD0 && vk <= VK_NUMPAD9) { swprintf_s(out, cap, L"Num%u", vk - VK_NUMPAD0); return; }
    swprintf_s(out, cap, L"0x%02X", vk & 0xFF);
}

void GetVkConfigNameA(UINT vk, char* out, size_t cap) {
    if (vk == VK_OEM_3) { snprintf(out, cap, "`"); return; }
    if (vk == VK_INSERT) { snprintf(out, cap, "INSERT"); return; }
    if (vk == VK_HOME) { snprintf(out, cap, "HOME"); return; }
    if (vk == VK_END) { snprintf(out, cap, "END"); return; }
    if (vk == VK_DELETE) { snprintf(out, cap, "DEL"); return; }
    if (vk == VK_PRIOR) { snprintf(out, cap, "PGUP"); return; }
    if (vk == VK_NEXT) { snprintf(out, cap, "PGDN"); return; }
    if (vk == VK_TAB) { snprintf(out, cap, "TAB"); return; }
    if (vk == VK_CAPITAL) { snprintf(out, cap, "CAPS"); return; }
    if (vk == VK_OEM_MINUS) { snprintf(out, cap, "-"); return; }
    if (vk == VK_OEM_PLUS) { snprintf(out, cap, "="); return; }
    if (vk == VK_OEM_4) { snprintf(out, cap, "["); return; }
    if (vk == VK_OEM_6) { snprintf(out, cap, "]"); return; }
    if (vk >= VK_F1 && vk <= VK_F12) { snprintf(out, cap, "F%u", vk - VK_F1 + 1); return; }
    if ((vk >= 'A' && vk <= 'Z') || (vk >= '0' && vk <= '9')) { snprintf(out, cap, "%c", (char)vk); return; }
    if (vk >= VK_NUMPAD0 && vk <= VK_NUMPAD9) { snprintf(out, cap, "NUM%u", vk - VK_NUMPAD0); return; }
    snprintf(out, cap, "0x%02X", vk & 0xFF);
}

UINT ParseVkFromStrA(const char* raw) {
    if (!raw) return VK_OEM_3;
    while (*raw == ' ' || *raw == '\t') raw++;
    char buf[64] = {};
    size_t n = 0;
    while (raw[n] && raw[n] != '\r' && raw[n] != '\n' && raw[n] != '#' && raw[n] != ';' && n + 1 < sizeof(buf)) {
        buf[n] = (char)std::toupper((unsigned char)raw[n]);
        n++;
    }
    while (n > 0 && (buf[n - 1] == ' ' || buf[n - 1] == '\t')) buf[--n] = '\0';
    if (n == 0) return VK_OEM_3;
    if (strcmp(buf, "`") == 0 || strcmp(buf, "~") == 0 || strcmp(buf, "OEM_3") == 0 || strcmp(buf, "GRAVE") == 0) return VK_OEM_3;
    if (strcmp(buf, "INSERT") == 0 || strcmp(buf, "INS") == 0) return VK_INSERT;
    if (strcmp(buf, "HOME") == 0) return VK_HOME;
    if (strcmp(buf, "END") == 0) return VK_END;
    if (strcmp(buf, "DEL") == 0 || strcmp(buf, "DELETE") == 0) return VK_DELETE;
    if (strcmp(buf, "PGUP") == 0 || strcmp(buf, "PAGEUP") == 0) return VK_PRIOR;
    if (strcmp(buf, "PGDN") == 0 || strcmp(buf, "PAGEDOWN") == 0) return VK_NEXT;
    if (strcmp(buf, "TAB") == 0) return VK_TAB;
    if (strcmp(buf, "CAPS") == 0 || strcmp(buf, "CAPSLOCK") == 0) return VK_CAPITAL;
    if (strcmp(buf, "-") == 0) return VK_OEM_MINUS;
    if (strcmp(buf, "=") == 0) return VK_OEM_PLUS;
    if (strcmp(buf, "[") == 0) return VK_OEM_4;
    if (strcmp(buf, "]") == 0) return VK_OEM_6;
    if (buf[0] == 'F' && n >= 2 && n <= 3) {
        int fn = atoi(buf + 1);
        if (fn >= 1 && fn <= 12) return (UINT)(VK_F1 + fn - 1);
    }
    if (strncmp(buf, "NUM", 3) == 0 && n == 4 && buf[3] >= '0' && buf[3] <= '9') {
        return (UINT)(VK_NUMPAD0 + (buf[3] - '0'));
    }
    if (n == 1 && ((buf[0] >= 'A' && buf[0] <= 'Z') || (buf[0] >= '0' && buf[0] <= '9'))) {
        return (UINT)(unsigned char)buf[0];
    }
    if (n >= 3 && buf[0] == '0' && buf[1] == 'X') {
        unsigned v = (unsigned)strtoul(buf + 2, nullptr, 16);
        if (v >= 0x08 && v <= 0xFE) return v;
    }
    unsigned dec = (unsigned)strtoul(buf, nullptr, 10);
    if (dec >= 0x08 && dec <= 0xFE) return dec;
    return VK_OEM_3;
}

void SavePanelHotkeyConfig(UINT vk) {
    if (!g_dllDir[0]) return;
    wchar_t iniPath[MAX_PATH] = {};
    swprintf_s(iniPath, L"%stew1_dyn_hotkey.ini", g_dllDir);
    char keyName[32] = {};
    GetVkConfigNameA(vk, keyName, sizeof(keyName));
    char content[512] = {};
    snprintf(content, sizeof(content),
             "# TEW1 服装差分面板自定义快捷键配置\r\n"
             "# 可在游戏内按当前快捷键打开面板 -> 点第 [9] 项直接改键，或手动修改下方 toggle_key：\r\n"
             "# 支持示例: ` (默认波浪键), HOME, END, PGUP, PGDN, F1-F6, F11, F12, TAB, [, ], A-Z, 或十六进制虚拟键码如 0xC0\r\n"
             "toggle_key=%s\r\n",
             keyName);
    HANDLE f = CreateFileW(iniPath, GENERIC_WRITE, FILE_SHARE_READ, nullptr, CREATE_ALWAYS, 0, nullptr);
    if (f != INVALID_HANDLE_VALUE) {
        DWORD wr = 0;
        WriteFile(f, content, (DWORD)std::strlen(content), &wr, nullptr);
        CloseHandle(f);
    }
}

bool ContainsAsciiCI(const char* haystack, const char* needle);

void LoadPanelHotkeyConfig() {
    UINT vk = VK_OEM_3; // Default: ` (~ key)
    wchar_t envBuf[64] = {};
    if (GetEnvironmentVariableW(L"TEW1_DYN_PANEL_KEY", envBuf, 64) > 0) {
        char aBuf[64] = {};
        WideCharToMultiByte(CP_ACP, 0, envBuf, -1, aBuf, sizeof(aBuf), nullptr, nullptr);
        vk = ParseVkFromStrA(aBuf);
        g_panelToggleVK.store(vk);
        return;
    }
    if (!g_dllDir[0]) {
        g_panelToggleVK.store(vk);
        return;
    }
    wchar_t iniPath[MAX_PATH] = {};
    swprintf_s(iniPath, L"%stew1_dyn_hotkey.ini", g_dllDir);
    HANDLE f = CreateFileW(iniPath, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_EXISTING, 0, nullptr);
    if (f == INVALID_HANDLE_VALUE) {
        g_panelToggleVK.store(vk);
        SavePanelHotkeyConfig(vk);
        return;
    }
    char data[2048] = {};
    DWORD rd = 0;
    if (ReadFile(f, data, sizeof(data) - 1, &rd, nullptr) && rd > 0) {
        data[rd] = '\0';
        const char* p = data;
        while (*p) {
            const char* eol = strchr(p, '\n');
            size_t len = eol ? (size_t)(eol - p) : std::strlen(p);
            char line[256] = {};
            if (len < sizeof(line)) {
                memcpy(line, p, len);
                line[len] = '\0';
                const char* eq = strchr(line, '=');
                if (eq && line[0] != '#' && line[0] != ';') {
                    if (ContainsAsciiCI(line, "toggle_key")) {
                        vk = ParseVkFromStrA(eq + 1);
                        break;
                    }
                }
            }
            if (!eol) break;
            p = eol + 1;
        }
    }
    CloseHandle(f);
    g_panelToggleVK.store(vk);
}

ID3D11VertexShader*       g_uiVS = nullptr;
ID3D11PixelShader*        g_uiPS = nullptr;
ID3D11BlendState*         g_uiBlend = nullptr;
ID3D11SamplerState*       g_uiSampler = nullptr;
ID3D11RasterizerState*    g_uiRS = nullptr;
ID3D11DepthStencilState*  g_uiDSS = nullptr;
ID3D11Texture2D*          g_uiTex = nullptr;
ID3D11ShaderResourceView* g_uiSRV = nullptr;
int                       g_uiTexW = 0;
int                       g_uiTexH = 0;
constexpr int             kOverlayX = 36;
constexpr int             kOverlayY = 36;
constexpr int             kOverlayW = 460;
constexpr int             kOverlayHeaderH = 62;
constexpr int             kOverlayRowH = 36;
constexpr int             kOverlayFooterH = 42;

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
    if (!r.Read(version) || (version < 1 || version > 3)) return false;
    if (!r.Read(nSkel) || !r.Read(nChains) || !r.Read(nCols) || !r.Read(nHairFps) || !r.Read(nFaces) || !r.Read(nMorphs))
        return false;
    if (nMorphs != kNumMorphs || nCols > 16 || nChains > 48) return false;

    RuntimePack pack;
    pack.version = version;
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
        fp.vert0Remap = pad3[0];
        fp.useVert0Remap = (pad3[1] == 1 || pad3[1] == 2) ? pad3[1] : 0;
        fp.vertLastRemap = pad3[2];
    }

    uint32_t nHairVerts = 0;
    if (!r.Read(nHairVerts) || nHairVerts > 262144) return false;
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

    if (version >= 3 && r.ptr + nChains + nHairFps * 5 <= r.end) {
        // Section 7 (v3): Per-chain anchorSlot + Per-hairFP matchAnyBone & weightOffset
        for (uint32_t i = 0; i < nChains; i++) {
            uint8_t slot = 0;
            if (!r.Read(slot)) break;
            pack.chains[i].anchorSlot = slot;
        }
        for (uint32_t i = 0; i < nHairFps; i++) {
            uint8_t anyB = 0;
            uint32_t wOff = 0;
            if (!r.Read(anyB) || !r.Read(wOff)) break;
            pack.hairFps[i].matchAnyBone = anyB;
            pack.hairFps[i].weightOffset = wOff;
        }
        // Section 8 (v3): Clothing Variant Groups for Insert in-game panel
        if (r.ptr + 4 <= r.end) {
            uint32_t nVar = 0;
            if (r.Read(nVar) && nVar <= kMaxVariants) {
                pack.variants.resize(nVar);
                for (uint32_t vi = 0; vi < nVar; vi++) {
                    char utf8[48] = {};
                    uint8_t defHid = 0, p3[3] = {};
                    uint32_t nFps = 0;
                    if (!r.ReadBytes(utf8, 48) || !r.Read(defHid) || !r.ReadBytes(p3, 3) || !r.Read(nFps) || nFps > 256) {
                        pack.variants.clear();
                        break;
                    }
                    utf8[47] = '\0';
                    MultiByteToWideChar(CP_UTF8, 0, utf8, -1, pack.variants[vi].label, 48);
                    pack.variants[vi].hidden = (defHid != 0);
                    pack.variants[vi].fps.resize(nFps);
                    for (uint32_t k = 0; k < nFps; k++) {
                        if (!r.Read(pack.variants[vi].fps[k].vertCount) || !r.ReadBytes(pack.variants[vi].fps[k].first3Pos, 36)) {
                            pack.variants.clear();
                            break;
                        }
                    }
                    if (pack.variants.empty()) break;
                }
            }
        }
    }

    pack.loaded = true;
    g_pack = std::move(pack);
    for (size_t vi = 0; vi < kMaxVariants; vi++) {
        g_variantHidden[vi].store(vi < g_pack.variants.size() ? g_pack.variants[vi].hidden : false);
    }
    g_overlayDirty.store(true);
    LogFmt("Loaded tew1_dyn pack v%u: skels=%u chains=%u bones=%u cols=%u hairFps=%u faceSurfs=%u extraCharVBs=%u variants=%zu\n",
           version, nSkel, nChains, g_pack.totalHairBones, nCols, nHairFps, nFaces,
           (uint32_t)g_pack.extraCharFps.size(), g_pack.variants.size());
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

        Mat34 anchorWorld = headWorld;
        Mat34 anchorWorldInv = headWorldInv;
        if (ch.anchorSlot >= 1 && ch.anchorSlot <= kNumColliders) {
            Mat34 aSkin{};
            if (readBoneSkin(skel.colRemap[ch.anchorSlot - 1], aSkin)) {
                anchorWorld = MulMat(modelMat, aSkin);
                anchorWorldInv = InvertRigid(anchorWorld);
            }
        }

        std::vector<Vec3> restBind(nNodes);
        std::vector<Vec3> targetW(nNodes);
        for (size_t i = 0; i < nNodes; i++) {
            restBind[i] = MulPoint(skel.headAlign, ch.restNodes[i]);
            targetW[i] = MulPoint(anchorWorld, restBind[i]);
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
                if (ch.anchorSlot == 0) {
                    // Hair chains collide against the 5 humanoid body/head capsules
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
                } else {
                    // Chest / soft-body chains: NEVER push out of torso capsule!
                    // Clamp displacement smoothly around rest target within ch.radius so bounce stays natural & never explodes.
                    const float maxDisp = std::max(0.15f, ch.radius);
                    for (size_t i = 1; i < nNodes; i++) {
                        Vec3 disp = cs.pos[i] - stepAnchor[i];
                        float dl = Len(disp);
                        if (dl > maxDisp) {
                            cs.pos[i] = stepAnchor[i] + disp * (maxDisp / dl);
                        }
                    }
                }
            }
        }

        cs.anchor = targetW;

        std::vector<Vec3> solvedBind(nNodes);
        for (size_t i = 0; i < nNodes; i++) {
            solvedBind[i] = MulPoint(anchorWorldInv, cs.pos[i]);
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
    st.boneXformsValid = (boneCursor == g_pack.totalHairBones);
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

void PollHotkeys(IDXGISwapChain* sc) {
    static bool prevF7 = false, prevF8 = false, prevF9 = false, prevF10 = false;
    static bool prevIns = false, prevUp = false, prevDown = false, prevRet = false, prevLMB = false;
    static bool prevNum[10] = {};

    bool f7  = (GetAsyncKeyState(VK_F7)     & 0x8000) != 0;
    bool f8  = (GetAsyncKeyState(VK_F8)     & 0x8000) != 0;
    bool f9  = (GetAsyncKeyState(VK_F9)     & 0x8000) != 0;
    bool f10 = (GetAsyncKeyState(VK_F10)    & 0x8000) != 0;
    UINT toggleVk = g_panelToggleVK.load();
    bool tog = (GetAsyncKeyState((int)toggleVk) & 0x8000) != 0;

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

    // Live in-game hotkey rebinding mode (triggered by row [9] inside the panel!)
    if (g_rebindingKey.load()) {
        bool anyHeld = false;
        UINT pressedVk = 0;
        for (UINT vk = 0x08; vk <= 0xFE; vk++) {
            // Skip mouse buttons, Shift/Ctrl/Alt modifiers alone
            if (vk == VK_SHIFT || vk == VK_CONTROL || vk == VK_MENU ||
                vk == VK_LSHIFT || vk == VK_RSHIFT || vk == VK_LCONTROL || vk == VK_RCONTROL ||
                vk == VK_LMENU || vk == VK_RMENU || vk == VK_LWIN || vk == VK_RWIN) {
                continue;
            }
            if ((GetAsyncKeyState((int)vk) & 0x8000) != 0) {
                anyHeld = true;
                if (pressedVk == 0) pressedVk = vk;
            }
        }
        bool lmbNow = (GetAsyncKeyState(VK_LBUTTON) & 0x8000) != 0;
        if (g_rebindWaitRelease.load()) {
            if (!anyHeld && !lmbNow) {
                g_rebindWaitRelease.store(false);
            }
        } else if (pressedVk != 0) {
            if (pressedVk == VK_ESCAPE) {
                g_rebindingKey.store(false);
                g_overlayDirty.store(true);
                LogFmt("Panel Hotkey Rebind: cancelled by ESC\n");
            } else {
                g_panelToggleVK.store(pressedVk);
                SavePanelHotkeyConfig(pressedVk);
                g_rebindingKey.store(false);
                g_overlayDirty.store(true);
                char kn[32] = {};
                GetVkConfigNameA(pressedVk, kn, sizeof(kn));
                LogFmt("Panel Hotkey Rebound -> %s (VK=0x%02X), saved to tew1_dyn_hotkey.ini\n", kn, pressedVk);
            }
            prevIns = true; // Debounce newly bound key so it doesn't immediately close the panel
        }
        prevF7 = f7; prevF8 = f8; prevF9 = f9; prevF10 = f10;
        prevUp = prevDown = prevRet = prevLMB = true;
        for (int k = 0; k <= 9; k++) prevNum[k] = true;
        return;
    }

    if (tog && !prevIns) {
        bool next = !g_overlayOpen.load();
        g_overlayOpen.store(next);
        g_overlayDirty.store(true);
        char kn[32] = {};
        GetVkConfigNameA(toggleVk, kn, sizeof(kn));
        LogFmt("Hotkey [%s]: Variant Panel = %s (variants=%zu)\n", kn, next ? "OPEN" : "CLOSED", g_pack.variants.size());
        prevF7 = f7; prevF8 = f8; prevF9 = f9; prevF10 = f10; prevIns = tog;
        return;
    }

    if (g_overlayOpen.load() && !g_pack.variants.empty()) {
        const int nVar = static_cast<int>(g_pack.variants.size());
        const bool hasSheerRow = HasAnySheerVariant();
        const int sheerRowIdx = hasSheerRow ? nVar : -1;
        const int hotkeyRowIdx = nVar + (hasSheerRow ? 1 : 0);
        const int totalRows = hotkeyRowIdx + 1;
        bool up   = (GetAsyncKeyState(VK_UP)     & 0x8000) != 0;
        bool down = (GetAsyncKeyState(VK_DOWN)   & 0x8000) != 0;
        bool ret  = ((GetAsyncKeyState(VK_RETURN) & 0x8000) != 0) || ((GetAsyncKeyState(VK_SPACE) & 0x8000) != 0);
        bool lmb  = (GetAsyncKeyState(VK_LBUTTON) & 0x8000) != 0;

        auto toggleRow = [&](int idx) {
            if (idx >= 0 && idx < nVar) {
                g_variantHidden[idx].store(!g_variantHidden[idx].load());
                g_overlayDirty.store(true);
            } else if (hasSheerRow && idx == sheerRowIdx) {
                int nextSheer = (g_sheerClothMode.load() + 1) % 4;
                g_sheerClothMode.store(nextSheer);
                g_emissiveDirty.store(true);
                g_overlayDirty.store(true);
                static const char* kModeNames[4] = {"0=SolidOpaque(100%)", "1=HighSheer(22-45%)", "2=MidSheer(42-62%)", "3=SoftSheer(62-78%)"};
                LogFmt("Panel: Outerwear Sheer Mode = %s\n", kModeNames[nextSheer]);
            } else if (idx == hotkeyRowIdx) {
                g_rebindingKey.store(true);
                g_rebindWaitRelease.store(true);
                g_overlayDirty.store(true);
                LogFmt("Panel: Waiting for new custom toggle hotkey (press ESC to cancel)...\n");
            }
        };

        if (up && !prevUp) {
            int c = (g_overlayCursor.load() - 1 + totalRows) % totalRows;
            g_overlayCursor.store(c);
            g_overlayDirty.store(true);
        }
        if (down && !prevDown) {
            int c = (g_overlayCursor.load() + 1) % totalRows;
            g_overlayCursor.store(c);
            g_overlayDirty.store(true);
        }
        if (ret && !prevRet) {
            toggleRow(g_overlayCursor.load());
        }
        for (int k = 0; k <= 9; k++) {
            bool pressed = ((GetAsyncKeyState('0' + k) & 0x8000) != 0) ||
                           ((GetAsyncKeyState(VK_NUMPAD0 + k) & 0x8000) != 0);
            if (pressed && !prevNum[k]) {
                if (k == 0) {
                    bool anyVisible = false;
                    for (int vi = 0; vi < nVar; vi++) {
                        if (!g_variantHidden[vi].load()) { anyVisible = true; break; }
                    }
                    for (int vi = 0; vi < nVar; vi++) g_variantHidden[vi].store(anyVisible);
                    g_overlayDirty.store(true);
                } else if (k - 1 < totalRows) {
                    int idx = k - 1;
                    g_overlayCursor.store(idx);
                    toggleRow(idx);
                }
            }
            prevNum[k] = pressed;
        }
        if (lmb && !prevLMB && sc) {
            DXGI_SWAP_CHAIN_DESC sd{};
            if (SUCCEEDED(sc->GetDesc(&sd)) && sd.OutputWindow) {
                POINT pt{};
                if (GetCursorPos(&pt) && ScreenToClient(sd.OutputWindow, &pt)) {
                    if (pt.x >= kOverlayX && pt.x <= kOverlayX + kOverlayW) {
                        int relY = pt.y - (kOverlayY + kOverlayHeaderH);
                        if (relY >= 0 && relY < totalRows * kOverlayRowH) {
                            int idx = relY / kOverlayRowH;
                            g_overlayCursor.store(idx);
                            toggleRow(idx);
                        } else if (relY >= totalRows * kOverlayRowH && relY < totalRows * kOverlayRowH + kOverlayFooterH) {
                            bool anyVisible = false;
                            for (int vi = 0; vi < nVar; vi++) {
                                if (!g_variantHidden[vi].load()) { anyVisible = true; break; }
                            }
                            for (int vi = 0; vi < nVar; vi++) g_variantHidden[vi].store(anyVisible);
                            g_overlayDirty.store(true);
                        }
                    }
                }
            }
        }
        prevUp = up; prevDown = down; prevRet = ret; prevLMB = lmb;
    } else {
        prevUp = prevDown = prevRet = prevLMB = false;
        for (int k = 0; k <= 9; k++) prevNum[k] = false;
    }

    prevF7 = f7; prevF8 = f8; prevF9 = f9; prevF10 = f10; prevIns = tog;
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
    if (!g_enableHair.load() || !st.boneXformsValid || st.boneXforms.size() < g_pack.totalHairBones)
        return;
    if ((size_t)tvb.weightOffset + vc > g_pack.hairWeights.size())
        return;

    const uint8_t* src = tvb.neutralVerts.data();
    uint8_t* dst = tvb.workVerts.data();
    const HairSkinVert* weights = g_pack.hairWeights.data() + tvb.weightOffset;
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

// True Blender-style Semi-Transparent / Solid-Opaque Cloth Pixel Shader
// Supports 4 levels in Insert panel: 0=SolidOpaque (100% solid, ignores BC3 alpha), 1=SoftSheer, 2=MidSheer, 3=OriginalBlenderSheer
static const char* kSheerPSHlsl = R"HLSL(
cbuffer constantBufferP : register(b0) {
    float4 renderpositiontoviewtexture;
};
cbuffer SheerParams : register(b4) {
    float4 u_sheer; // x=emissiveFloor, y=sceneWeight, z=hemiMin, w=rolloff
    float4 u_alpha; // x=alphaScale, y=alphaBias, z=forceOpaque(0 or 1), w=fresnelBoost
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
    float opacity = saturate(albedo.a);
    float3 linAlbedo = albedo.rgb * albedo.rgb;

    float3 bumpN = texBump.Sample(sampBump, uv).xyz * 2.0 - 1.0;
    float3 N;
    N.x = dot(bumpN, input.htexcoord1.xyz);
    N.y = dot(bumpN, input.htexcoord2.xyz);
    N.z = dot(bumpN, input.htexcoord3.xyz);
    float nLen = length(N);
    N = (nLen > 1e-4) ? (N / nLen) : float3(0.0, 0.0, 1.0);
    if (!input.facing) N = -N;
    float3 V = normalize(-input.htexcoord4.xyz);

    float2 screenUV = input.position.xy * renderpositiontoviewtexture.zw + renderpositiontoviewtexture.xy;
    float3 sceneLight = max(texLightBuf.SampleLevel(sampLightBuf, screenUV, 0).rgb, float3(0.0, 0.0, 0.0));

    float hemi = lerp(u_sheer.z, 1.0, N.z * 0.5 + 0.5);
    float ndv = saturate(abs(dot(N, V)));
    float fresnel = pow(1.0 - ndv, 2.5);
    float softRim = fresnel * (0.14 * u_sheer.x + 0.05);

    float3 selfLit = (u_sheer.x * hemi + softRim).xxx;
    float3 combined = selfLit + sceneLight * u_sheer.y;
    combined = combined / (1.0 + combined * u_sheer.w) * (1.0 + u_sheer.w);

    float3 outRgb = linAlbedo * combined;
    if (u_alpha.z > 0.5) {
        return float4(outRgb, 1.0);
    }
    // Separate opaque cyan heart prints (opacity >= 0.92) from sheer white pajama fabric (opacity < 0.90)
    // so all 3 sheer tiers show unmistakable visual transparency on white fabric while keeping hearts crisp & solid!
    float heartMask = smoothstep(0.90, 0.98, opacity);
    float sheerBase = saturate(opacity * u_alpha.x + u_alpha.y);
    float sheerAlpha = saturate(sheerBase + fresnel * u_alpha.w * (1.0 - sheerBase));
    float finalAlpha = lerp(sheerAlpha, 1.0, heartMask);
    return float4(outRgb, finalAlpha);
}
)HLSL";

struct EmissiveCBData {
    float emissiveFloor;
    float sceneWeight;
    float hemiMin;
    float rolloff;
};

struct SheerCBData {
    float emissiveFloor;
    float sceneWeight;
    float hemiMin;
    float rolloff;
    float alphaScale;
    float alphaBias;
    float forceOpaque;
    float fresnelBoost;
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

    // Compile Sheer Semi-Transparent / Solid-Opaque Cloth PS + 32-byte CB + BlendStates
    ID3DBlob* sCode = nullptr;
    ID3DBlob* sErrs = nullptr;
    hr = fnCompile(kSheerPSHlsl, std::strlen(kSheerPSHlsl), "tew1_sheer_cloth.hlsl",
                   nullptr, nullptr, "main", "ps_5_0", D3DCOMPILE_OPTIMIZATION_LEVEL3, 0, &sCode, &sErrs);
    if (SUCCEEDED(hr) && sCode) {
        rawCreatePS(dev, sCode->GetBufferPointer(), sCode->GetBufferSize(), nullptr, &g_sheerPS);
        sCode->Release();
        D3D11_BUFFER_DESC sbdBuf{};
        sbdBuf.ByteWidth = sizeof(SheerCBData);
        sbdBuf.Usage = D3D11_USAGE_DEFAULT;
        sbdBuf.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
        SheerCBData sheerInit{0.16f, 1.05f, 0.82f, 0.18f, 0.55f, 0.20f, 0.0f, 0.06f};
        D3D11_SUBRESOURCE_DATA ssrd{&sheerInit, 0, 0};
        rawCreateBuf(dev, &sbdBuf, &ssrd, &g_sheerCB);

        D3D11_BLEND_DESC sbd{};
        sbd.AlphaToCoverageEnable = FALSE;
        sbd.IndependentBlendEnable = FALSE;
        sbd.RenderTarget[0].BlendEnable = TRUE;
        sbd.RenderTarget[0].SrcBlend = D3D11_BLEND_SRC_ALPHA;
        sbd.RenderTarget[0].DestBlend = D3D11_BLEND_INV_SRC_ALPHA;
        sbd.RenderTarget[0].BlendOp = D3D11_BLEND_OP_ADD;
        sbd.RenderTarget[0].SrcBlendAlpha = D3D11_BLEND_ZERO;
        sbd.RenderTarget[0].DestBlendAlpha = D3D11_BLEND_ONE;
        sbd.RenderTarget[0].BlendOpAlpha = D3D11_BLEND_OP_ADD;
        sbd.RenderTarget[0].RenderTargetWriteMask = D3D11_COLOR_WRITE_ENABLE_ALL;
        dev->CreateBlendState(&sbd, &g_sheerBlend);

        D3D11_BLEND_DESC obd{};
        obd.AlphaToCoverageEnable = FALSE;
        obd.IndependentBlendEnable = FALSE;
        obd.RenderTarget[0].BlendEnable = FALSE;
        obd.RenderTarget[0].RenderTargetWriteMask = D3D11_COLOR_WRITE_ENABLE_ALL;
        dev->CreateBlendState(&obd, &g_opaqueBlend);

        LogFmt("Sheer/Opaque Cloth PS & BlendStates ready (ps=%p, cb=%p, sheerBlend=%p, opaqueBlend=%p).\n",
               g_sheerPS, g_sheerCB, g_sheerBlend, g_opaqueBlend);
    } else if (sErrs) {
        LogFmt("Sheer PS compile error: %s\n", static_cast<const char*>(sErrs->GetBufferPointer()));
        sErrs->Release();
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

inline void PinTrackedVBLocked(ID3D11Buffer* vb) {
    if (!vb) return;
    uint64_t fc = g_frameCount.load(std::memory_order_relaxed);
    auto it = g_pinnedVBs.find(vb);
    if (it == g_pinnedVBs.end()) {
        vb->AddRef();
        g_pinnedVBs[vb] = fc;
    } else {
        it->second = fc;
    }
}

void GarbageCollectUnloadedVBs(uint64_t fc) {
    if ((fc % 120) != 0) return;
    std::vector<ID3D11Buffer*> toRelease;
    size_t remaining = 0;
    {
        std::lock_guard<std::mutex> lk(g_mtx);
        for (auto it = g_pinnedVBs.begin(); it != g_pinnedVBs.end(); ) {
            ID3D11Buffer* vb = it->first;
            uint64_t lastSeen = it->second;
            if (fc > lastSeen + 180) {
                vb->AddRef();
                ULONG rc = vb->Release();
                if (rc <= 1) {
                    // Only our pin remains -> TEW1 already unloaded this chapter/checkpoint VB!
                    g_vbs.erase(vb);
                    g_charVBs.erase(vb);
                    g_vbVariantGroup.erase(vb);
                    g_loggedSheerVBs.erase(vb);
                    auto vit = g_variantVBs.find(vb);
                    if (vit != g_variantVBs.end()) {
                        if (vit->second.sheerVB) {
                            g_loggedSheerVBs.erase(vit->second.sheerVB);
                            toRelease.push_back(vit->second.sheerVB);
                        }
                        g_variantVBs.erase(vit);
                    }
                    toRelease.push_back(vb);
                    it = g_pinnedVBs.erase(it);
                    continue;
                }
            }
            ++it;
        }
        remaining = g_pinnedVBs.size();
    }
    for (ID3D11Buffer* b : toRelease) {
        b->Release();
    }
    if (!toRelease.empty()) {
        LogFmt("GC cleanly released %zu unloaded chapter GPU buffers (remaining pinned VBs=%zu)\n",
               toRelease.size(), remaining);
    }
}

HRESULT STDMETHODCALLTYPE HookCreateBuffer(ID3D11Device* dev, const D3D11_BUFFER_DESC* desc,
                                           const D3D11_SUBRESOURCE_DATA* init, ID3D11Buffer** outBuf) {
    HRESULT hr = origCreateBuffer(dev, desc, init, outBuf);
    if (FAILED(hr) || !desc || !outBuf || !*outBuf) return hr;

    {
        std::lock_guard<std::mutex> lk(g_mtx);
        g_vbs.erase(*outBuf);
        g_charVBs.erase(*outBuf);
        g_vbVariantGroup.erase(*outBuf);
        auto oldVit = g_variantVBs.find(*outBuf);
        if (oldVit != g_variantVBs.end()) {
            if (oldVit->second.sheerVB) oldVit->second.sheerVB->Release();
            g_variantVBs.erase(oldVit);
        }
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
        const uint8_t lastRemap = raw[(size_t)(vc - 1) * 32 + 28];

        // Tag clothing variant group if matched & cache neutral + NaN-discard VBs (+ twin sheerVB for sheer cloth!)
        // (NaN vertex positions discard primitives cleanly in Depth-Prepass, Shadows, Velocity, Forward, AND all Deferred Contexts!)
        for (size_t vi = 0; vi < g_pack.variants.size(); vi++) {
            for (const auto& vfp : g_pack.variants[vi].fps) {
                if (vfp.vertCount == vc && MatchFirst3Pos(raw, vfp.first3Pos)) {
                    bool sheerCapable = IsSheerVariantLabel(g_pack.variants[vi].label);
                    ID3D11Buffer* twinSheerVB = nullptr;
                    if (sheerCapable) {
                        D3D11_BUFFER_DESC sdesc = *desc;
                        sdesc.Usage = D3D11_USAGE_DEFAULT;
                        sdesc.CPUAccessFlags = 0;
                        origCreateBuffer(dev, &sdesc, init, &twinSheerVB);
                    }
                    std::lock_guard<std::mutex> lk(g_mtx);
                    g_vbVariantGroup[*outBuf] = static_cast<int>(vi);
                    VariantVBState vst;
                    vst.groupIdx = static_cast<int>(vi);
                    vst.isSheerCloth = sheerCapable;
                    vst.sheerVB = twinSheerVB;
                    vst.neutralVerts.assign(raw, raw + desc->ByteWidth);
                    vst.hiddenVerts = vst.neutralVerts;
                    const uint32_t qnan = 0x7FC00000u;
                    for (uint32_t k = 0; k < vc; k++) {
                        uint8_t* hv = vst.hiddenVerts.data() + (size_t)k * 32;
                        memcpy(hv + 0, &qnan, 4);
                        memcpy(hv + 4, &qnan, 4);
                        memcpy(hv + 8, &qnan, 4);
                    }
                    g_variantVBs[*outBuf] = std::move(vst);
                    PinTrackedVBLocked(*outBuf);
                    if (sheerCapable) {
                        g_loggedSheerVBs.erase(twinSheerVB);
                        g_emissiveDirty.store(true);
                    }
                    LogFmt("Tagged Variant[%zu] VB %p (verts=%u, sheer=%d, sheerVB=%p)\n",
                           vi, *outBuf, vc, sheerCapable ? 1 : 0, twinSheerVB);
                    break;
                }
            }
        }

        for (const auto& fp : g_pack.hairFps) {
            bool boneOk = false;
            if (fp.useVert0Remap == 2) {
                boneOk = (fp.vert0Remap == headRemap && fp.vertLastRemap == lastRemap);
            } else if (fp.useVert0Remap == 1) {
                boneOk = (fp.vert0Remap == headRemap);
            } else {
                boneOk = (fp.matchAnyBone || fp.headRemap == headRemap);
            }
            if (fp.vertCount == vc && boneOk && MatchFirst3Pos(raw, fp.first3Pos)) {
                std::lock_guard<std::mutex> lk(g_mtx);
                TrackedSurfaceVB tvb;
                tvb.isHair = true;
                tvb.headRemap = fp.headRemap;
                tvb.vertCount = vc;
                tvb.weightOffset = fp.weightOffset;
                tvb.neutralVerts.assign(raw, raw + desc->ByteWidth);
                tvb.workVerts = tvb.neutralVerts;
                g_vbs[*outBuf] = std::move(tvb);
                g_charVBs.insert(*outBuf);
                PinTrackedVBLocked(*outBuf);
                LogFmt("Hooked Dynamic PHYSICS VB %p (verts=%u, headRemap=%u, v0=%u, wOff=%u)\n",
                       *outBuf, vc, fp.headRemap, headRemap, fp.weightOffset);
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
                PinTrackedVBLocked(*outBuf);
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
    if (!g_immCtx) return;
    if (!g_emissiveDirty.exchange(false)) return;

    int mode = g_emissiveMode.load();
    int sheerMode = g_sheerClothMode.load();
    EmissiveCBData cb{};
    SheerCBData sheerCb{};
    if (mode == 1) {
        // F7 Soft Emissive: keeps dramatic lighting while lifting dark shadows clearly
        cb = {0.28f, 0.85f, 0.84f, 0.22f};
        sheerCb.emissiveFloor = 0.30f; sheerCb.sceneWeight = 0.85f; sheerCb.hemiMin = 0.84f; sheerCb.rolloff = 0.22f;
    } else if (mode == 2) {
        // F8 Bright Anime Emissive: vivid luminous character look in any room
        cb = {0.62f, 0.55f, 0.88f, 0.28f};
        sheerCb.emissiveFloor = 0.62f; sheerCb.sceneWeight = 0.55f; sheerCb.hemiMin = 0.88f; sheerCb.rolloff = 0.28f;
    } else if (mode == 3) {
        // F9 Full Unlit Glow: showcase-grade maximum self-illumination
        cb = {1.05f, 0.22f, 0.92f, 0.30f};
        sheerCb.emissiveFloor = 1.05f; sheerCb.sceneWeight = 0.22f; sheerCb.hemiMin = 0.92f; sheerCb.rolloff = 0.30f;
    } else {
        // mode == 0: balanced vanilla lighting floor for luminous yet clear sheer fabric
        cb = {0.28f, 0.85f, 0.84f, 0.22f};
        sheerCb.emissiveFloor = 0.16f; sheerCb.sceneWeight = 1.05f; sheerCb.hemiMin = 0.82f; sheerCb.rolloff = 0.18f;
    }

    if (sheerMode == 0) {
        // 0 = 100% Solid Opaque (ignores BC3 alpha completely!)
        sheerCb.alphaScale = 0.0f; sheerCb.alphaBias = 1.0f; sheerCb.forceOpaque = 1.0f; sheerCb.fresnelBoost = 0.0f;
    } else if (sheerMode == 1) {
        // 1 = High Sheer (ultra-clear chiffon: white fabric ~0.22..0.46, hearts 1.00)
        sheerCb.alphaScale = 0.50f; sheerCb.alphaBias = 0.04f; sheerCb.forceOpaque = 0.0f; sheerCb.fresnelBoost = 0.05f;
    } else if (sheerMode == 2) {
        // 2 = Medium Sheer (DEFAULT sweet spot: white fabric ~0.42..0.62, hearts 1.00)
        sheerCb.alphaScale = 0.55f; sheerCb.alphaBias = 0.20f; sheerCb.forceOpaque = 0.0f; sheerCb.fresnelBoost = 0.06f;
    } else {
        // 3 = Soft Rich Sheer (+20% fuller veil: white fabric ~0.60..0.78, hearts 1.00)
        sheerCb.alphaScale = 0.50f; sheerCb.alphaBias = 0.40f; sheerCb.forceOpaque = 0.0f; sheerCb.fresnelBoost = 0.07f;
    }

    auto orig = GetCtxOrig(g_immCtx);
    if (orig.updateSub) {
        t_inInternalUpdate = true;
        if (g_emissiveCB) orig.updateSub(g_immCtx, g_emissiveCB, 0, nullptr, &cb, 0, 0);
        if (g_sheerCB)    orig.updateSub(g_immCtx, g_sheerCB, 0, nullptr, &sheerCb, 0, 0);
        t_inInternalUpdate = false;
    }
}

void UpdateAllAtFrameBoundary(IDXGISwapChain* sc) {
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

    PollHotkeys(sc);
    UpdateEmissiveCBIfNeeded();

    LARGE_INTEGER now{};
    QueryPerformanceCounter(&now);

    auto orig = GetCtxOrig(g_immCtx);
    if (!orig.updateSub) return;

    {
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

    const bool sheerActive = (g_sheerClothMode.load() > 0) && g_sheerPS && g_sheerCB && g_sheerBlend;

    for (auto& kv : g_vbs) {
        ID3D11Buffer* vbPtr = kv.first;
        TrackedSurfaceVB& tvb = kv.second;
        if (!tvb.seenThisFrame) continue;
        tvb.seenThisFrame = false;
        auto pit = g_pinnedVBs.find(vbPtr);
        if (pit != g_pinnedVBs.end()) pit->second = fc;

        // Route physics uploads cleanly when this VB is also a clothing variant (e.g. chest physics on sheer pajama!):
        // - If user hid this clothing variant: skip upload so origVB stays NaN-hidden!
        // - If Sheer Cloth Mode is ON for this variant: upload live physics into sheerVB (keeping origVB NaN-hidden from Depth-Prepass!)
        ID3D11Buffer* uploadTarget = vbPtr;
        auto vit = g_variantVBs.find(vbPtr);
        if (vit != g_variantVBs.end()) {
            int gi = vit->second.groupIdx;
            if (gi >= 0 && gi < (int)kMaxVariants && g_variantHidden[gi].load()) {
                continue;
            }
            if (sheerActive && vit->second.isSheerCloth && vit->second.sheerVB) {
                uploadTarget = vit->second.sheerVB;
            }
        }

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
        orig.updateSub(g_immCtx, uploadTarget, 0, nullptr, tvb.workVerts.data(), 0, 0);
        t_inInternalUpdate = false;
    }

    // Apply NaN-discard hide / neutral restore for ALL live clothing variant VBs
    // - Hidden variant -> origVB has NaN (invisible in Depth-Prepass, Shadows, Velocity, Forward, & Deferred Contexts!)
    // - Visible sheer cloth (sheerActive=true) -> origVB has NaN (ZERO depth-prepass occlusion of body/nipples/innerwear!),
    //   while sheerVB renders in Forward Pass with true Blender SRC_ALPHA transparency!
    // - Visible opaque cloth (sheerActive=false) -> origVB has neutralVerts (or live physics verts above!)
    for (auto& kv : g_variantVBs) {
        ID3D11Buffer* vbPtr = kv.first;
        VariantVBState& vst = kv.second;
        if (!vst.seenThisFrame) continue;
        vst.seenThisFrame = false;
        auto pit = g_pinnedVBs.find(vbPtr);
        if (pit != g_pinnedVBs.end()) pit->second = fc;
        if (vst.groupIdx < 0 || vst.groupIdx >= (int)kMaxVariants) continue;
        bool wantHidden = g_variantHidden[vst.groupIdx].load();
        bool wantSheer = (!wantHidden && sheerActive && vst.isSheerCloth && vst.sheerVB != nullptr);
        bool wantOrigNaN = wantHidden || wantSheer;
        if (wantOrigNaN != vst.origHasNaN) {
            const uint8_t* srcBuf = wantOrigNaN ? vst.hiddenVerts.data() : vst.neutralVerts.data();
            t_inInternalUpdate = true;
            orig.updateSub(g_immCtx, vbPtr, 0, nullptr, srcBuf, 0, 0);
            t_inInternalUpdate = false;
            vst.origHasNaN = wantOrigNaN;
            LogFmt("Variant[%d] VB %p -> %s\n", vst.groupIdx, vbPtr,
                   wantHidden ? "HIDDEN (NaN)" : (wantSheer ? "SHEER (orig=NaN, sheerVB=LIVE)" : "OPAQUE (LIVE)"));
        }
    }
    } // unlock g_mtx before GC COM Release
    GarbageCollectUnloadedVBs(fc);
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

const char* kOverlayVSHlsl = R"(
struct VSOut {
    float4 pos : SV_POSITION;
    float2 uv  : TEXCOORD0;
};
VSOut main(uint id : SV_VertexID) {
    VSOut o;
    float2 uvs[4] = { float2(0,0), float2(1,0), float2(0,1), float2(1,1) };
    o.uv = uvs[id];
    o.pos = float4(o.uv.x * 2.0f - 1.0f, 1.0f - o.uv.y * 2.0f, 0.0f, 1.0f);
    return o;
}
)";

const char* kOverlayPSHlsl = R"(
Texture2D<float4> texUI : register(t0);
SamplerState sampUI : register(s0);
float4 main(float4 pos : SV_POSITION, float2 uv : TEXCOORD0) : SV_TARGET {
    return texUI.Sample(sampUI, uv);
}
)";

bool EnsureOverlayResources(ID3D11Device* dev, int texW, int texH) {
    if (!dev) return false;
    if (!g_uiVS || !g_uiPS) {
        HMODULE hComp = LoadLibraryW(L"d3dcompiler_47.dll");
        if (!hComp) hComp = LoadLibraryW(L"d3dcompiler_43.dll");
        if (!hComp) return false;
        using pD3DCompile = HRESULT(WINAPI*)(LPCVOID, SIZE_T, LPCSTR, const D3D_SHADER_MACRO*, ID3DInclude*,
                                            LPCSTR, LPCSTR, UINT, UINT, ID3DBlob**, ID3DBlob**);
        auto fnCompile = reinterpret_cast<pD3DCompile>(GetProcAddress(hComp, "D3DCompile"));
        if (!fnCompile) return false;

        ID3DBlob* vsCode = nullptr;
        ID3DBlob* psCode = nullptr;
        if (FAILED(fnCompile(kOverlayVSHlsl, std::strlen(kOverlayVSHlsl), "tew1_ui_vs.hlsl",
                             nullptr, nullptr, "main", "vs_5_0", D3DCOMPILE_OPTIMIZATION_LEVEL3, 0, &vsCode, nullptr)) || !vsCode)
            return false;
        if (FAILED(fnCompile(kOverlayPSHlsl, std::strlen(kOverlayPSHlsl), "tew1_ui_ps.hlsl",
                             nullptr, nullptr, "main", "ps_5_0", D3DCOMPILE_OPTIMIZATION_LEVEL3, 0, &psCode, nullptr)) || !psCode) {
            vsCode->Release();
            return false;
        }
        dev->CreateVertexShader(vsCode->GetBufferPointer(), vsCode->GetBufferSize(), nullptr, &g_uiVS);
        if (origCreatePS) {
            origCreatePS(dev, psCode->GetBufferPointer(), psCode->GetBufferSize(), nullptr, &g_uiPS);
        } else {
            dev->CreatePixelShader(psCode->GetBufferPointer(), psCode->GetBufferSize(), nullptr, &g_uiPS);
        }
        vsCode->Release();
        psCode->Release();
        if (!g_uiVS || !g_uiPS) return false;

        D3D11_BLEND_DESC bd{};
        bd.RenderTarget[0].BlendEnable = TRUE;
        bd.RenderTarget[0].SrcBlend = D3D11_BLEND_SRC_ALPHA;
        bd.RenderTarget[0].DestBlend = D3D11_BLEND_INV_SRC_ALPHA;
        bd.RenderTarget[0].BlendOp = D3D11_BLEND_OP_ADD;
        bd.RenderTarget[0].SrcBlendAlpha = D3D11_BLEND_ONE;
        bd.RenderTarget[0].DestBlendAlpha = D3D11_BLEND_INV_SRC_ALPHA;
        bd.RenderTarget[0].BlendOpAlpha = D3D11_BLEND_OP_ADD;
        bd.RenderTarget[0].RenderTargetWriteMask = D3D11_COLOR_WRITE_ENABLE_ALL;
        dev->CreateBlendState(&bd, &g_uiBlend);

        D3D11_SAMPLER_DESC sd{};
        sd.Filter = D3D11_FILTER_MIN_MAG_MIP_LINEAR;
        sd.AddressU = sd.AddressV = sd.AddressW = D3D11_TEXTURE_ADDRESS_CLAMP;
        dev->CreateSamplerState(&sd, &g_uiSampler);

        D3D11_RASTERIZER_DESC rsd{};
        rsd.FillMode = D3D11_FILL_SOLID;
        rsd.CullMode = D3D11_CULL_NONE;
        rsd.ScissorEnable = FALSE;
        rsd.DepthClipEnable = FALSE;
        dev->CreateRasterizerState(&rsd, &g_uiRS);

        D3D11_DEPTH_STENCIL_DESC dsd{};
        dsd.DepthEnable = FALSE;
        dsd.StencilEnable = FALSE;
        dev->CreateDepthStencilState(&dsd, &g_uiDSS);
    }

    if (!g_uiTex || g_uiTexW != texW || g_uiTexH != texH) {
        if (g_uiSRV) { g_uiSRV->Release(); g_uiSRV = nullptr; }
        if (g_uiTex) { g_uiTex->Release(); g_uiTex = nullptr; }
        D3D11_TEXTURE2D_DESC td{};
        td.Width = texW;
        td.Height = texH;
        td.MipLevels = 1;
        td.ArraySize = 1;
        td.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
        td.SampleDesc.Count = 1;
        td.Usage = D3D11_USAGE_DEFAULT;
        td.BindFlags = D3D11_BIND_SHADER_RESOURCE;
        if (FAILED(dev->CreateTexture2D(&td, nullptr, &g_uiTex)) || !g_uiTex) return false;
        if (FAILED(dev->CreateShaderResourceView(g_uiTex, nullptr, &g_uiSRV)) || !g_uiSRV) return false;
        g_uiTexW = texW;
        g_uiTexH = texH;
    }
    return true;
}

void RedrawOverlayTexture(ID3D11DeviceContext* ctx) {
    const int nVar = static_cast<int>(g_pack.variants.size());
    const bool hasSheerRow = HasAnySheerVariant();
    const int hotkeyRowIdx = nVar + (hasSheerRow ? 1 : 0);
    const int totalRows = hotkeyRowIdx + 1;
    const int w = kOverlayW;
    const int h = kOverlayHeaderH + totalRows * kOverlayRowH + kOverlayFooterH;

    BITMAPINFO bmi{};
    bmi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    bmi.bmiHeader.biWidth = w;
    bmi.bmiHeader.biHeight = -h;
    bmi.bmiHeader.biPlanes = 1;
    bmi.bmiHeader.biBitCount = 32;
    bmi.bmiHeader.biCompression = BI_RGB;

    void* bits = nullptr;
    HDC memDC = CreateCompatibleDC(nullptr);
    HBITMAP dib = CreateDIBSection(memDC, &bmi, DIB_RGB_COLORS, &bits, nullptr, 0);
    if (!dib || !bits) {
        if (dib) DeleteObject(dib);
        DeleteDC(memDC);
        return;
    }
    HGDIOBJ oldBmp = SelectObject(memDC, dib);

    auto fillRect = [&](int rx, int ry, int rw, int rh, uint8_t a, uint8_t r, uint8_t g, uint8_t b) {
        int x0 = std::max(0, rx), y0 = std::max(0, ry);
        int x1 = std::min(w, rx + rw), y1 = std::min(h, ry + rh);
        uint32_t px = (uint32_t(a) << 24) | (uint32_t(r) << 16) | (uint32_t(g) << 8) | uint32_t(b);
        uint32_t* p = static_cast<uint32_t*>(bits);
        for (int yy = y0; yy < y1; yy++) {
            for (int xx = x0; xx < x1; xx++) p[yy * w + xx] = px;
        }
    };

    fillRect(0, 0, w, h, 225, 16, 19, 27);
    fillRect(0, 0, w, 4, 255, 220, 53, 69);
    fillRect(0, h - 2, w, 2, 180, 70, 82, 104);
    fillRect(0, 0, 2, h, 180, 70, 82, 104);
    fillRect(w - 2, 0, 2, h, 180, 70, 82, 104);

    HFONT fTitle = CreateFontW(22, 0, 0, 0, FW_BOLD, FALSE, FALSE, FALSE, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, L"Microsoft YaHei");
    HFONT fRow   = CreateFontW(18, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, L"Microsoft YaHei");
    HFONT fHint  = CreateFontW(15, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, L"Microsoft YaHei");
    SetBkMode(memDC, TRANSPARENT);

    auto drawText = [&](HFONT f, int tx, int ty, int tw, int th, COLORREF col, const wchar_t* str, UINT fmt) {
        SelectObject(memDC, f);
        SetTextColor(memDC, col);
        RECT rc{tx, ty, tx + tw, ty + th};
        DrawTextW(memDC, str, -1, &rc, fmt | DT_VCENTER | DT_SINGLELINE);
        uint32_t* p = static_cast<uint32_t*>(bits);
        int x0 = std::max(0, tx), y0 = std::max(0, ty);
        int x1 = std::min(w, tx + tw), y1 = std::min(h, ty + th);
        for (int yy = y0; yy < y1; yy++) {
            for (int xx = x0; xx < x1; xx++) {
                uint32_t& c = p[yy * w + xx];
                if ((c >> 24) == 0) c |= 0xFF000000u;
            }
        }
    };

    wchar_t curKeyW[24] = {};
    GetVkLabelW(g_panelToggleVK.load(), curKeyW, 24);
    wchar_t titleBuf[96] = {};
    swprintf_s(titleBuf, L"服装差分切换面板  [%ls 键关闭]", curKeyW);
    drawText(fTitle, 16, 8, w - 32, 32, RGB(248, 250, 252), titleBuf, DT_LEFT);
    drawText(fHint, 16, 38, w - 32, 20, RGB(156, 163, 175), L"按 1-9 / 方向键+回车 / 鼠标点击切换 | 0 一键全脱/全穿", DT_LEFT);
    fillRect(14, kOverlayHeaderH - 2, w - 28, 1, 120, 80, 92, 112);

    int cursor = g_overlayCursor.load();
    for (int i = 0; i < nVar; i++) {
        int ry = kOverlayHeaderH + i * kOverlayRowH;
        bool hid = g_variantHidden[i].load();
        bool sel = (i == cursor);
        if (sel) {
            fillRect(10, ry + 2, w - 20, kOverlayRowH - 4, 210, 42, 52, 74);
        }
        wchar_t line[96];
        swprintf_s(line, L"[%d]  %ls", i + 1, g_pack.variants[i].label);
        drawText(fRow, 20, ry + 2, w - 130, kOverlayRowH - 4,
                 hid ? RGB(148, 163, 184) : RGB(241, 245, 249), line, DT_LEFT);

        fillRect(w - 96, ry + 6, 76, kOverlayRowH - 12, 230,
                 hid ? 75 : 34, hid ? 85 : 150, hid ? 99 : 84);
        drawText(fHint, w - 96, ry + 6, 76, kOverlayRowH - 12,
                 RGB(255, 255, 255), hid ? L"已隐藏" : L"显示中", DT_CENTER);
    }

    if (hasSheerRow) {
        int ry = kOverlayHeaderH + nVar * kOverlayRowH;
        int sm = g_sheerClothMode.load();
        bool sel = (nVar == cursor);
        if (sel) {
            fillRect(10, ry + 2, w - 20, kOverlayRowH - 4, 210, 42, 52, 74);
        }
        fillRect(16, ry, w - 32, 1, 90, 95, 110, 134);
        wchar_t line[96];
        swprintf_s(line, L"[%d]  睡衣外套透明度（4档切换）", nVar + 1);
        drawText(fRow, 20, ry + 2, w - 130, kOverlayRowH - 4,
                 sm > 0 ? RGB(125, 211, 252) : RGB(226, 232, 240), line, DT_LEFT);

        static const wchar_t* kSheerTags[4] = {L"不透明", L"高透纱", L"中透纱", L"微透纱"};
        static const uint8_t kPillCol[4][3] = {
            {75, 85, 99},
            {139, 92, 246},
            {14, 165, 233},
            {56, 189, 248},
        };
        int si = (sm >= 0 && sm < 4) ? sm : 0;
        fillRect(w - 96, ry + 6, 76, kOverlayRowH - 12, 235,
                 kPillCol[si][0], kPillCol[si][1], kPillCol[si][2]);
        drawText(fHint, w - 96, ry + 6, 76, kOverlayRowH - 12,
                 RGB(255, 255, 255), kSheerTags[si], DT_CENTER);
    }

    {
        int ry = kOverlayHeaderH + hotkeyRowIdx * kOverlayRowH;
        bool rebinding = g_rebindingKey.load();
        bool sel = (hotkeyRowIdx == cursor);
        if (sel) {
            fillRect(10, ry + 2, w - 20, kOverlayRowH - 4, 210, 42, 52, 74);
        }
        fillRect(16, ry, w - 32, 1, 90, 95, 110, 134);
        wchar_t line[96];
        swprintf_s(line, L"[%d]  %ls", hotkeyRowIdx + 1,
                   rebinding ? L"请按下新的开关快捷键（ESC取消）" : L"自定义面板快捷键（点此改键）");
        drawText(fRow, 20, ry + 2, w - 130, kOverlayRowH - 4,
                 rebinding ? RGB(251, 191, 36) : RGB(226, 232, 240), line, DT_LEFT);

        fillRect(w - 96, ry + 6, 76, kOverlayRowH - 12, 235,
                 rebinding ? 217 : 71, rebinding ? 119 : 85, rebinding ? 6 : 105);
        drawText(fHint, w - 96, ry + 6, 76, kOverlayRowH - 12,
                 RGB(255, 255, 255), rebinding ? L"等待按键" : curKeyW, DT_CENTER);
    }

    int fy = kOverlayHeaderH + totalRows * kOverlayRowH;
    fillRect(14, fy + 2, w - 28, 1, 120, 80, 92, 112);
    drawText(fHint, 16, fy + 6, w - 32, kOverlayFooterH - 8,
             RGB(250, 204, 21), L"[0] 一键全脱 / 一键全穿   ·   [F7/F8/F9] 自发光   [F10] 表情", DT_CENTER);

    auto orig = GetCtxOrig(ctx);
    if (orig.updateSub && g_uiTex) {
        t_inInternalUpdate = true;
        orig.updateSub(ctx, g_uiTex, 0, nullptr, bits, w * 4, 0);
        t_inInternalUpdate = false;
    }

    SelectObject(memDC, oldBmp);
    DeleteObject(fTitle); DeleteObject(fRow); DeleteObject(fHint);
    DeleteObject(dib);
    DeleteDC(memDC);
}

void RenderVariantOverlay(IDXGISwapChain* sc) {
    if (!g_overlayOpen.load() || g_pack.variants.empty() || !g_device || !g_immCtx || !sc) return;
    const int nVar = static_cast<int>(g_pack.variants.size());
    const int totalRows = nVar + (HasAnySheerVariant() ? 1 : 0) + 1;
    const int texW = kOverlayW;
    const int texH = kOverlayHeaderH + totalRows * kOverlayRowH + kOverlayFooterH;

    if (!EnsureOverlayResources(g_device, texW, texH)) return;
    if (g_overlayDirty.exchange(false)) {
        RedrawOverlayTexture(g_immCtx);
    }

    ID3D11Texture2D* backBuf = nullptr;
    if (FAILED(sc->GetBuffer(0, __uuidof(ID3D11Texture2D), reinterpret_cast<void**>(&backBuf))) || !backBuf) return;
    ID3D11RenderTargetView* rtv = nullptr;
    HRESULT hr = g_device->CreateRenderTargetView(backBuf, nullptr, &rtv);
    backBuf->Release();
    if (FAILED(hr) || !rtv) return;

    ID3D11RenderTargetView* oldRTVs[4] = {};
    ID3D11DepthStencilView* oldDSV = nullptr;
    g_immCtx->OMGetRenderTargets(4, oldRTVs, &oldDSV);
    ID3D11BlendState* oldBlend = nullptr;
    FLOAT oldBF[4] = {};
    UINT oldMask = 0;
    g_immCtx->OMGetBlendState(&oldBlend, oldBF, &oldMask);
    ID3D11RasterizerState* oldRS = nullptr;
    g_immCtx->RSGetState(&oldRS);
    ID3D11DepthStencilState* oldDSS = nullptr;
    UINT oldStencilRef = 0;
    g_immCtx->OMGetDepthStencilState(&oldDSS, &oldStencilRef);
    D3D11_VIEWPORT oldVPs[16] = {};
    UINT numVPs = 16;
    g_immCtx->RSGetViewports(&numVPs, oldVPs);
    ID3D11InputLayout* oldIL = nullptr;
    D3D11_PRIMITIVE_TOPOLOGY oldTopo = D3D11_PRIMITIVE_TOPOLOGY_UNDEFINED;
    g_immCtx->IAGetInputLayout(&oldIL);
    g_immCtx->IAGetPrimitiveTopology(&oldTopo);
    ID3D11VertexShader* oldVS = nullptr;
    ID3D11PixelShader* oldPS = nullptr;
    g_immCtx->VSGetShader(&oldVS, nullptr, nullptr);
    g_immCtx->PSGetShader(&oldPS, nullptr, nullptr);

    t_inInternalDraw = true;
    auto orig = GetCtxOrig(g_immCtx);
    g_immCtx->OMSetRenderTargets(1, &rtv, nullptr);
    if (g_uiRS)  g_immCtx->RSSetState(g_uiRS);
    if (g_uiDSS) g_immCtx->OMSetDepthStencilState(g_uiDSS, 0);
    D3D11_VIEWPORT vp{float(kOverlayX), float(kOverlayY), float(texW), float(texH), 0.f, 1.f};
    g_immCtx->RSSetViewports(1, &vp);
    g_immCtx->OMSetBlendState(g_uiBlend, nullptr, 0xFFFFFFFF);
    g_immCtx->IASetInputLayout(nullptr);
    g_immCtx->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLESTRIP);
    if (orig.vsSetShader) orig.vsSetShader(g_immCtx, g_uiVS, nullptr, 0);
    if (orig.psSetShader) orig.psSetShader(g_immCtx, g_uiPS, nullptr, 0);
    if (orig.psSetSRV)    orig.psSetSRV(g_immCtx, 0, 1, &g_uiSRV);
    g_immCtx->PSSetSamplers(0, 1, &g_uiSampler);
    g_immCtx->Draw(4, 0);

    g_immCtx->OMSetRenderTargets(4, oldRTVs, oldDSV);
    g_immCtx->OMSetBlendState(oldBlend, oldBF, oldMask);
    g_immCtx->RSSetState(oldRS);
    g_immCtx->OMSetDepthStencilState(oldDSS, oldStencilRef);
    if (numVPs > 0) g_immCtx->RSSetViewports(numVPs, oldVPs);
    g_immCtx->IASetInputLayout(oldIL);
    g_immCtx->IASetPrimitiveTopology(oldTopo);
    if (orig.vsSetShader) orig.vsSetShader(g_immCtx, oldVS, nullptr, 0);
    if (orig.psSetShader) orig.psSetShader(g_immCtx, oldPS, nullptr, 0);
    t_inInternalDraw = false;
    ReassertDrawHooks(g_immCtx);

    for (auto* r : oldRTVs) if (r) r->Release();
    if (oldDSV) oldDSV->Release();
    if (oldBlend) oldBlend->Release();
    if (oldRS) oldRS->Release();
    if (oldDSS) oldDSS->Release();
    if (oldIL) oldIL->Release();
    if (oldVS) oldVS->Release();
    if (oldPS) oldPS->Release();
    rtv->Release();
}

bool IsVariantHiddenNow(const CtxBoundState& cs) {
    if (!cs.boundVB0 || g_pack.variants.empty()) return false;
    std::lock_guard<std::mutex> lk(g_mtx);
    auto it = g_vbVariantGroup.find(cs.boundVB0);
    if (it == g_vbVariantGroup.end()) return false;
    int idx = it->second;
    return (idx >= 0 && idx < static_cast<int>(kMaxVariants)) ? g_variantHidden[idx].load() : false;
}

void DetectDepthDirectionOnce(ID3D11DeviceContext* ctx) {
    if (!ctx || g_depthDirKnown.load(std::memory_order_relaxed)) return;
    ID3D11DepthStencilState* curDSS = nullptr;
    UINT curRef = 0;
    ctx->OMGetDepthStencilState(&curDSS, &curRef);
    if (!curDSS) return;
    D3D11_DEPTH_STENCIL_DESC d{};
    curDSS->GetDesc(&d);
    curDSS->Release();
    if (d.DepthEnable && d.DepthWriteMask == D3D11_DEPTH_WRITE_MASK_ALL) {
        if (d.DepthFunc == D3D11_COMPARISON_GREATER || d.DepthFunc == D3D11_COMPARISON_GREATER_EQUAL) {
            g_depthIsReverseZ.store(true);
            if (!g_depthDirKnown.exchange(true)) {
                LogFmt("Auto-detected Depth-Prepass direction: REVERSE-Z (DepthFunc=%d)\n", (int)d.DepthFunc);
            }
        } else if (d.DepthFunc == D3D11_COMPARISON_LESS || d.DepthFunc == D3D11_COMPARISON_LESS_EQUAL) {
            g_depthIsReverseZ.store(false);
            if (!g_depthDirKnown.exchange(true)) {
                LogFmt("Auto-detected Depth-Prepass direction: STANDARD-Z (DepthFunc=%d)\n", (int)d.DepthFunc);
            }
        }
    }
}

struct SheerDrawPlan {
    bool active = false;
    bool opaqueSolid = false;
    ID3D11Buffer* vbToDraw = nullptr;
};

SheerDrawPlan GetSheerDrawPlan(const CtxBoundState& cs) {
    SheerDrawPlan plan{};
    if (!cs.boundVB0 || !cs.boundPS || !g_sheerPS || !g_sheerCB || !g_sheerBlend || !g_opaqueBlend) {
        return plan;
    }
    int mode = g_sheerClothMode.load(std::memory_order_relaxed);
    std::lock_guard<std::mutex> lk(g_mtx);
    auto vit = g_variantVBs.find(cs.boundVB0);
    if (vit == g_variantVBs.end() || !vit->second.isSheerCloth) {
        return plan;
    }
    if (g_forwardAlbedoPS.find(cs.boundPS) == g_forwardAlbedoPS.end()) {
        return plan;
    }
    if (mode == 0) {
        // Solid Opaque Mode: draw origVB with BlendEnable=FALSE + forceOpaque=1.0 so BC3 alpha NEVER bleeds or darkens!
        plan.active = true;
        plan.opaqueSolid = true;
        plan.vbToDraw = cs.boundVB0;
        plan.vbToDraw->AddRef();
    } else if (vit->second.sheerVB) {
        // Sheer Mode (1=HighSheer, 2=MidSheer, 3=SoftSheer): swap to sheerVB + SRC_ALPHA blend!
        plan.active = true;
        plan.opaqueSolid = false;
        plan.vbToDraw = vit->second.sheerVB;
        plan.vbToDraw->AddRef();
    }
    return plan;
}

ID3D11DepthStencilState* GetOrCreateSheerDSS(ID3D11DepthStencilState* oldDSS) {
    if (!g_device) return nullptr;
    D3D11_DEPTH_STENCIL_DESC d{};
    if (oldDSS) {
        oldDSS->GetDesc(&d);
    } else {
        d.StencilEnable = FALSE;
    }
    int origFunc = (int)d.DepthFunc;
    d.DepthEnable = TRUE;
    d.DepthWriteMask = D3D11_DEPTH_WRITE_MASK_ZERO;
    d.DepthFunc = g_depthIsReverseZ.load() ? D3D11_COMPARISON_GREATER_EQUAL : D3D11_COMPARISON_LESS_EQUAL;

    uint64_t key = (uint64_t(d.DepthFunc) & 0xF) |
                   (uint64_t(d.StencilEnable ? 1 : 0) << 4) |
                   (uint64_t(d.StencilReadMask) << 8) |
                   (uint64_t(d.StencilWriteMask) << 16) |
                   (uint64_t(d.FrontFace.StencilFunc) << 24) |
                   (uint64_t(d.FrontFace.StencilPassOp) << 32) |
                   (uint64_t(d.BackFace.StencilFunc) << 40);
    {
        std::lock_guard<std::mutex> lk(g_mtx);
        auto it = g_sheerDSSCache.find(key);
        if (it != g_sheerDSSCache.end()) return it->second;
    }

    ID3D11DepthStencilState* created = nullptr;
    if (FAILED(g_device->CreateDepthStencilState(&d, &created)) || !created) return nullptr;
    {
        std::lock_guard<std::mutex> lk(g_mtx);
        auto it = g_sheerDSSCache.find(key);
        if (it != g_sheerDSSCache.end()) {
            created->Release();
            return it->second;
        }
        g_sheerDSSCache[key] = created;
    }
    LogFmt("Created Sheer DSS %p (origFunc=%d -> newFunc=%d, stencil=%d)\n",
           created, origFunc, (int)d.DepthFunc, (int)d.StencilEnable);
    return created;
}

ID3D11RasterizerState* GetOrCreateDoubleSidedRS(ID3D11RasterizerState* oldRS, int* outOrigCull) {
    if (outOrigCull) *outOrigCull = 0;
    if (!g_device) return nullptr;
    D3D11_RASTERIZER_DESC d{};
    if (oldRS) {
        oldRS->GetDesc(&d);
    } else {
        d.FillMode = D3D11_FILL_SOLID;
        d.CullMode = D3D11_CULL_BACK;
        d.DepthClipEnable = TRUE;
    }
    if (outOrigCull) *outOrigCull = (int)d.CullMode;
    // Already double-sided (CULL_NONE) or explicit backface pass (CULL_FRONT) -> keep engine RS untouched
    if (d.CullMode == D3D11_CULL_NONE || d.CullMode == D3D11_CULL_FRONT) {
        return nullptr;
    }
    d.CullMode = D3D11_CULL_NONE;
    uint64_t key = (uint64_t(d.FillMode) & 0xF) |
                   (uint64_t(d.FrontCounterClockwise ? 1 : 0) << 4) |
                   (uint64_t(d.ScissorEnable ? 1 : 0) << 5) |
                   (uint64_t(d.DepthClipEnable ? 1 : 0) << 6) |
                   (uint64_t(d.MultisampleEnable ? 1 : 0) << 7) |
                   (uint64_t(d.AntialiasedLineEnable ? 1 : 0) << 8) |
                   (uint64_t(uint32_t(d.DepthBias)) << 16);
    {
        std::lock_guard<std::mutex> lk(g_mtx);
        auto it = g_sheerRSCache.find(key);
        if (it != g_sheerRSCache.end()) return it->second;
    }
    ID3D11RasterizerState* created = nullptr;
    if (FAILED(g_device->CreateRasterizerState(&d, &created)) || !created) return nullptr;
    {
        std::lock_guard<std::mutex> lk(g_mtx);
        auto it = g_sheerRSCache.find(key);
        if (it != g_sheerRSCache.end()) {
            created->Release();
            return it->second;
        }
        g_sheerRSCache[key] = created;
    }
    LogFmt("Created Double-Sided RS %p (origCull=%d -> CULL_NONE, scissor=%d)\n",
           created, outOrigCull ? *outOrigCull : -1, (int)d.ScissorEnable);
    return created;
}

HRESULT STDMETHODCALLTYPE HookPresent(IDXGISwapChain* sc, UINT sync, UINT flags) {
    RenderVariantOverlay(sc);
    HRESULT hr = origPresent(sc, sync, flags);
    UpdateAllAtFrameBoundary(sc);
    return hr;
}

void STDMETHODCALLTYPE HookIASetVB(ID3D11DeviceContext* ctx, UINT startSlot, UINT numBufs,
                                   ID3D11Buffer* const* bufs, const UINT* strides, const UINT* offsets) {
    if (!t_inInternalDraw && startSlot == 0 && numBufs >= 1 && bufs) {
        auto& cs = GetCtxState(ctx);
        cs.boundVB0 = bufs[0];
        cs.boundVB0Stride = strides ? strides[0] : 32;
        cs.boundVB0Offset = offsets ? offsets[0] : 0;
        if (cs.boundVB0) {
            CaptureBoundSurfaceState(cs);
            if (!g_pack.variants.empty()) {
                std::lock_guard<std::mutex> lk(g_mtx);
                auto vit = g_variantVBs.find(cs.boundVB0);
                if (vit != g_variantVBs.end()) vit->second.seenThisFrame = true;
            }
        }
    }
    GetCtxOrig(ctx).iaSetVB(ctx, startSlot, numBufs, bufs, strides, offsets);
    if (!t_inInternalDraw) {
        ReassertDrawHooks(ctx);
    }
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
    if (!g_depthDirKnown.load(std::memory_order_relaxed)) {
        DetectDepthDirectionOnce(ctx);
    }
    auto orig = GetCtxOrig(ctx);
    auto& cs = GetCtxState(ctx);
    if (IsVariantHiddenNow(cs)) {
        return;
    }
    SheerDrawPlan plan = GetSheerDrawPlan(cs);
    if (plan.active) {
        ID3D11BlendState* oldBlend = nullptr;
        FLOAT oldBF[4] = {};
        UINT oldMask = 0xFFFFFFFFu;
        ctx->OMGetBlendState(&oldBlend, oldBF, &oldMask);
        ID3D11RasterizerState* oldRS = nullptr;
        ctx->RSGetState(&oldRS);
        int origCull = 0;
        ID3D11RasterizerState* doubleSidedRS = GetOrCreateDoubleSidedRS(oldRS, &origCull);
        ID3D11DepthStencilState* oldDSS = nullptr;
        UINT oldStencilRef = 0;
        ID3D11DepthStencilState* sheerDSS = nullptr;
        if (!plan.opaqueSolid) {
            ctx->OMGetDepthStencilState(&oldDSS, &oldStencilRef);
            sheerDSS = GetOrCreateSheerDSS(oldDSS);
        }

        ID3D11Buffer* origVB = cs.boundVB0;
        UINT stride = cs.boundVB0Stride ? cs.boundVB0Stride : 32;
        UINT offset = cs.boundVB0Offset;

        t_inInternalDraw = true;
        if (doubleSidedRS) ctx->RSSetState(doubleSidedRS);
        if (!plan.opaqueSolid) {
            orig.iaSetVB(ctx, 0, 1, &plan.vbToDraw, &stride, &offset);
            ctx->OMSetBlendState(g_sheerBlend, nullptr, 0xFFFFFFFFu);
            if (sheerDSS) ctx->OMSetDepthStencilState(sheerDSS, oldStencilRef);
        } else {
            ctx->OMSetBlendState(g_opaqueBlend, nullptr, 0xFFFFFFFFu);
        }
        orig.psSetShader(ctx, g_sheerPS, nullptr, 0);
        orig.psSetCB(ctx, 4, 1, &g_sheerCB);
        void** vt = *reinterpret_cast<void***>(ctx);
        FnDrawIndexed realDraw = (vt && vt[12] != reinterpret_cast<void*>(HookDrawIndexed))
                                 ? reinterpret_cast<FnDrawIndexed>(vt[12])
                                 : orig.drawIndexed;
        realDraw(ctx, indexCount, startIndex, baseVertex);
        ID3D11Buffer* nullCB = nullptr;
        orig.psSetCB(ctx, 4, 1, &nullCB);
        orig.psSetShader(ctx, cs.boundPS, nullptr, 0);
        if (!plan.opaqueSolid) {
            ctx->OMSetDepthStencilState(oldDSS, oldStencilRef);
            orig.iaSetVB(ctx, 0, 1, &origVB, &stride, &offset);
        }
        if (doubleSidedRS) ctx->RSSetState(oldRS);
        ctx->OMSetBlendState(oldBlend, oldBF, oldMask);
        t_inInternalDraw = false;
        ReassertDrawHooks(ctx);
        if (oldBlend) oldBlend->Release();
        if (oldRS) oldRS->Release();
        if (oldDSS) oldDSS->Release();
        ID3D11Buffer* drawnVb = plan.vbToDraw;
        if (plan.vbToDraw) plan.vbToDraw->Release();
        bool logThis = false;
        {
            std::lock_guard<std::mutex> lk(g_mtx);
            if (g_loggedSheerVBs.find(drawnVb) == g_loggedSheerVBs.end()) {
                g_loggedSheerVBs.insert(drawnVb);
                logThis = true;
            }
        }
        g_sheerDrawCount.fetch_add(1);
        if (logThis) {
            LogFmt("Sheer/Opaque DrawIndexed active (ctx=%p, mode=%d, vb=%p, origCull=%d, forcedDoubleSided=%d, revZ=%d)\n",
                   ctx, g_sheerClothMode.load(), drawnVb, origCull, doubleSidedRS ? 1 : 0, g_depthIsReverseZ.load() ? 1 : 0);
        }
        return;
    }
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
    if (!g_depthDirKnown.load(std::memory_order_relaxed)) {
        DetectDepthDirectionOnce(ctx);
    }
    auto orig = GetCtxOrig(ctx);
    auto& cs = GetCtxState(ctx);
    if (IsVariantHiddenNow(cs)) {
        return;
    }
    SheerDrawPlan plan = GetSheerDrawPlan(cs);
    if (plan.active) {
        ID3D11BlendState* oldBlend = nullptr;
        FLOAT oldBF[4] = {};
        UINT oldMask = 0xFFFFFFFFu;
        ctx->OMGetBlendState(&oldBlend, oldBF, &oldMask);
        ID3D11RasterizerState* oldRS = nullptr;
        ctx->RSGetState(&oldRS);
        int origCull = 0;
        ID3D11RasterizerState* doubleSidedRS = GetOrCreateDoubleSidedRS(oldRS, &origCull);
        ID3D11DepthStencilState* oldDSS = nullptr;
        UINT oldStencilRef = 0;
        ID3D11DepthStencilState* sheerDSS = nullptr;
        if (!plan.opaqueSolid) {
            ctx->OMGetDepthStencilState(&oldDSS, &oldStencilRef);
            sheerDSS = GetOrCreateSheerDSS(oldDSS);
        }

        ID3D11Buffer* origVB = cs.boundVB0;
        UINT stride = cs.boundVB0Stride ? cs.boundVB0Stride : 32;
        UINT offset = cs.boundVB0Offset;

        t_inInternalDraw = true;
        if (doubleSidedRS) ctx->RSSetState(doubleSidedRS);
        if (!plan.opaqueSolid) {
            orig.iaSetVB(ctx, 0, 1, &plan.vbToDraw, &stride, &offset);
            ctx->OMSetBlendState(g_sheerBlend, nullptr, 0xFFFFFFFFu);
            if (sheerDSS) ctx->OMSetDepthStencilState(sheerDSS, oldStencilRef);
        } else {
            ctx->OMSetBlendState(g_opaqueBlend, nullptr, 0xFFFFFFFFu);
        }
        orig.psSetShader(ctx, g_sheerPS, nullptr, 0);
        orig.psSetCB(ctx, 4, 1, &g_sheerCB);
        void** vt = *reinterpret_cast<void***>(ctx);
        FnDrawIndexedInstanced realDraw = (vt && vt[20] != reinterpret_cast<void*>(HookDrawIndexedInstanced))
                                          ? reinterpret_cast<FnDrawIndexedInstanced>(vt[20])
                                          : orig.drawIndexedInstanced;
        realDraw(ctx, indexCountPerInst, instCount, startIndex, baseVertex, startInst);
        ID3D11Buffer* nullCB = nullptr;
        orig.psSetCB(ctx, 4, 1, &nullCB);
        orig.psSetShader(ctx, cs.boundPS, nullptr, 0);
        if (!plan.opaqueSolid) {
            ctx->OMSetDepthStencilState(oldDSS, oldStencilRef);
            orig.iaSetVB(ctx, 0, 1, &origVB, &stride, &offset);
        }
        if (doubleSidedRS) ctx->RSSetState(oldRS);
        ctx->OMSetBlendState(oldBlend, oldBF, oldMask);
        t_inInternalDraw = false;
        ReassertDrawHooks(ctx);
        if (oldBlend) oldBlend->Release();
        if (oldRS) oldRS->Release();
        if (oldDSS) oldDSS->Release();
        if (plan.vbToDraw) plan.vbToDraw->Release();
        g_sheerDrawCount.fetch_add(1);
        return;
    }
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
    wcscpy_s(g_dllDir, dllDir);
    LoadPanelHotkeyConfig();

    wchar_t logPath[MAX_PATH] = {};
    swprintf_s(logPath, L"%stew1_dyn_runtime.log", dllDir);
    g_log = CreateFileW(logPath, GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, CREATE_ALWAYS, 0, nullptr);
    char hkName[32] = {};
    GetVkConfigNameA(g_panelToggleVK.load(), hkName, sizeof(hkName));
    LogFmt("TEW1 Generic Dynamic Runtime v3.10 (Chapter-Safe COM-Pinned VBs + Auto-GC + Double-Sided Sheer + Hotkey=[%s]) starting...\n", hkName);

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
