"""Minimal ComfyUI HTTP API client: start server, queue a workflow graph, wait, collect outputs."""
import json, time, urllib.request, urllib.error, subprocess, pathlib, uuid, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config

CLIENT_ID = uuid.uuid4().hex

def _post(path, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(config.COMFY_URL + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def _get(path):
    with urllib.request.urlopen(config.COMFY_URL + path, timeout=30) as r:
        return json.loads(r.read())

def server_up():
    try:
        _get("/system_stats"); return True
    except Exception:
        return False

def start_server(timeout=600):
    if server_up():
        print("  comfy already up"); return None
    main = config.ENGINE / "main.py"
    log = open(config.LOGDIR / "comfy_server.log", "w")
    proc = subprocess.Popen(
        [str(config.PY_EMBED), str(main), "--listen", "127.0.0.1", "--port", "8188",
         "--output-directory", str(config.COMFY_OUTPUT)],
        cwd=str(config.ENGINE), stdout=log, stderr=subprocess.STDOUT)
    t0 = time.time()
    while time.time() - t0 < timeout:
        if server_up():
            print(f"  comfy server up in {time.time()-t0:.0f}s"); return proc
        time.sleep(3)
    raise RuntimeError("ComfyUI server did not start in time (see logs/comfy_server.log)")

def queue(workflow):
    r = _post("/prompt", {"prompt": workflow, "client_id": CLIENT_ID})
    return r["prompt_id"]

def wait(prompt_id, timeout=1800, poll=2):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            hist = _get(f"/history/{prompt_id}")
        except Exception:
            time.sleep(poll); continue
        if prompt_id in hist:
            h = hist[prompt_id]
            status = h.get("status", {})
            if status.get("status_str") == "error" or status.get("completed") is False and "error" in json.dumps(status):
                raise RuntimeError(f"workflow error: {json.dumps(status)[:500]}")
            return h
        time.sleep(poll)
    raise TimeoutError(f"prompt {prompt_id} timed out after {timeout}s")

def collect_images(history):
    """Return list of saved file paths (images + audio, in node output order)."""
    files = []
    outdir = config.COMFY_OUTPUT
    for node_id, node_out in history.get("outputs", {}).items():
        for key in ("images", "audio", "gifs"):
            for item in node_out.get(key, []):
                sub = item.get("subfolder", "")
                files.append(outdir / sub / item["filename"])
    return files

def run(workflow, timeout=1800):
    pid = queue(workflow)
    hist = wait(pid, timeout=timeout)
    return collect_images(hist)
