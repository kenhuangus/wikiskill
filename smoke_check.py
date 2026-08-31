"""Live smoke test: boots the real wikiskill serve stack and exercises it over HTTP."""
import json
import shutil
import subprocess
import sys
import time
import urllib.request

PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"
ok = True

shutil.rmtree("smoke_run", ignore_errors=True)  # fresh workspace per invocation


def check(name, cond, extra=""):
    global ok
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {extra}")
    ok = ok and bool(cond)


def get(path, timeout=20):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8")


proc = subprocess.Popen(
    [sys.executable, "-m", "wikiskill.cli", "serve", "--host", "127.0.0.1",
     "--port", str(PORT)],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

try:
    # wait for server
    for _ in range(100):
        try:
            st, body = get("/api/health", timeout=5)
            break
        except Exception:
            time.sleep(0.3)
    else:
        raise RuntimeError("server did not start")

    check("health", st == 200 and '"ok":true' in body.replace(" ", ""))

    st, body = get("/")
    check("index served", st == 200 and 'WikiSkill' in body and 'run-form' in body)

    req = urllib.request.Request(BASE + "/api/run",
                                 data=json.dumps({"llm_backend": "mock",
                                                  "iterations": 2,
                                                  "workspace_root": "smoke_run"}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        st, body = r.status, r.read().decode()
    check("run started", st == 202 and '"run_id"' in body)

    done = False
    for _ in range(200):
        st, body = get("/api/status")
        state = json.loads(body)["state"]
        if state and state["status"] in ("done", "error"):
            done = state["status"] == "done"
            break
        time.sleep(0.2)
    check("run completed (mock, live server)", done)

    st, body = get("/api/workspace?root=smoke_run")
    data = json.loads(body)
    check("workspace browsable", st == 200 and "wiki/index.md" in data["files"],
          f"({sorted(data['files'])[:3]})")

    req = urllib.request.Request(BASE + "/api/evaluate",
                                 data=json.dumps({"llm_backend": "mock",
                                                  "workspace_root": "smoke_run"}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        ev = json.loads(r.read().decode())["evaluation"]
    check("evaluation end-to-end", ev["significant"] is True and
          ev["skilled_accuracy"] == 1.0,
          f"skilled={ev['skilled_accuracy']}")

finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()

print("SMOKE TEST", "PASSED" if ok else "FAILED")
sys.exit(0 if ok else 1)