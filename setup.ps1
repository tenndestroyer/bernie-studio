# ============================================================================
#  Bernie Studio - first-run auto-installer (Windows)
#  Installs EVERYTHING with NO dependency on your system Python:
#    * a pinned, torch-compatible EMBEDDED Python 3.12 (so "Python is too new /
#      can't install torch" can never happen, even on Python 3.14 machines)
#    * ComfyUI engine (latest), vendor-correct PyTorch
#      (cu128 NVIDIA / DirectML AMD-Intel / CPU)
#    * all AI models (Flux, Wan 2.2, ACE-Step, Real-ESRGAN), custom nodes,
#      Ollama + local LLMs
#  Re-runnable (skips finished stages). Only writes the .installed marker once
#  PyTorch actually imports, so a half-finished install never looks "done".
#  Run:  .\setup.ps1
# ============================================================================
$ErrorActionPreference = "Continue"
$REPO    = $PSScriptRoot
$HOMEDIR = if ($env:BERNIE_HOME) { $env:BERNIE_HOME } else { Join-Path $REPO "BernieStudioData" }
$ENG     = Join-Path $HOMEDIR "ComfyUI"
$PYDIR   = Join-Path $HOMEDIR "python_embeded"
$PY      = Join-Path $PYDIR "python.exe"
$MK      = Join-Path $HOMEDIR ".installed"
New-Item -ItemType Directory -Force -Path $HOMEDIR | Out-Null
function Say($m){ Write-Host "[bernie-setup] $m" -ForegroundColor Cyan }
function Die($m){ Write-Host "[bernie-setup] ERROR: $m" -ForegroundColor Red }

# ---------- 0. hardware detection (vendor + VRAM) ----------
$vram = 0; $vendor = "cpu"
try { $vram = [int]((nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits) -split "`n")[0] / 1024; if ($vram -gt 0) { $vendor = "nvidia" } } catch {}
if ($vendor -ne "nvidia") {
  try {
    $gname = (Get-CimInstance Win32_VideoController | Where-Object { $_.AdapterRAM -ne $null } | Sort-Object AdapterRAM -Descending | Select-Object -First 1).Name
    if ($gname -match "Radeon|AMD") { $vendor = "amd" }
    elseif ($gname -match "Arc|Intel") { $vendor = "intel" }
    elseif ($gname -match "NVIDIA|GeForce|RTX|Quadro") { $vendor = "nvidia" }
    $m = 0; Get-ChildItem 'HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}' -ErrorAction SilentlyContinue | ForEach-Object { $v=(Get-ItemProperty $_.PSPath -Name 'HardwareInformation.qwMemorySize' -ErrorAction SilentlyContinue).'HardwareInformation.qwMemorySize'; if($v -gt $m){$m=$v} }
    if ($m -gt 0) { $vram = [math]::Round($m/1GB,0) }
  } catch {}
}
if ($env:BERNIE_GPU) { $vendor = $env:BERNIE_GPU }
$ram = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB,0)
$tier = if ($env:BERNIE_TIER) { $env:BERNIE_TIER }
        elseif ($vram -ge 22) { "ultra" } elseif ($vram -ge 15) { "high" }
        elseif ($vram -ge 11) { "balanced" } else { "low" }
Say "Detected GPU: $vendor, VRAM=${vram}GB, RAM=${ram}GB  ->  quality tier: $tier"
if ($vendor -eq "nvidia") { Say "NVIDIA/CUDA backend (fully supported)." }
elseif ($vendor -eq "amd" -or $vendor -eq "intel") { Say "$vendor GPU -> DirectML backend (EXPERIMENTAL/best-effort; needs more VRAM, no fp8)." }
else { Say "WARNING: no supported GPU detected -> CPU mode (extremely slow; for testing only)." }
if ($vram -lt 8 -and $vendor -ne "cpu") { Say "WARNING: <8GB VRAM. Rendering will be very slow / may not fit." }

# free-disk sanity check (~70GB needed for models+engine+output)
try {
  $drive = (Get-Item $HOMEDIR).PSDrive.Name
  $free  = [math]::Round((Get-PSDrive $drive).Free/1GB,0)
  Say "Free disk on ${drive}: ${free}GB"
  if ($free -lt 70) { Say "WARNING: <70GB free. Models + output may not fit. Set BERNIE_HOME to a bigger drive." }
} catch {}

# ---------- 0b. prerequisites (git, ffmpeg) via winget ----------
function Need($exe, $wingetId) {
  if (Get-Command $exe -ErrorAction SilentlyContinue) { return }
  Say "installing prerequisite: $exe ..."
  try { winget install -e --id $wingetId --silent --accept-source-agreements --accept-package-agreements 2>&1 | Out-Null }
  catch { Say "could not auto-install $exe - please install it manually." }
}
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
  Say "WARNING: winget not found. If git/ffmpeg are missing, install them manually."
}
Need "git" "Git.Git"
Need "ffmpeg" "Gyan.FFmpeg"
# refresh PATH so the just-installed tools are usable in this session
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path","User")
foreach ($t in @("curl.exe","tar.exe")) {
  if (-not (Get-Command $t -ErrorAction SilentlyContinue)) { Say "WARNING: $t not found (it ships with Windows 10/11; update Windows if downloads fail)." }
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Die "git is required and not available. Install Git for Windows, then re-run .\setup.ps1"; exit 1 }

