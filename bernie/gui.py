"""Bernie Studio — desktop GUI backend.

A dependency-free local web app (Python stdlib only) that turns the pipeline into
commercial-feeling creative software. It serves a single-page UI (bernie/web/index.html)
and a small JSON API that drives the EXISTING pipeline (make.py / series.py) — no command
line required.

    python -m bernie.gui            # or:  python bernie/gui.py
    run.bat                         # (launches this and opens the browser)

Endpoints
    GET  /                      -> the SPA
    GET  /api/status            -> system health + every render slot + library + series
    GET  /api/season            -> the built-in Season-1 plan and which episodes are done
    GET  /api/settings          -> current config + masked keys
    GET  /api/logs?name=&n=     -> tail of a log file
    POST /api/create            -> launch one episode (detached, resumable)
    POST /api/series            -> launch fully-autonomous series mode
    POST /api/settings          -> write keys.env / tier override
    POST /api/install           -> run the first-run installer (setup.ps1)
    POST /api/stop              -> best-effort stop of running renders + engine

Everything launches DETACHED (CREATE_NO_WINDOW | DETACHED_PROCESS on Windows) so a
closed console / restarted GUI never kills an in-flight render.
"""
import sys, os, json, time, shutil, subprocess, pathlib, threading, webbrowser, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config  # noqa: E402

REPO   = config.REPO
WEBDIR = HERE / "web"
JOBS   = config.HOME / "gui_jobs.json"          # remembers launched renders across GUI restarts
DETACH = (0x08000000 | 0x00000008) if os.name == "nt" else 0   # CREATE_NO_WINDOW|DETACHED_PROCESS

# how recently a slot must have written a file to count as "actively rendering"
ACTIVE_WINDOW = 8 * 60


# ----------------------------------------------------------------------------- helpers
def _run(cmd, timeout=15):
    try:
        return subprocess.check_output(cmd, text=True, timeout=timeout,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""

def _pid_alive(pid):
    if not pid:
        return False
    try:
        if os.name == "nt":
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))  # QUERY_LIMITED_INFO
            if not h:
                return False
            code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(h)
            return code.value == 259  # STILL_ACTIVE
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False

