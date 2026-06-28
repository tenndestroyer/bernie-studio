"""Portable, hardware-aware config for Bernie Studio.

Paths are derived from BERNIE_HOME (defaults to a 'BernieStudioData' folder next to the repo),
so the project runs anywhere with no hardcoded user paths. On import it auto-detects the GPU's
VRAM and system RAM and picks a quality TIER (video model size, native resolution, dtype, LLM
size) — so a 12 GB laptop and a 24 GB / 64 GB workstation each get appropriate settings.

LLM API keys are read from the environment / keys.env (never committed). Local Ollama is the
guaranteed free fallback, so the project works with zero cloud keys.
"""
import os, pathlib, shutil, subprocess, json

# ---------- locations (portable) ----------
REPO = pathlib.Path(__file__).resolve().parent.parent          # repo root
HOME = pathlib.Path(os.environ.get("BERNIE_HOME", REPO / "BernieStudioData")).resolve()
ENGINE   = HOME / "ComfyUI"                 # the render engine (downloaded by setup)
PY_EMBED = HOME / "python_embeded" / ("python.exe" if os.name == "nt" else "bin/python")
STORAGE  = pathlib.Path(os.environ.get("BERNIE_STORAGE", HOME / "data")).resolve()

SLOT         = os.environ.get("BERNIE_SLOT", "").strip()
EPISODE_NAME = os.environ.get("BERNIE_EP", "Bernie_Ep1").strip()
OUT          = STORAGE / "output"
WORK         = STORAGE / ("work" + (f"_{SLOT}" if SLOT else ""))
SHOTS        = WORK / "shots"
VOICES       = WORK / "voices"
MUSIC        = WORK / "music"
DATASET      = WORK / "lora_dataset"
COMFY_OUTPUT = STORAGE / "comfy_output"
LORA_OUT     = ENGINE / "models" / "loras"
LOGDIR       = HOME / "logs"
for d in (OUT, WORK, SHOTS, VOICES, MUSIC, DATASET, COMFY_OUTPUT, LOGDIR):
    d.mkdir(parents=True, exist_ok=True)

COMFY_URL = "http://127.0.0.1:8188"
FPS = 24

# ---------- hardware detection ----------
def _vram_gb():
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            text=True, timeout=15)
        return int(out.strip().splitlines()[0]) / 1024.0
    except Exception:
        return 0.0

def _ram_gb():
    try:
        if os.name == "nt":
            import ctypes
            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            ms = MS(); ms.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
            return ms.ullTotalPhys / 1e9
        else:
            return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
    except Exception:
        return 0.0

VRAM_GB = float(os.environ.get("BERNIE_VRAM_GB", 0) or _vram_gb())
RAM_GB  = float(os.environ.get("BERNIE_RAM_GB", 0) or _ram_gb())

# ---------- quality tier (auto, override with BERNIE_TIER) ----------
def _pick_tier():
    forced = os.environ.get("BERNIE_TIER")
    if forced: return forced
    if VRAM_GB >= 22: return "ultra"   # 24GB+ : Wan 14B, 1280x720 fp16
    if VRAM_GB >= 15: return "high"    # 16-22GB: Wan 5B, 1280x720
    if VRAM_GB >= 11: return "balanced"# 12-15GB: Wan 5B, 960x544 (laptop default)
    return "low"                       # <12GB : Wan 5B, 640x368

TIER = _pick_tier()
_TIERS = {
    "ultra":    dict(WAN_W=1280, WAN_H=720, WAN_FRAMES=121, WAN_STEPS=30, WAN_DTYPE="default",
                     WAN_MODEL="wan2.2_ti2v_5B", TILED=False, KEY_W=1280, KEY_H=720,
                     LLM_LOCAL="qwen2.5:32b"),
    "high":     dict(WAN_W=1280, WAN_H=720, WAN_FRAMES=81,  WAN_STEPS=30, WAN_DTYPE="fp8_e4m3fn",
                     WAN_MODEL="wan2.2_ti2v_5B", TILED=True,  KEY_W=1280, KEY_H=720,
                     LLM_LOCAL="qwen2.5:14b"),
    "balanced": dict(WAN_W=960,  WAN_H=544, WAN_FRAMES=81,  WAN_STEPS=28, WAN_DTYPE="fp8_e4m3fn",
                     WAN_MODEL="wan2.2_ti2v_5B", TILED=True,  KEY_W=1280, KEY_H=720,
                     LLM_LOCAL="qwen2.5vl:7b"),
    "low":      dict(WAN_W=640,  WAN_H=368, WAN_FRAMES=81,  WAN_STEPS=24, WAN_DTYPE="fp8_e4m3fn",
                     WAN_MODEL="wan2.2_ti2v_5B", TILED=True,  KEY_W=1024, KEY_H=576,
                     LLM_LOCAL="qwen2.5vl:7b"),
}
_t = _TIERS[TIER]
KEY_W, KEY_H = _t["KEY_W"], _t["KEY_H"]
WAN_W, WAN_H = _t["WAN_W"], _t["WAN_H"]
WAN_FRAMES, WAN_STEPS, WAN_DTYPE = _t["WAN_FRAMES"], _t["WAN_STEPS"], _t["WAN_DTYPE"]
WAN_MODEL, WAN_TILED = _t["WAN_MODEL"], _t["TILED"]
SHOT_SECONDS = WAN_FRAMES / FPS
UPSCALE = True

# ---------- LLM (free chain; local Ollama guaranteed fallback) ----------
def _load_keys_env():
    f = REPO / "keys.env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())
_load_keys_env()
OLLAMA_URL      = os.environ.get("OLLAMA_URL", "http://localhost:11434")
LOCAL_LLM_MODEL = os.environ.get("BERNIE_LLM", _t["LLM_LOCAL"])
def cerebras_key(): return os.environ.get("CEREBRAS_API_KEY", "")
GROQ_KEY    = os.environ.get("GROQ_API_KEY", "")
MISTRAL_KEY = os.environ.get("MISTRAL_API_KEY", "")
CEREBRAS_MODEL = "gpt-oss-120b"
# only include cloud providers that actually have a key; local ollama is always last
_chain = []
if cerebras_key(): _chain.append("cerebras")
if GROQ_KEY:       _chain.append("groq")
if MISTRAL_KEY:    _chain.append("mistral")
_chain.append("ollama")
LLM_CHAIN = os.environ.get("BERNIE_LLM_CHAIN", ",".join(_chain)).split(",")

def summary():
    return (f"Bernie Studio config | tier={TIER} VRAM={VRAM_GB:.0f}GB RAM={RAM_GB:.0f}GB | "
            f"Wan {WAN_W}x{WAN_H} {WAN_MODEL} {WAN_DTYPE} tiled={WAN_TILED} | "
            f"LLM chain={LLM_CHAIN} local={LOCAL_LLM_MODEL} | HOME={HOME}")

if __name__ == "__main__":
    print(summary())