# ---------- 1. ComfyUI engine (latest source) ----------
if (-not (Test-Path (Join-Path $ENG "main.py"))) {
  Say "cloning ComfyUI engine (latest)..."
  & git clone --depth 1 https://github.com/comfyanonymous/ComfyUI $ENG 2>&1 | Out-Null
  if (-not (Test-Path (Join-Path $ENG "main.py"))) { Die "ComfyUI clone failed (git installed? online?). Re-run .\setup.ps1"; exit 1 }
} else { Say "ComfyUI engine present." }

# ---------- 2. EMBEDDED Python 3.12 (pinned, torch-compatible) ----------
# This is the fix for "Python is too new / can't install torch": we NEVER use the
# system Python for the engine. We provision a standalone CPython 3.12 (PyTorch has
# no wheels for 3.14, and only just got 3.13 - 3.12 is the safe, supported choice).
function PyMinor($exe){
  try { return (& $exe -c "import sys;print('%d.%d'%(sys.version_info[0],sys.version_info[1]))" 2>$null) } catch { return $null }
}
function Ensure-EmbeddedPython {
  if (Test-Path $PY) {
    $v = PyMinor $PY
    if ($v -and ([version]$v -ge [version]"3.10") -and ([version]$v -le [version]"3.13")) { Say "embedded Python $v OK (torch-compatible)"; return $true }
    Say "bundled Python '$v' can't run PyTorch; replacing with a pinned standalone 3.12..."
    Remove-Item $PYDIR -Recurse -Force -ErrorAction SilentlyContinue
  } else { Say "provisioning a pinned standalone Python 3.12 (torch-compatible)..." }
  try {
    $rel = Invoke-RestMethod "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest" -Headers @{'User-Agent'='bernie-setup'}
    $asset = $rel.assets | Where-Object { $_.name -match 'cpython-3\.12\.\d+\+.*-x86_64-pc-windows-msvc-install_only\.tar\.gz$' } | Select-Object -First 1
    if (-not $asset) { Die "no standalone Python 3.12 asset found in the latest release."; return $false }
    $tgz = Join-Path $HOMEDIR "py312.tar.gz"
    Say "downloading $($asset.name) (~30MB)..."
    & curl.exe -L --retry 8 -C - -o $tgz $asset.browser_download_url
    Say "extracting Python..."
    & tar -xf $tgz -C $HOMEDIR
    $src = Join-Path $HOMEDIR "python"
    if (Test-Path (Join-Path $src "python.exe")) {
      if (Test-Path $PYDIR) { Remove-Item $PYDIR -Recurse -Force -ErrorAction SilentlyContinue }
      Move-Item $src $PYDIR -Force
    }
    Remove-Item $tgz -Force -ErrorAction SilentlyContinue
  } catch { Die "standalone Python download failed: $_"; return $false }
  if (Test-Path $PY) { Say "embedded Python $(PyMinor $PY) installed."; return $true }
  Die "embedded Python install failed."; return $false
}
if (-not (Ensure-EmbeddedPython)) { Die "Cannot continue without a working Python. Fix the above and re-run .\setup.ps1"; exit 1 }
& $PY -m ensurepip --upgrade 2>&1 | Out-Null

# ---------- 3. PyTorch (vendor-specific) + ComfyUI requirements ----------
& $PY -m pip install --upgrade pip setuptools wheel 2>&1 | Select-Object -Last 1
if ($vendor -eq "nvidia") {
  Say "installing PyTorch cu128 (NVIDIA, Blackwell-ready, ~2.7GB)..."
  & $PY -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128 2>&1 | Select-Object -Last 2
} elseif ($vendor -eq "amd" -or $vendor -eq "intel") {
  Say "installing torch-directml ($vendor, DirectML backend)..."
  & $PY -m pip install torch-directml 2>&1 | Select-Object -Last 2
} else {
  Say "installing PyTorch (CPU build)..."
  & $PY -m pip install torch torchvision torchaudio 2>&1 | Select-Object -Last 2
}
if (Test-Path (Join-Path $ENG "requirements.txt")) {
  Say "installing ComfyUI requirements..."
  & $PY -m pip install -r (Join-Path $ENG "requirements.txt") 2>&1 | Select-Object -Last 1
}
& $PY -m pip install --upgrade "huggingface_hub" edge-tts pillow numpy soundfile 2>&1 | Out-Null