def _gpu_live():
    """Live GPU utilisation/memory (NVIDIA via nvidia-smi; best-effort otherwise)."""
    if config.GPU_VENDOR == "nvidia":
        out = _run(["nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                    "--format=csv,noheader,nounits"])
        if out:
            p = [x.strip() for x in out.splitlines()[0].split(",")]
            try:
                return {"util": int(float(p[0])), "mem_used": int(float(p[1])),
                        "mem_total": int(float(p[2])), "temp": int(float(p[3])), "live": True}
            except Exception:
                pass
    # fallback: no live telemetry, just the detected total
    return {"util": None, "mem_used": None,
            "mem_total": int(config.VRAM_GB * 1024) or None, "temp": None, "live": False}

def _comfy_up():
    try:
        with urllib.request.urlopen(config.COMFY_URL + "/system_stats", timeout=2):
            return True
    except Exception:
        return False

def _disk(path):
    try:
        u = shutil.disk_usage(str(path))
        return {"free_gb": round(u.free / 1e9, 1), "total_gb": round(u.total / 1e9, 1),
                "used_pct": round(100 * u.used / u.total)}
    except Exception:
        return {"free_gb": None, "total_gb": None, "used_pct": None}

def _newest_mtime(*paths):
    newest = 0.0
    for p in paths:
        try:
            if p.exists():
                newest = max(newest, p.stat().st_mtime)
        except Exception:
            pass
    return newest

def _slot_status(work_dir):
    """Build a live status object for one render slot (a work_* directory)."""
    ep_f = work_dir / "episode.json"
    if not ep_f.exists():
        return None
    try:
        ep = json.loads(ep_f.read_text(encoding="utf-8"))
    except Exception:
        return None
    shots = ep.get("shots", [])
    total = len(shots)
    prog_f = work_dir / "progress.json"
    # typed state wrapper (core/state.py) instead of a raw dict read
    from core.state import RenderProgress
    slot_name = work_dir.name[5:] if work_dir.name.startswith("work_") else ""
    _c = RenderProgress.load(slot_name).counts()
    key_done, vid_done, failed = _c["key_done"], _c["vid_done"], _c["failed"]
    # newest activity across progress + rendered shot files
    shots_dir = work_dir / "shots"
    newest = _newest_mtime(prog_f)
    try:
        for f in shots_dir.glob("*.mp4"):
            newest = max(newest, f.stat().st_mtime)
    except Exception:
        pass
    age = (time.time() - newest) if newest else None
    slot = work_dir.name.replace("work_", "") if work_dir.name != "work" else ""
    name = ep.get("name") or ep.get("title") or (f"Bernie_{slot}" if slot else "Bernie_Ep1")
    out_mp4 = config.OUT / f"{name}.mp4"
    # phase
    if out_mp4.exists():
        phase = "done"
    elif vid_done >= total and total:
        phase = "assembling"
    elif key_done < total:
        phase = "keyframes"
    else:
        phase = "video"
    return {
        "slot": slot or "(pilot)",
        "name": name,
        "title": ep.get("title", name),
        "total": total,
        "key_done": key_done,
        "vid_done": vid_done,
        "failed": failed,
        "frac": round(vid_done / total, 3) if total else 0.0,
        "phase": phase,
        "active": age is not None and age < ACTIVE_WINDOW and not out_mp4.exists(),
        "idle_secs": round(age) if age is not None else None,
        "final_exists": out_mp4.exists(),
    }

def _all_slots():
    out = []
    try:
        for d in sorted(config.STORAGE.glob("work*")):
            if d.is_dir():
                s = _slot_status(d)
                if s:
                    out.append(s)
    except Exception:
        pass
    return out

def _safe_slot(slot):
    """Reject path-traversal in a slot label; '' means the default (pilot) work dir."""
    s = (slot or "").strip()
    if s == "(pilot)" or ".." in s or "/" in s or "\\" in s or ":" in s:
        return ""
    return s

def _work_for_slot(slot):
    """Map a slot label back to its work directory (traversal-safe)."""
    s = _safe_slot(slot)
    return config.STORAGE / "work" if not s else config.STORAGE / f"work_{s}"

def shots_detail(slot):
    """Per-shot grid for the Render Monitor: status + which assets exist."""
    work = _work_for_slot(slot)
    ep_f = work / "episode.json"
    if not ep_f.exists():
        return {"slot": slot, "shots": []}
    try:
        ep = json.loads(ep_f.read_text(encoding="utf-8"))
    except Exception:
        return {"slot": slot, "shots": []}
    prog = {}
    pf = work / "progress.json"
    if pf.exists():
        try:
            prog = json.loads(pf.read_text(encoding="utf-8"))
        except Exception:
            prog = {}
    ps = prog.get("shots", {})
    shots_dir = work / "shots"
    out = []
    for s in ep.get("shots", []):
        sid = s.get("id")
        st = ps.get(sid, {})
        has_key = (shots_dir / f"{sid}_key.png").exists()
        has_clip = (shots_dir / f"{sid}.mp4").exists()
        status = st.get("status") or ("key" if has_key else None) or st.get("key") or "pending"
        out.append({"id": sid, "key": has_key, "clip": has_clip, "status": status,
                    "secs": st.get("secs"),
                    "desc": (s.get("action") or s.get("desc") or s.get("location") or "")[:90]})
    return {"slot": slot, "shots": out}

def thumb_path(slot, sid):
    safe = "".join(c for c in (sid or "") if c.isalnum() or c in "_-")
    f = _work_for_slot(slot) / "shots" / f"{safe}_key.png"
    return f if f.exists() else None

def _read_work_json(slot, name):
    f = _work_for_slot(slot) / name
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None

def read_report(slot):
    """Writers'-room reports (calibrated director writes director_report.json with before/after diffs)."""
    return {"director": _read_work_json(slot, "director_report.json"),
            "agency": _read_work_json(slot, "agency_report.json")}

def read_visual(slot):
    """Visual-QC report (per-shot score/onmodel/scary/issue) written by director_visual."""
    return _read_work_json(slot, "visual_report.json") or {}

def read_events_api(slot, since):
    try:
        from core import events
        return {"events": events.read_events(slot, since=int(since or 0))}
    except Exception as e:
        return {"events": [], "error": str(e)}

def run_doctor():
    try:
        import doctor
        return doctor.run(fix=False)
    except Exception as e:
        return {"ok": False, "checks": [], "error": str(e)}

def action_reroll(body):
    """Re-render one weak shot on the GPU (detached). Resumable; updates progress.json."""
    slot = (body.get("slot") or "").strip()
    sid = "".join(c for c in (body.get("id") or "") if c.isalnum() or c in "_-")
    if not sid:
        return {"ok": False, "error": "no shot id"}
    code = (f"import sys,pathlib;sys.path.insert(0,r'{HERE}');"
            f"import director_revise as d;d.revise(['{sid}'])")
    extra = {}
    if slot and slot != "(pilot)":
        extra["BERNIE_SLOT"] = slot
    if body.get("name"):
        extra["BERNIE_EP"] = body["name"]
    pid = _launch([_python(), "-c", code], extra, f"reroll_{slot}_{sid}")
    return {"ok": True, "pid": pid, "shot": sid}

def _library():
    lib = []
    try:
        for f in sorted(config.OUT.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
            lib.append({"name": f.stem, "file": str(f),
                        "size_mb": round(f.stat().st_size / 1e6, 1),
                        "mtime": f.stat().st_mtime})
    except Exception:
        pass
    return lib

def _season():
    try:
        import series
        from core.state import SeriesState
        done = set(SeriesState.load().done)
        plan = []
        for ep in series.SEASON:
            final = (config.OUT / f"{ep['name']}.mp4").exists()
            plan.append({"n": ep["n"], "slug": ep["slug"], "name": ep["name"],
                         "title": ep["title"], "scenes": ep["scenes"],
                         "premise": ep["premise"],
                         "done": final or ep["slug"] in done})
        nxt = next((e for e in plan if not e["done"]), None)
        return {"plan": plan, "next": nxt}
    except Exception as e:
        return {"plan": [], "next": None, "error": str(e)}

def _load_jobs():
    if JOBS.exists():
        try:
            return json.loads(JOBS.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"jobs": []}

def _save_jobs(j):
    try:
        JOBS.write_text(json.dumps(j, indent=2), encoding="utf-8")
    except Exception:
        pass

def _active_jobs():
    j = _load_jobs()
    for job in j["jobs"]:
        job["alive"] = _pid_alive(job.get("pid"))
    return j["jobs"]


# ----------------------------------------------------------------------------- actions
def _python():
    """The interpreter to launch renders with (prefer the bundled engine python)."""
    if config.PY_EMBED.exists():
        return str(config.PY_EMBED)
    return sys.executable

def _launch(cmd, env_extra, label):
    env = {**os.environ, "PYTHONUTF8": "1", **env_extra}
    log = open(config.LOGDIR / f"gui_{label}.log", "a", encoding="utf-8")
    log.write(f"\n=== launch {label} @ {time.strftime('%Y-%m-%d %H:%M:%S')} :: {' '.join(cmd)} ===\n")
    log.flush()
    kw = dict(cwd=str(REPO), env=env, stdout=log, stderr=subprocess.STDOUT)
    if os.name == "nt":
        kw["creationflags"] = DETACH
    else:
        kw["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kw)
    j = _load_jobs()
    j["jobs"] = [x for x in j["jobs"] if _pid_alive(x.get("pid"))][-20:]
    j["jobs"].append({"label": label, "pid": proc.pid, "cmd": cmd, "t": time.time()})
    _save_jobs(j)
    return proc.pid

def action_create(body):
    name   = (body.get("name") or "Bernie_EpX").strip().replace(" ", "_")
    slot   = (body.get("slot") or name.lower().replace("bernie_", "")).strip()
    prem   = (body.get("premise") or "").strip()
    scenes = int(body.get("scenes") or 14)
    target = int(body.get("target") or 86)
    cycles = int(body.get("cycles") or 2)
    cmd = [_python(), str(REPO / "make.py"), "--slot", slot, "--name", name,
           "--scenes", str(scenes), "--target", str(target), "--cycles", str(cycles)]
    if prem:
        cmd += ["--generate", prem]
    extra = {"BERNIE_SLOT": slot, "BERNIE_EP": name}
    if body.get("tier"):
        extra["BERNIE_TIER"] = str(body["tier"])
    pid = _launch(cmd, extra, f"create_{slot}")
    return {"ok": True, "pid": pid, "slot": slot, "name": name}

def action_series(body):
    cmd = [_python(), str(REPO / "make.py"), "--series"]
    if body.get("max"):
        cmd += ["--max", str(int(body["max"]))]
    pid = _launch(cmd, {}, "series")
    return {"ok": True, "pid": pid}

def action_install(_body):
    if os.name != "nt":
        return {"ok": False, "error": "setup.ps1 is Windows-only"}
    log = open(config.LOGDIR / "gui_install.log", "a", encoding="utf-8")
    log.write(f"\n=== install @ {time.strftime('%H:%M:%S')} ===\n"); log.flush()
    proc = subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(REPO / "setup.ps1")],
        cwd=str(REPO), stdout=log, stderr=subprocess.STDOUT, creationflags=DETACH)
    return {"ok": True, "pid": proc.pid, "log": "gui_install"}

def action_stop(_body):
    killed = []
    for job in _load_jobs()["jobs"]:
        if _pid_alive(job.get("pid")):
            try:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(job["pid"])],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    os.kill(int(job["pid"]), 9)
                killed.append(job["pid"])
            except Exception:
                pass
    return {"ok": True, "killed": killed}

def write_settings(body):
    """Persist keys + tier to keys.env (gitignored). Never echoes secrets back."""
    keys_f = REPO / "keys.env"
    cur = {}
    if keys_f.exists():
        for line in keys_f.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1); cur[k.strip()] = v.strip()
    def _clean(v):   # one value per line: no CR/LF can forge another key=value pair
        return str(v).replace("\r", "").replace("\n", "").strip()
    for k in ("HF_TOKEN", "CEREBRAS_API_KEY", "GROQ_API_KEY", "MISTRAL_API_KEY"):
        v = body.get(k)
        if v is not None and _clean(v) and not str(v).startswith("****"):
            cur[k] = _clean(v)
    if body.get("BERNIE_TIER"):
        cur["BERNIE_TIER"] = _clean(body["BERNIE_TIER"])
    if body.get("BERNIE_HOME"):
        cur["BERNIE_HOME"] = _clean(body["BERNIE_HOME"])
    lines = [f"{k}={v}" for k, v in cur.items()]
    keys_f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"ok": True, "saved": list(cur.keys())}

