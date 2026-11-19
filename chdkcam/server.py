#!/usr/bin/env python3
"""CHDKCam-Weboberflaeche (nur Python-Standardbibliothek).
Start: python3 server.py [port]   -> http://<ip>:8081
Umgebung: CHDKCAM_PORT (Standard 8081), CHDKCAM_BIND (Standard 0.0.0.0), CHDKCAM_DATA
"""
import datetime
import json
import os
import re
import shutil
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402
import render  # noqa: E402
import daily  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
IMG_RE = re.compile(r"^\d{8}_\d{6}\.jpg$")
VID_RE = re.compile(r"^[\w.-]+\.mp4$")
PREV_RE = re.compile(r"^(preview|preview_small|live)\.jpg$")

job_lock = threading.Lock()
job = {"state": "idle"}


def set_job(**kw):
    with job_lock:
        job.clear()
        job.update(kw)


def job_snapshot():
    with job_lock:
        return dict(job)


# ---------------------------------------------------------------- Daten
def list_days(pid):
    d = os.path.join(core.IMAGES, pid)
    if not os.path.isdir(d):
        return []
    out = []
    for day in sorted(os.listdir(d), reverse=True):
        if DAY_RE.match(day):
            n = len([f for f in os.listdir(os.path.join(d, day)) if IMG_RE.match(f)])
            out.append({"day": day, "count": n})
    return out


def list_images(pid, day):
    d = os.path.join(core.IMAGES, pid, day)
    if not os.path.isdir(d):
        return []
    return sorted(f for f in os.listdir(d) if IMG_RE.match(f))


def next_due(c):
    now = datetime.datetime.now().replace(second=0, microsecond=0)
    t = now + datetime.timedelta(minutes=1)
    for _ in range(60 * 48):
        if core.due(c, t):
            return t.isoformat(timespec="minutes")
        t += datetime.timedelta(minutes=1)
    return None


def latest_info(pid):
    p = os.path.join(core.LATEST, pid + ".jpg")
    if not os.path.isfile(p):
        return None
    return datetime.datetime.fromtimestamp(os.path.getmtime(p)).isoformat(timespec="seconds")


def status():
    c = core.load_cfg()
    st = core.read_json(core.STATUS_FILE, {})
    du = shutil.disk_usage(core.DATA)
    pos = []
    for p in c["positions"]:
        days = list_days(p["id"])
        pos.append(dict(p, latest=latest_info(p["id"]),
                        days=len(days), images=sum(d["count"] for d in days)))
    return {
        "now": datetime.datetime.now().isoformat(timespec="seconds"),
        "light_on": core.light_on(c),
        "next": next_due(c),
        "interval_min": c["interval_min"],
        "light_start": c["light_start"],
        "light_end": c["light_end"],
        "last": st.get("last"),
        "last_ok": st.get("last_ok"),
        "positions": pos,
        "disk_free_gb": round(du.free / 1e9, 1),
        "job": job_snapshot(),
    }


def tail(path, n=40):
    try:
        with open(path) as f:
            return f.readlines()[-n:]
    except OSError:
        return []


def list_videos():
    if not os.path.isdir(core.VIDEOS):
        return []
    out = []
    for f in sorted(os.listdir(core.VIDEOS), reverse=True):
        if VID_RE.match(f) and ".part." not in f:
            p = os.path.join(core.VIDEOS, f)
            out.append({"name": f, "mb": round(os.path.getsize(p) / 1e6, 1),
                        "time": datetime.datetime.fromtimestamp(
                            os.path.getmtime(p)).isoformat(timespec="minutes")})
    return out


# ---------------------------------------------------------------- Jobs
def run_capture(pid):
    set_job(state="running", kind="capture", started=time.time())
    try:
        r = core.capture(only=pid)
        set_job(state="done", kind="capture", result=r)
    except Exception as e:  # noqa: BLE001
        core.log_error("Aufnahme (Web): %s" % e)
        set_job(state="error", kind="capture", error=str(e))


def run_render(pid, day_from, day_to, fps, width):
    files = render.collect(core.IMAGES, pid, day_from, day_to)
    name = "%s_%s_bis_%s_%dfps.mp4" % (pid, day_from or "anfang", day_to or "heute", fps)
    out = os.path.join(core.VIDEOS, name)
    set_job(state="running", kind="render", total=len(files), frame=0, name=name)

    def prog(frame, total):
        set_job(state="running", kind="render", total=total, frame=frame, name=name)

    try:
        render.render(files, out, fps=fps, width=width, on_progress=prog)
        set_job(state="done", kind="render", name=name)
    except Exception as e:  # noqa: BLE001
        core.log_error("Video: %s" % e)
        set_job(state="error", kind="render", error=str(e))