# verify torch actually imports BEFORE we ever mark the install complete
$torchok = $false
try {
  $tv = & $PY -c "import torch,sys;print(torch.__version__, 'cuda='+str(torch.cuda.is_available()));sys.exit(0)" 2>&1
  Say "torch check -> $tv"
  if ($LASTEXITCODE -eq 0) { $torchok = $true }
} catch {}
if (-not $torchok) { Die "PyTorch did not import - rendering will NOT work yet (see messages above)." }
elseif ($vendor -eq "nvidia" -and ($tv -match "cuda=False")) { Say "WARNING: torch installed but CUDA not available - check your NVIDIA driver." }

# ---------- 4. custom nodes ----------
$CN = Join-Path $ENG "custom_nodes"; New-Item -ItemType Directory -Force -Path $CN | Out-Null
foreach ($u in @("https://github.com/kijai/ComfyUI-WanVideoWrapper.git",
                 "https://github.com/ltdrdata/ComfyUI-Manager.git")) {
  $n = ($u -split "/")[-1] -replace "\.git$",""
  if (-not (Test-Path (Join-Path $CN $n))) { Say "node: $n"; & git -C $CN clone --depth 1 $u 2>&1 | Out-Null }
}

# ---------- 5. models (hardware-aware) ----------
$MD = Join-Path $ENG "models"
foreach ($d in @("unet","vae","clip","diffusion_models","text_encoders","loras","upscale_models","checkpoints")) {
  New-Item -ItemType Directory -Force -Path (Join-Path $MD $d) | Out-Null
}
$TOK = $env:HF_TOKEN
function Grab($url,$dest,$auth){
  if ((Test-Path $dest) -and ((Get-Item $dest).Length -gt 1MB)) { Say "have $(Split-Path $dest -Leaf)"; return }
  Say "download $(Split-Path $dest -Leaf)"
  if ($auth -and $TOK) { & curl.exe -L --retry 8 -C - -H "Authorization: Bearer $TOK" -o $dest $url 2>&1 | Out-Null }
  else { & curl.exe -L --retry 8 -C - -o $dest $url 2>&1 | Out-Null }
}
$H = "https://huggingface.co"
if (-not $TOK) { Say "NOTE: set `$env:HF_TOKEN to a (free) HuggingFace token to fetch gated FLUX.1-dev. Get one at huggingface.co/settings/tokens and accept the FLUX.1-dev license." }
Grab "$H/black-forest-labs/FLUX.1-dev/resolve/main/flux1-dev.safetensors" (Join-Path $MD "unet\flux1-dev.safetensors") $true
Grab "$H/black-forest-labs/FLUX.1-dev/resolve/main/ae.safetensors" (Join-Path $MD "vae\ae.safetensors") $true
Grab "$H/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors" (Join-Path $MD "clip\clip_l.safetensors") $false
Grab "$H/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp8_e4m3fn.safetensors" (Join-Path $MD "clip\t5xxl_fp8_e4m3fn.safetensors") $false
Grab "$H/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors" (Join-Path $MD "diffusion_models\wan2.2_ti2v_5B_fp16.safetensors") $false
Grab "$H/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/vae/wan2.2_vae.safetensors" (Join-Path $MD "vae\wan2.2_vae.safetensors") $false
Grab "$H/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors" (Join-Path $MD "text_encoders\umt5_xxl_fp8_e4m3fn_scaled.safetensors") $false
Grab "$H/Comfy-Org/ACE-Step_ComfyUI_repackaged/resolve/main/all_in_one/ace_step_v1_3.5b.safetensors" (Join-Path $MD "checkpoints\ace_step_v1_3.5b.safetensors") $false
Grab "$H/ai-forever/Real-ESRGAN/resolve/main/RealESRGAN_x4.pth" (Join-Path $MD "upscale_models\RealESRGAN_x4.pth") $false

# ---------- 6. Ollama + local LLM (the free agent/vision brains) ----------
$ollama = (Get-Command ollama -ErrorAction SilentlyContinue)
if (-not $ollama) {
  Say "installing Ollama..."
  try { & winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements 2>&1 | Out-Null }
  catch { Say "Install Ollama manually from https://ollama.com/download then re-run setup." }
  $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
}
$llm = if ($tier -eq "ultra") { "qwen2.5:32b" } elseif ($tier -eq "high") { "qwen2.5:14b" } else { "qwen2.5vl:7b" }
Say "pulling local LLMs (agents=$llm, vision=qwen2.5vl:7b)..."
try { & ollama pull $llm 2>&1 | Select-Object -Last 1; & ollama pull qwen2.5vl:7b 2>&1 | Select-Object -Last 1 } catch { Say "ollama pull failed (is Ollama running?) - the app will retry later." }

# ---------- done ----------
if ($torchok) {
  Set-Content $MK "tier=$tier vram=$vram ram=$ram python=$(PyMinor $PY) $(Get-Date -Format o)"
  Say "================  SETUP COMPLETE (tier: $tier, Python $(PyMinor $PY))  ================"
  Say "Launch the app:   .\run.bat"
} else {
  Die "================  SETUP INCOMPLETE  ================"
  Die "PyTorch isn't working, so the marker was NOT written. Fix the errors above and re-run .\setup.ps1"
  exit 1
}
