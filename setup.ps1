# ============================================================================
#  Bernie Studio - first-run auto-installer (Windows / NVIDIA)
#  Installs EVERYTHING: ComfyUI engine, cu128 PyTorch (Blackwell-ready), all AI
#  models (Flux, Wan 2.2, ACE-Step, Real-ESRGAN), custom nodes, Python deps, and
#  Ollama + local LLMs. Hardware-aware: scales model/resolution to your GPU.
#  Re-runnable (skips finished stages). Run:  .\setup.ps1
# ============================================================================
$ErrorActionPreference = "Continue"
$REPO   = $PSScriptRoot
$HOMEDIR= if ($env:BERNIE_HOME) { $env:BERNIE_HOME } else { Join-Path $REPO "BernieStudioData" }
$ENG    = Join-Path $HOMEDIR "ComfyUI"
$PYDIR  = Join-Path $HOMEDIR "python_embeded"
$PY     = Join-Path $PYDIR "python.exe"
$MK     = Join-Path $HOMEDIR ".installed"
New-Item -ItemType Directory -Force -Path $HOMEDIR | Out-Null
function Say($m){ Write-Host "[bernie-setup] $m" -ForegroundColor Cyan }

# ---------- 0. hardware detection (vendor + VRAM) ----------
$vram = 0; $vendor = "cpu"
try { $vram = [int]((nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits) -split "`n")[0] / 1024; if ($vram -gt 0) { $vendor = "nvidia" } } catch {}
if ($vendor -ne "nvidia") {
  try {
    $gname = (Get-CimInstance Win32_VideoController | Where-Object { $_.AdapterRAM -ne $null } | Sort-Object AdapterRAM -Descending | Select-Object -First 1).Name
    if ($gname -match "Radeon|AMD") { $vendor = "amd" }
    elseif ($gname -match "Arc|Intel") { $vendor = "intel" }
    elseif ($gname -match "NVIDIA|GeForce|RTX|Quadro") { $vendor = "nvidia" }
    # try registry for true VRAM (AdapterRAM caps at 4GB)
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

# ---------- 0b. prerequisites (git, ffmpeg) via winget ----------
function Need($exe, $wingetId) {
  if (Get-Command $exe -ErrorAction SilentlyContinue) { return }
  Say "installing prerequisite: $exe ..."
  try { winget install -e --id $wingetId --silent --accept-source-agreements --accept-package-agreements 2>&1 | Out-Null }
  catch { Say "could not auto-install $exe - please install it manually." }
}
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
  Say "WARNING: winget not found. Please install git + ffmpeg manually if the next steps fail."
}
Need "git" "Git.Git"
Need "ffmpeg" "Gyan.FFmpeg"
# refresh PATH in this session so the just-installed tools are usable
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path","User")

# ---------- 1. tools: 7-Zip (from GitHub mirror; 7-zip.org is often blocked) ----------
$SZ = Join-Path $HOMEDIR "7zip\7z.exe"
if (-not (Test-Path $SZ)) {
  Say "installing 7-Zip..."
  try {
    $rel = Invoke-RestMethod "https://api.github.com/repos/ip7z/7zip/releases/latest" -Headers @{'User-Agent'='bernie'}
    $url = ($rel.assets | Where-Object { $_.name -match 'x64\.exe$' })[0].browser_download_url
    $exe = Join-Path $HOMEDIR "7zinst.exe"
    & curl.exe -sL -o $exe $url
    & $exe /S /D=(Join-Path $HOMEDIR "7zip"); Start-Sleep 6
  } catch { Say "7-Zip install failed: $_" }
}

# ---------- 2. ComfyUI portable (engine + bundled python) ----------
if (-not (Test-Path (Join-Path $ENG "main.py"))) {
  Say "downloading ComfyUI portable (~1.6GB)..."
  $p7 = Join-Path $HOMEDIR "comfy_portable.7z"
  & curl.exe -L --retry 8 -C - -o $p7 "https://github.com/comfyanonymous/ComfyUI/releases/download/latest/ComfyUI_windows_portable_nvidia.7z"
  Say "extracting engine..."
  & $SZ x $p7 "-o$HOMEDIR" -y | Out-Null
  $wp = Join-Path $HOMEDIR "ComfyUI_windows_portable"
  if (Test-Path $wp) {
    Move-Item (Join-Path $wp "ComfyUI") $ENG -Force -ErrorAction SilentlyContinue
    if (-not (Test-Path $PY)) { Move-Item (Join-Path $wp "python_embeded") $PYDIR -Force -ErrorAction SilentlyContinue }
    Remove-Item $wp -Recurse -Force -ErrorAction SilentlyContinue
  }
  Remove-Item $p7 -Force -ErrorAction SilentlyContinue
}
# the portable bundles an old ComfyUI; use the latest source for newest nodes (Wan2.2, ACE-Step)
if (-not (Test-Path (Join-Path $ENG ".git"))) {
  Say "updating ComfyUI to latest source..."
  $tmp = Join-Path $HOMEDIR "ComfyUI_src"
  & git clone --depth 1 https://github.com/comfyanonymous/ComfyUI $tmp 2>&1 | Out-Null
  if (Test-Path (Join-Path $tmp "main.py")) {
    Copy-Item (Join-Path $tmp "*") $ENG -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
  }
}

# ---------- 3. PyTorch (vendor-specific) + ComfyUI requirements ----------
& $PY -m pip install --upgrade pip 2>&1 | Out-Null
if ($vendor -eq "nvidia") {
  Say "installing PyTorch cu128 (NVIDIA, Blackwell-ready, ~2.7GB)..."
  & $PY -m pip install --force-reinstall torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128 2>&1 | Select-Object -Last 1
} elseif ($vendor -eq "amd" -or $vendor -eq "intel") {
  Say "installing PyTorch + torch-directml ($vendor, DirectML backend)..."
  & $PY -m pip install --force-reinstall torch-directml 2>&1 | Select-Object -Last 2
} else {
  Say "installing PyTorch (CPU build)..."
  & $PY -m pip install --force-reinstall torch torchvision torchaudio 2>&1 | Select-Object -Last 1
}
& $PY -m pip install -r (Join-Path $ENG "requirements.txt") 2>&1 | Select-Object -Last 1
& $PY -m pip install --upgrade "huggingface_hub" edge-tts pillow numpy 2>&1 | Out-Null
& $PY -c "import torch;print('[bernie-setup] torch',torch.__version__,'CUDA',torch.cuda.is_available())"

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
Grab "$H/ai-forever/Real-ESRGAN/resolve/main/RealESRGAN_x4.pth" (Join-Path $MD "upscale_models\RealESRGAN_x4plus_anime_6B.pth") $false

# ---------- 6. Ollama + local LLM (the free agent/vision brains) ----------
$ollama = (Get-Command ollama -ErrorAction SilentlyContinue)
if (-not $ollama) {
  Say "installing Ollama..."
  try { & winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements 2>&1 | Out-Null }
  catch { Say "Install Ollama manually from https://ollama.com/download then re-run setup." }
}
$llm = if ($tier -eq "ultra") { "qwen2.5:32b" } elseif ($tier -eq "high") { "qwen2.5:14b" } else { "qwen2.5vl:7b" }
Say "pulling local LLMs (agents=$llm, vision=qwen2.5vl:7b)..."
try { & ollama pull $llm 2>&1 | Select-Object -Last 1; & ollama pull qwen2.5vl:7b 2>&1 | Select-Object -Last 1 } catch { Say "ollama pull failed (is Ollama running?)" }

# ---------- done ----------
Set-Content $MK "tier=$tier vram=$vram ram=$ram $(Get-Date -Format o)"
Say "================  SETUP COMPLETE (tier: $tier)  ================"
Say "Make an episode:   .\run.bat"