def read_settings():
    def mask(v):
        return ("****" + v[-4:]) if v and len(v) > 6 else ("set" if v else "")
    return {
        "vendor": config.GPU_VENDOR, "tier": config.TIER, "vram_gb": round(config.VRAM_GB, 1),
        "ram_gb": round(config.RAM_GB, 1), "home": str(config.HOME), "storage": str(config.STORAGE),
        "wan": f"{config.WAN_W}x{config.WAN_H}", "wan_model": config.WAN_MODEL,
        "fps": config.FPS, "llm_chain": config.LLM_CHAIN, "local_llm": config.LOCAL_LLM_MODEL,
        "summary": config.summary(),
        "keys": {
            "HF_TOKEN": mask(os.environ.get("HF_TOKEN", "")),
            "CEREBRAS_API_KEY": mask(os.environ.get("CEREBRAS_API_KEY", "")),
            "GROQ_API_KEY": mask(os.environ.get("GROQ_API_KEY", "")),
            "MISTRAL_API_KEY": mask(os.environ.get("MISTRAL_API_KEY", "")),
        },
        "installed": (config.HOME / ".installed").exists(),
    }

def tail_log(name, n=160):
    safe = "".join(c for c in (name or "") if c.isalnum() or c in "_-")
    f = config.LOGDIR / f"{safe}.log"
    if not f.exists():
        # also try a couple of well-known logs at HOME root
        alt = config.HOME / f"{safe}.log"
        f = alt if alt.exists() else f
    if not f.exists():
        return {"name": safe, "lines": [], "missing": True}
    try:
        data = f.read_text(encoding="utf-8", errors="replace").splitlines()
        return {"name": safe, "lines": data[-int(n):]}
    except Exception as e:
        return {"name": safe, "lines": [f"<error reading log: {e}>"]}