DAILY_RE = re.compile(r"^tag_([a-z0-9_-]+)_(\d{4}-\d{2}-\d{2})\.mp4$")


def daily_videos(pid):
    out = []
    if os.path.isdir(core.VIDEOS):
        for f in sorted(os.listdir(core.VIDEOS)):
            m = DAILY_RE.match(f)
            if m and m.group(1) == pid:
                out.append({"day": m.group(2), "name": f})
    return out


def run_concat(pid, d1, d2):
    vids = [os.path.join(core.VIDEOS, v["name"]) for v in daily_videos(pid)
            if (not d1 or v["day"] >= d1) and (not d2 or v["day"] <= d2)]
    name = "%s_tage_%s_bis_%s.mp4" % (pid, d1 or "anfang", d2 or "heute")
    set_job(state="running", kind="render", name=name, frame=0, total=len(vids), phase="concat")
    try:
        render.concat(vids, os.path.join(core.VIDEOS, name))
        set_job(state="done", kind="render", name=name)
    except Exception as e:  # noqa: BLE001
        core.log_error("Zusammenfuegen: %s" % e)
        set_job(state="error", kind="render", error=str(e))


def run_daily():
    set_job(state="running", kind="render", name="Tagesvideos", frame=0, total=0)
    try:
        n = daily.run(force=True)
        set_job(state="done", kind="render", name="%d Tagesvideo(s)" % n)
    except Exception as e:  # noqa: BLE001
        core.log_error("Tagesvideos: %s" % e)
        set_job(state="error", kind="render", error=str(e))


