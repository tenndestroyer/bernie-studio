"""Bernie Studio self-test / repair tool — "does my install work?".

Runs a battery of non-destructive checks (python, ffmpeg, git, Ollama, ComfyUI,
key model files, free disk, GPU/tier, keys.env) and prints a clean table. With
--fix it attempts SAFE repairs only (winget install missing tools, `ollama pull`
a missing local model if Ollama is up, `pip install -r requirements.txt`). It
never deletes anything, never raises, and degrades gracefully when files/dirs or
external tools are absent.

Honest limits: `--fix` can only do things that are themselves safe and quick.
It cannot download the multi-gigabyte Flux / Wan / ACE model checkpoints (that is
the job of setup.ps1) — for those it just tells you they're missing. winget/pip
may still fail on a locked-down machine; failures are reported, not hidden.
"""
import sys
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import os, json, shutil, subprocess, argparse, urllib.request, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
try:
    import config
except Exception:
    config = None
try:
    import comfy
except Exception:
    comfy = None
try:
    import workflows
except Exception:
    workflows = None


# ---------- small helpers (never raise) ----------
def _which(name):
    try:
        return shutil.which(name)
    except Exception:
        return None


def _run(cmd, timeout=60):
    """Run a command, return (rc, output). Never raises."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return -1, f"{type(e).__name__}: {e}"


def _http_json(url, timeout=5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _check(name, ok, detail, fixable=False):
    return {"name": name, "ok": bool(ok), "detail": str(detail), "fixable": bool(fixable)}


# ---------- individual checks ----------
def _check_python():
    v = sys.version_info
    ok = v >= (3, 10)
    return _check("python>=3.10", ok, f"running {v.major}.{v.minor}.{v.micro}", fixable=False)


def _check_tool(tool, fixable=True):
    path = _which(tool)
    return _check(f"{tool} on PATH", bool(path), path or "not found", fixable=(fixable and not path))


def _check_ollama():
    if config is None:
        return _check("Ollama reachable", False, "config import failed", fixable=False)
    tags = _http_json(config.OLLAMA_URL.rstrip("/") + "/api/tags", timeout=5)
    if tags is None:
        return _check("Ollama reachable", False,
                      f"no response at {config.OLLAMA_URL} (is `ollama serve` running?)",
                      fixable=False)
    models = [m.get("name", "") for m in tags.get("models", [])]
    want = config.LOCAL_LLM_MODEL
    # ollama tags often carry a :tag suffix; match loosely
    have = any(want == m or m.startswith(want.split(":")[0]) for m in models)
    return _check("Ollama reachable", True,
                  f"up; local model '{want}' " + ("present" if have else "MISSING (fix: ollama pull)") +
                  f"; {len(models)} model(s) installed",
                  fixable=not have)


def _check_comfy():
    if comfy is None:
        return _check("ComfyUI reachable", False, "comfy import failed", fixable=False)
    try:
        up = comfy.server_up()
    except Exception as e:
        up = False
        return _check("ComfyUI reachable", False, f"server_up() error: {e}", fixable=False)
    url = getattr(config, "COMFY_URL", "?") if config else "?"
    return _check("ComfyUI reachable", up,
                  f"up at {url}" if up else f"down at {url} (start via pipeline / comfy.start_server)",
                  fixable=False)


def _check_models():
    """Existence-only checks for the big model files under ENGINE/models."""
    if config is None or workflows is None:
        return [_check("model files", False, "config/workflows import failed", fixable=False)]
    models_root = config.ENGINE / "models"
    # (label, filename, subdir-candidates) — names come straight from workflows.py
    wan_unet = getattr(workflows, "WAN_UNET", "wan2.2_ti2v_5B_fp16.safetensors")
    targets = [
        ("flux1-dev unet", getattr(workflows, "FLUX_UNET", "flux1-dev.safetensors"),
         ["unet", "diffusion_models", "checkpoints"]),
        ("wan unet",       wan_unet,                ["unet", "diffusion_models", "checkpoints"]),
        ("wan vae",        getattr(workflows, "WAN_VAE", "wan2.2_vae.safetensors"), ["vae"]),
        ("ace-step ckpt",  getattr(workflows, "ACE_CKPT", "ace_step_v1_3.5b.safetensors"),
         ["checkpoints"]),
    ]
    results = []
    for label, fname, subdirs in targets:
        found = ""
        try:
            if models_root.exists():
                for sd in subdirs:
                    cand = models_root / sd / fname
                    if cand.exists():
                        found = str(cand)
                        break
                if not found:
                    # last-resort shallow scan anywhere under models/ (cheap, names are unique)
                    for sd in subdirs:
                        d = models_root / sd
                        if d.exists():
                            for p in d.glob(fname):
                                found = str(p); break
                        if found:
                            break
        except Exception as e:
            found = ""
        results.append(_check(f"model: {label}", bool(found),
                              found or f"{fname} missing under {models_root} (run setup to download)",
                              fixable=False))
    return results


def _check_disk():
    if config is None:
        return _check("free disk >20GB", False, "config import failed", fixable=False)
    target = config.STORAGE
    try:
        # walk up to an existing parent if STORAGE doesn't exist yet
        probe = target
        while not probe.exists() and probe.parent != probe:
            probe = probe.parent
        total, used, free = shutil.disk_usage(str(probe))
        free_gb = free / (1024 ** 3)
        return _check("free disk >20GB", free_gb >= 20,
                      f"{free_gb:.1f} GB free on {probe.drive or probe}", fixable=False)
    except Exception as e:
        return _check("free disk >20GB", False, f"could not stat {target}: {e}", fixable=False)


def _check_gpu():
    if config is None:
        return _check("GPU / tier", False, "config import failed", fixable=False)
    try:
        s = config.summary()
    except Exception as e:
        s = f"summary() error: {e}"
    # not a pass/fail gate per se — but CPU-only is worth flagging as not-ok
    ok = getattr(config, "GPU_VENDOR", "cpu") != "cpu"
    detail = s if ok else (s + "  [WARNING: no GPU detected — rendering will be extremely slow]")
    return _check("GPU / tier", ok, detail, fixable=False)


def _check_keys_env():
    if config is None:
        return _check("keys.env present", False, "config import failed", fixable=False)
    f = config.REPO / "keys.env"
    if f.exists():
        return _check("keys.env present", True, str(f), fixable=False)
    return _check("keys.env present", True,  # not a hard failure: local Ollama works with no keys
                  f"not found ({f}) — optional; local Ollama is the free fallback", fixable=False)


# ---------- SAFE repairs (only when fix=True) ----------
def _winget_install(pkg_id):
    if _which("winget") is None:
        return False, "winget not available"
    rc, out = _run(["winget", "install", "-e", "--id", pkg_id,
                    "--accept-source-agreements", "--accept-package-agreements"], timeout=600)
    return rc == 0, out.strip()[-300:]


def _try_fix(chk):
    """Attempt one safe repair for a failed, fixable check. Returns a status string."""
    name = chk["name"]
    try:
        if name == "ffmpeg on PATH":
            ok, msg = _winget_install("Gyan.FFmpeg")
            return f"winget ffmpeg: {'ok' if ok else 'failed'} ({msg})"
        if name == "git on PATH":
            ok, msg = _winget_install("Git.Git")
            return f"winget git: {'ok' if ok else 'failed'} ({msg})"
        if name == "Ollama reachable" and config is not None:
            # only reachable+model-missing checks are marked fixable
            model = config.LOCAL_LLM_MODEL
            if _which("ollama") is None:
                return "ollama CLI not on PATH; cannot pull"
            rc, out = _run(["ollama", "pull", model], timeout=1800)
            return f"ollama pull {model}: {'ok' if rc == 0 else 'failed'} ({out.strip()[-200:]})"
    except Exception as e:
        return f"fix error: {e}"
    return "no safe fix available"


def _try_pip_requirements():
    """Optional safe repair: pip install -r requirements.txt if present."""
    if config is None:
        return None
    req = config.REPO / "requirements.txt"
    if not req.exists():
        return None
    rc, out = _run([sys.executable, "-m", "pip", "install", "-r", str(req)], timeout=900)
    return _check("pip install -r requirements.txt", rc == 0,
                  out.strip()[-300:] if out else f"rc={rc}", fixable=False)


# ---------- public API ----------
def run(fix=False):
    """Run all checks. Returns {"ok":bool, "checks":[{name,ok,detail,fixable}...]}.

    If fix=True, attempts SAFE, non-destructive repairs on failed+fixable checks,
    then re-records the (post-fix) detail. Never raises.
    """
    checks = []
    checks.append(_check_python())
    checks.append(_check_tool("ffmpeg"))
    checks.append(_check_tool("git"))
    checks.append(_check_ollama())
    checks.append(_check_comfy())
    checks.extend(_check_models())
    checks.append(_check_disk())
    checks.append(_check_gpu())
    checks.append(_check_keys_env())

    if fix:
        for chk in checks:
            if not chk["ok"] and chk["fixable"]:
                status = _try_fix(chk)
                chk["detail"] = f"{chk['detail']} | FIX: {status}"
        # optional requirements install (independent of a specific failed check)
        pipres = _try_pip_requirements()
        if pipres is not None:
            checks.append(pipres)
        # re-run the cheap, repaired checks so the table reflects reality
        refreshed = [_check_python(), _check_tool("ffmpeg"), _check_tool("git"),
                     _check_ollama(), _check_comfy()]
        # splice refreshed results back over their originals (match by name)
        by_name = {c["name"]: c for c in refreshed}
        for i, chk in enumerate(checks):
            if chk["name"] in by_name:
                checks[i] = by_name[chk["name"]]

    overall = all(c["ok"] for c in checks)
    return {"ok": overall, "checks": checks}


def main():
    ap = argparse.ArgumentParser(
        description="Bernie Studio install doctor — self-test and SAFE auto-repair.")
    ap.add_argument("--fix", action="store_true",
                    help="attempt safe, non-destructive repairs (winget/ollama pull/pip)")
    args = ap.parse_args()

    report = run(fix=args.fix)
    checks = report["checks"]

    name_w = max((len(c["name"]) for c in checks), default=4)
    print()
    print(f"{'CHECK'.ljust(name_w)}  STATUS  DETAIL")
    print(f"{'-' * name_w}  ------  ------")
    for c in checks:
        mark = "OK  " if c["ok"] else "FAIL"
        fixtag = "" if c["ok"] or not c["fixable"] else "  [fixable: run --fix]"
        print(f"{c['name'].ljust(name_w)}  {mark}    {c['detail']}{fixtag}")
    print()

    if report["ok"]:
        print("RESULT: OK — install looks healthy.")
        sys.exit(0)
    else:
        nfail = sum(1 for c in checks if not c["ok"])
        hint = "" if args.fix else "  (try --fix for safe auto-repairs)"
        print(f"RESULT: PROBLEMS — {nfail} check(s) failed.{hint}")
        sys.exit(1)


if __name__ == "__main__":
    main()