def list_logs():
    out = []
    try:
        for f in sorted(config.LOGDIR.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True):
            out.append(f.stem)
    except Exception:
        pass
    return out[:40]


def status():
    return {
        "ts": time.time(),
        "system": {
            "vendor": config.GPU_VENDOR,
            "backend": "CUDA" if config.IS_NVIDIA else ("DirectML" if config.GPU_VENDOR in ("amd", "intel") else "CPU"),
            "tier": config.TIER,
            "vram_gb": round(config.VRAM_GB, 1),
            "ram_gb": round(config.RAM_GB, 1),
            "cpu_count": os.cpu_count(),
            "gpu": _gpu_live(),
            "disk": _disk(config.STORAGE),
            "comfy_up": _comfy_up(),
            "wan": f"{config.WAN_W}x{config.WAN_H}",
            "installed": (config.HOME / ".installed").exists(),
        },
        "summary": config.summary(),
        "slots": _all_slots(),
        "library": _library(),
        "season": _season(),
        "jobs": _active_jobs(),
        "logs": list_logs(),
    }


# ----------------------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, payload, ctype="application/json"):
        if ctype == "application/json":
            body = json.dumps(payload).encode("utf-8")
        else:
            body = payload if isinstance(payload, bytes) else payload.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path in ("/", "/index.html"):
                html = (WEBDIR / "index.html").read_text(encoding="utf-8")
                return self._send(200, html, "text/html; charset=utf-8")
            if u.path == "/api/status":
                return self._send(200, status())
            if u.path == "/api/season":
                return self._send(200, _season())
            if u.path == "/api/settings":
                return self._send(200, read_settings())
            if u.path == "/api/logs":
                return self._send(200, tail_log(q.get("name", ["comfy_server"])[0],
                                                int(q.get("n", ["160"])[0])))
            if u.path == "/api/library":
                return self._send(200, {"library": _library()})
            if u.path == "/api/shots":
                return self._send(200, shots_detail(q.get("slot", [""])[0]))
            if u.path == "/api/thumb":
                f = thumb_path(q.get("slot", [""])[0], q.get("id", [""])[0])
                if f:
                    return self._send(200, f.read_bytes(), "image/png")
                return self._send(404, {"error": "no thumbnail"})
            if u.path == "/api/events":
                return self._send(200, read_events_api(q.get("slot", [""])[0], q.get("since", ["0"])[0]))
            if u.path == "/api/report":
                return self._send(200, read_report(q.get("slot", [""])[0]))
            if u.path == "/api/visual":
                return self._send(200, read_visual(q.get("slot", [""])[0]))
            if u.path == "/api/doctor":
                return self._send(200, run_doctor())
            return self._send(404, {"error": "not found"})
        except Exception as e:
            return self._send(500, {"error": str(e)})

    def do_POST(self):
        u = urlparse(self.path)
        try:
            ln = int(self.headers.get("Content-Length", "0") or 0)
            body = json.loads(self.rfile.read(ln) or b"{}") if ln else {}
        except Exception:
            body = {}
        try:
            if u.path == "/api/create":
                return self._send(200, action_create(body))
            if u.path == "/api/series":
                return self._send(200, action_series(body))
            if u.path == "/api/install":
                return self._send(200, action_install(body))
            if u.path == "/api/stop":
                return self._send(200, action_stop(body))
            if u.path == "/api/settings":
                return self._send(200, write_settings(body))
            if u.path == "/api/reroll":
                return self._send(200, action_reroll(body))
            return self._send(404, {"error": "not found"})
        except Exception as e:
            return self._send(500, {"error": str(e)})


def serve(port=8787, open_browser=True):
    WEBDIR.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Bernie Studio GUI  ->  {url}")
    print(config.summary())
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nGUI stopped.")


if __name__ == "__main__":
    p = 8787
    for a in sys.argv[1:]:
        if a.startswith("--port"):
            p = int(a.split("=")[-1]) if "=" in a else p
    serve(port=p, open_browser=("--no-browser" not in sys.argv))