def start_job(target, *args):
    if job_snapshot().get("state") == "running":
        return False
    set_job(state="running")
    threading.Thread(target=target, args=args, daemon=True).start()
    return True


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "CHDKCam"

    def log_message(self, *a):
        pass

    def send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, ctype, cache=False):
        if not os.path.isfile(path):
            return self.send_error(404)
        size = os.path.getsize(path)
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        if rng and rng.startswith("bytes="):
            a, _, b = rng[6:].partition("-")
            try:
                start = int(a) if a else max(0, size - int(b))
                end = int(b) if a and b else size - 1
            except ValueError:
                start, end = 0, size - 1
            self.send_response(206)
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "max-age=86400" if cache else "no-store")
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(65536, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                left -= len(chunk)

    def read_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > 100000:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode())
        except ValueError:
            return {}

    def valid_pid(self, pid):
        return pid in [p["id"] for p in core.load_cfg()["positions"]] or \
            (core.ID_RE.match(pid or "") and os.path.isdir(os.path.join(core.IMAGES, pid)))

    # ---- GET
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        parts = [p for p in u.path.split("/") if p]
        try:
            if u.path in ("/", "/index.html"):
                return self.send_file(os.path.join(STATIC, "index.html"),
                                      "text/html; charset=utf-8")
            if u.path == "/api/status":
                return self.send_json(status())
            if u.path == "/api/config":
                return self.send_json(core.load_cfg())
            if u.path == "/api/camera":
                try:
                    return self.send_json(core.camera_status())
                except Exception as e:  # noqa: BLE001
                    return self.send_json({"connected": False, "error": str(e)})
            if u.path == "/api/days":
                pid = q.get("pos", "")
                return self.send_json(list_days(pid) if self.valid_pid(pid) else [])
            if u.path == "/api/images":
                pid, day = q.get("pos", ""), q.get("day", "")
                if self.valid_pid(pid) and DAY_RE.match(day):
                    return self.send_json(list_images(pid, day))
                return self.send_json([])
            if u.path == "/api/daily_videos":
                pid = q.get("pos", "")
                return self.send_json(daily_videos(pid) if self.valid_pid(pid) else [])
            if u.path == "/api/videos":
                return self.send_json(list_videos())
            if u.path == "/api/log":
                return self.send_json({"error": tail(core.ERR_LOG),
                                       "capture": tail(core.CAP_LOG)})
            if len(parts) == 4 and parts[0] in ("img", "thumb"):
                _, pid, day, name = parts
                if core.ID_RE.match(pid) and DAY_RE.match(day) and IMG_RE.match(name):
                    base = core.IMAGES if parts[0] == "img" else core.THUMBS
                    path = os.path.join(base, pid, day, name)
                    if parts[0] == "thumb" and not os.path.isfile(path):
                        src = os.path.join(core.IMAGES, pid, day, name)
                        if os.path.isfile(src):
                            core.make_thumb(src, path)
                    return self.send_file(path, "image/jpeg", cache=True)
            if len(parts) == 2 and parts[0] == "latest":
                pid = parts[1][:-4] if parts[1].endswith(".jpg") else ""
                if core.ID_RE.match(pid):
                    return self.send_file(os.path.join(core.LATEST, pid + ".jpg"), "image/jpeg")
            if len(parts) == 2 and parts[0] == "preview" and PREV_RE.match(parts[1]):
                return self.send_file(os.path.join(core.PREVIEW, parts[1]), "image/jpeg")
            if len(parts) == 2 and parts[0] == "video" and VID_RE.match(parts[1]):
                return self.send_file(os.path.join(core.VIDEOS, parts[1]), "video/mp4")
        except (BrokenPipeError, ConnectionResetError):
            return
        self.send_error(404)

    # ---- POST
    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        body = self.read_body()
        if u.path == "/api/config":
            c = core.load_cfg()
            c.update({k: v for k, v in body.items() if k in core.DEFAULT_CFG})
            return self.send_json(core.save_cfg(c))
        if u.path == "/api/capture":
            pid = body.get("pos") or None
            if pid and not self.valid_pid(pid):
                return self.send_json({"ok": False, "error": "unbekannte Position"}, 400)
            ok = start_job(run_capture, pid)
            return self.send_json({"ok": ok, "error": None if ok else "laeuft bereits"})
        if u.path == "/api/preview":
            try:
                _, info = core.preview(body.get("position") or {})
                return self.send_json({"ok": True, "url": "/preview/preview_small.jpg",
                                       "full": "/preview/preview.jpg", "t": time.time(),
                                       "info": info})
            except Exception as e:  # noqa: BLE001
                return self.send_json({"ok": False, "error": str(e)})
        if u.path == "/api/live":
            try:
                core.liveview(body.get("zoom"))
                return self.send_json({"ok": True, "url": "/preview/live.jpg", "t": time.time()})
            except Exception as e:  # noqa: BLE001
                return self.send_json({"ok": False, "error": str(e)})
        if u.path == "/api/render":
            pid = body.get("pos", "")
            if not self.valid_pid(pid):
                return self.send_json({"ok": False, "error": "unbekannte Position"}, 400)
            d1 = body.get("from") or None
            d2 = body.get("to") or None
            if (d1 and not DAY_RE.match(d1)) or (d2 and not DAY_RE.match(d2)):
                return self.send_json({"ok": False, "error": "Datum ungueltig"}, 400)
            fps = core._clamp(body.get("fps", 24), 1, 60)
            width = core._clamp(body.get("width", 1920), 320, 4000)
            ok = start_job(run_render, pid, d1, d2, fps, width)
            return self.send_json({"ok": ok, "error": None if ok else "laeuft bereits"})
        if u.path == "/api/concat":
            pid = body.get("pos", "")
            d1, d2 = body.get("from") or None, body.get("to") or None
            if not self.valid_pid(pid) or (d1 and not DAY_RE.match(d1)) or (d2 and not DAY_RE.match(d2)):
                return self.send_json({"ok": False, "error": "ungueltige Angaben"}, 400)
            ok = start_job(run_concat, pid, d1, d2)
            return self.send_json({"ok": ok, "error": None if ok else "laeuft bereits"})
        if u.path == "/api/daily":
            ok = start_job(run_daily)
            return self.send_json({"ok": ok, "error": None if ok else "laeuft bereits"})
        if u.path == "/api/clear":
            what = body.get("what")
            try:
                if what == "logs":
                    core.clear_logs()
                elif what == "images":
                    if job_snapshot().get("state") == "running":
                        return self.send_json({"ok": False, "error": "es laeuft gerade ein Auftrag"})
                    core.clear_images()
                else:
                    return self.send_json({"ok": False, "error": "unbekannt"}, 400)
            except Exception as e:  # noqa: BLE001
                return self.send_json({"ok": False, "error": str(e)})
            return self.send_json({"ok": True})
        if u.path == "/api/video/delete":
            name = body.get("name", "")
            if VID_RE.match(name):
                try:
                    os.remove(os.path.join(core.VIDEOS, name))
                except OSError:
                    pass
            return self.send_json({"ok": True})
        self.send_error(404)


def main():
    core.ensure_dirs()
    if not os.path.isfile(core.CFG_FILE):
        core.save_cfg(core.DEFAULT_CFG)
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("CHDKCAM_PORT", 8081))
    bind = os.environ.get("CHDKCAM_BIND", "0.0.0.0")
    srv = ThreadingHTTPServer((bind, port), Handler)
    srv.daemon_threads = True
    print("CHDKCam laeuft auf http://%s:%d" % (bind, port), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
