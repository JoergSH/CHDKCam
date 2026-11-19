#!/usr/bin/env python3
"""CHDKCam - Zeitraffer mit einer Canon-Kamera unter CHDK (z. B. PowerShot SX20).

Steuert die Kamera ueber chdkptp: pro Aufnahme-Runde werden mehrere
"Positionen" (Zoom, Fokus, Belichtung) nacheinander angefahren und je ein
Bild direkt auf den Rechner uebertragen (remoteshoot, nichts auf der SD-Karte).

Aufruf:
  python3 core.py capture [--scheduled] [--pos ID]   Aufnahme-Runde
  python3 core.py camera                              Kamera-Status abfragen
  python3 core.py info                                Konfiguration/Pfade
Umgebung: CHDKCAM_DATA (Standard ~/chdkcam)
"""
import datetime
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

DATA = os.path.expanduser(os.environ.get("CHDKCAM_DATA", "~/chdkcam"))
CFG_FILE = os.path.join(DATA, "config.json")
STATUS_FILE = os.path.join(DATA, "status.json")
ERR_LOG = os.path.join(DATA, "error.log")
CAP_LOG = os.path.join(DATA, "capture.log")
LOCK_FILE = os.path.join(DATA, ".camlock")
IMAGES = os.path.join(DATA, "images")
THUMBS = os.path.join(DATA, "thumbs")
LATEST = os.path.join(DATA, "latest")
VIDEOS = os.path.join(DATA, "videos")
PREVIEW = os.path.join(DATA, "preview")
THUMB_W = 480
ZOOM_MAX = 128          # SX20: 129 Stufen (0..128); wird beim Kamera-Check aktualisiert
FLASH_MODES = {"auto": 0, "on": 1, "off": 2}   # propcase FLASH_MODE
# propcase WB_MODE (an der SX20 ermittelt)
WB_MODES = {"auto": 0, "day": 1, "cloudy": 2, "tungsten": 3, "fluor": 4, "fluor_h": 5,
            "custom": 7}
ID_RE = re.compile(r"^[a-z0-9_-]{1,24}$")

DEFAULT_CFG = {
    "title": "CHDKCam",    # Name in der Weboberflaeche / im Browser-Tab
    "interval_min": 10,
    "light_start": 4,      # Stunde, ab der fotografiert wird
    "light_end": 24,       # Stunde, bis zu der fotografiert wird (24 = Mitternacht)
    "chdkptp": "~/chdkptp/chdkptp-run.sh",
    "settle_ms": 2500,     # Wartezeit nach dem Zoomen
    "shot_pause_ms": 4000,  # Pause nach dem Ausloesen (SX20 stuerzt sonst beim Zoomen ab)
    "after": "stay",       # stay | home (Zoom 0) | play (Objektiv einfahren)
    "retries": 1,
    "day_video": True,     # Tagesvideos automatisch erstellen (wenn das Licht aus ist)
    "day_fps": 24,
    "day_width": 1920,
    "positions": [
        {"id": "weit", "name": "Übersicht", "zoom": 0, "focus_mm": 0,
         "tv": "", "iso": 0, "flash": "camera", "wb": "camera", "enabled": True},
        {"id": "bluete", "name": "Blüte", "zoom": 60, "focus_mm": 0,
         "tv": "", "iso": 0, "flash": "camera", "wb": "camera", "enabled": True},
    ],
}


# ------------------------------------------------------------ Hilfsfunktionen
def ensure_dirs():
    for d in (DATA, IMAGES, THUMBS, LATEST, VIDEOS, PREVIEW):
        os.makedirs(d, exist_ok=True)


def write_json_atomic(path, data):
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def read_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def log(path, msg):
    ensure_dirs()
    line = "%s %s\n" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    with open(path, "a") as f:
        f.write(line)
    # Log klein halten
    try:
        if os.path.getsize(path) > 512 * 1024:
            with open(path) as f:
                lines = f.readlines()[-2000:]
            with open(path, "w") as f:
                f.writelines(lines)
    except OSError:
        pass


def log_error(msg):
    log(ERR_LOG, msg)


# ------------------------------------------------------------ Konfiguration
def _clamp(v, lo, hi, typ=int, default=None):
    try:
        v = typ(v)
    except (TypeError, ValueError):
        return default if default is not None else lo
    return max(lo, min(hi, v))


TV_RE = re.compile(r"^(\d+(\.\d+)?|1/\d+(\.\d+)?)$")


def validate_position(p, idx):
    pid = str(p.get("id") or "pos%d" % (idx + 1)).strip().lower()
    pid = re.sub(r"[^a-z0-9_-]", "_", pid)[:24] or "pos%d" % (idx + 1)
    fl = p.get("flash", "camera")
    if fl not in FLASH_MODES:
        fl = "camera"
    wb = p.get("wb", "camera")
    if wb not in WB_MODES:
        wb = "camera"
    tv = str(p.get("tv") or "").strip()
    if tv and not TV_RE.match(tv):
        tv = ""
    return {
        "id": pid,
        "name": str(p.get("name") or pid)[:40],
        "zoom": _clamp(p.get("zoom", 0), 0, ZOOM_MAX),
        "focus_mm": _clamp(p.get("focus_mm", 0), 0, 100000),
        "tv": tv,
        "iso": _clamp(p.get("iso", 0), 0, 3200),
        "flash": fl,
        "wb": wb,
        "enabled": bool(p.get("enabled", True)),
    }


def validate_cfg(new):
    c = dict(DEFAULT_CFG)
    c["title"] = (str(new.get("title") or "").strip() or "CHDKCam")[:40]
    c["interval_min"] = _clamp(new.get("interval_min", c["interval_min"]), 1, 1440)
    c["light_start"] = _clamp(new.get("light_start", c["light_start"]), 0, 23)
    c["light_end"] = _clamp(new.get("light_end", c["light_end"]), 1, 24)
    c["chdkptp"] = str(new.get("chdkptp") or c["chdkptp"])
    c["settle_ms"] = _clamp(new.get("settle_ms", c["settle_ms"]), 0, 20000)
    c["shot_pause_ms"] = _clamp(new.get("shot_pause_ms", c["shot_pause_ms"]), 0, 30000)
    after = new.get("after", c["after"])
    c["after"] = after if after in ("stay", "home", "play") else "stay"
    c["retries"] = _clamp(new.get("retries", c["retries"]), 0, 3)
    c["day_video"] = bool(new.get("day_video", c["day_video"]))
    c["day_fps"] = _clamp(new.get("day_fps", c["day_fps"]), 1, 60)
    c["day_width"] = _clamp(new.get("day_width", c["day_width"]), 320, 4000)
    pos = new.get("positions", c["positions"])
    if not isinstance(pos, list):
        pos = c["positions"]
    out, seen = [], set()
    for i, p in enumerate(pos[:8]):
        if not isinstance(p, dict):
            continue
        vp = validate_position(p, i)
        while vp["id"] in seen:
            vp["id"] = (vp["id"] + "_")[:24]
        seen.add(vp["id"])
        out.append(vp)
    c["positions"] = out
    return c


def load_cfg():
    return validate_cfg(read_json(CFG_FILE, DEFAULT_CFG))


def save_cfg(c):
    ensure_dirs()
    c = validate_cfg(c)
    write_json_atomic(CFG_FILE, c)
    return c


# ------------------------------------------------------------ Zeitplan
def light_on(c, now=None):
    now = now or datetime.datetime.now()
    s, e = c["light_start"], c["light_end"]
    h = now.hour
    if s < e:
        return s <= h < e
    return h >= s or h < e      # ueber Mitternacht


def due(c, now=None):
    now = now or datetime.datetime.now()
    if not light_on(c, now):
        return False
    minutes = now.hour * 60 + now.minute - c["light_start"] * 60
    return minutes % c["interval_min"] == 0


# ------------------------------------------------------------ Sperre
class CamLock:
    """Verhindert, dass zwei Prozesse gleichzeitig mit der Kamera sprechen."""

    def __init__(self, timeout=120):
        self.timeout = timeout
        self.f = None

    def __enter__(self):
        ensure_dirs()
        self.f = open(LOCK_FILE, "w")
        end = time.time() + self.timeout
        while True:
            try:
                fcntl.flock(self.f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if time.time() > end:
                    self.f.close()
                    raise TimeoutError("Kamera ist belegt")
                time.sleep(0.5)

    def __exit__(self, *a):
        try:
            fcntl.flock(self.f, fcntl.LOCK_UN)
        finally:
            self.f.close()


# ------------------------------------------------------------ chdkptp
def chdkptp_cmd(c):
    return os.path.expanduser(c["chdkptp"])


def run_chdkptp(c, cmds, timeout=180):
    """Fuehrt eine Folge von chdkptp-Befehlen in einer Verbindung aus."""
    args = [chdkptp_cmd(c), "-c"]
    for cmd in cmds:
        args.append("-e" + cmd)
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise RuntimeError("chdkptp nicht gefunden: %s" % args[0])
    except subprocess.TimeoutExpired:
        raise RuntimeError("chdkptp Zeitueberschreitung")
    out = (p.stdout or "") + (p.stderr or "")
    return out


ENSURE_REC = ("luar if not get_mode() then switch_mode_usb(1) "
              "local i=0 while not get_mode() and i<60 do sleep(100) i=i+1 end "
              "sleep(1000) end return get_mode()")


def _returns(out):
    """Liest 'N:return:WERT'-Zeilen aus der chdkptp-Ausgabe."""
    vals = []
    for line in out.splitlines():
        m = re.match(r"^\d+:return:(.*)$", line.strip())
        if m:
            vals.append(m.group(1).strip("'\""))
    return vals


def _errors(out):
    return [l.strip() for l in out.splitlines()
            if l.strip().startswith("ERROR") and "already in rec" not in l]


def rs_args(p):
    a = ""
    if p.get("focus_mm"):
        a += " -sd=%dmm" % p["focus_mm"]
    if p.get("tv"):
        a += " -tv=%s" % p["tv"]
    if p.get("iso"):
        a += " -svm=%d" % p["iso"]
    return a


def camera_status(c=None):
    c = c or load_cfg()
    with CamLock(timeout=60):
        out = run_chdkptp(c, [
            "luar return get_mode(), get_zoom(), get_zoom_steps(), get_vbatt(), "
            "get_buildinfo().build_number, get_buildinfo().platform"], timeout=40)
    vals = _returns(out)
    if len(vals) < 6:
        errs = _errors(out)
        return {"connected": False, "error": errs[0] if errs else out.strip()[-300:]}
    return {"connected": True, "rec": vals[0] == "true", "zoom": int(vals[1]),
            "zoom_steps": int(vals[2]), "vbatt_mv": int(vals[3]),
            "chdk": vals[4], "platform": vals[5]}


def _find_shot(base):
    """remoteshoot haengt manchmal eine Endung an, manchmal nicht."""
    for cand in (base, base + ".jpg", base + ".JPG"):
        if os.path.isfile(cand) and os.path.getsize(cand) > 1000:
            return cand
    return None


def make_thumb(src, dst, width=THUMB_W):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src,
                    "-vf", "scale=%d:-2" % width, "-q:v", "5", dst],
                   capture_output=True, timeout=60)
    return os.path.isfile(dst)


def _set_latest(pid, path):
    tmp = os.path.join(LATEST, ".%s.tmp" % pid)
    shutil.copyfile(path, tmp)
    os.replace(tmp, os.path.join(LATEST, pid + ".jpg"))


TV_STEPS = [15, 13, 10, 8, 6, 5, 4, 3.2, 2.5, 2, 1.6, 1.3, 1, 0.8, 0.6, 0.5, 0.4, 0.3,
            1/4, 1/5, 1/6, 1/8, 1/10, 1/13, 1/15, 1/20, 1/25, 1/30, 1/40, 1/50, 1/60, 1/80,
            1/100, 1/125, 1/160, 1/200, 1/250, 1/320, 1/400, 1/500, 1/640, 1/800, 1/1000,
            1/1250, 1/1600, 1/2000, 1/2500, 1/3200]
ISO_STEPS = [80, 100, 125, 160, 200, 250, 320, 400, 500, 640, 800, 1000, 1250, 1600]


def _nearest_log(v, steps):
    import math
    return min(steps, key=lambda s: abs(math.log(s) - math.log(v)))


def exif_exposure(path):
    """Liest Belichtungszeit (s) und ISO aus dem EXIF einer JPEG-Datei (ohne Zusatzpakete)."""
    import struct
    try:
        with open(path, "rb") as f:
            data = f.read(256 * 1024)
    except OSError:
        return {}
    i = data.find(b"Exif\x00\x00")
    if i < 0:
        return {}
    t = data[i + 6:]
    end = "<" if t[:2] == b"II" else ">"

    def u16(o):
        return struct.unpack(end + "H", t[o:o + 2])[0]

    def u32(o):
        return struct.unpack(end + "I", t[o:o + 4])[0]

    def entries(off):
        out = {}
        try:
            n = u16(off)
            for k in range(n):
                e = off + 2 + 12 * k
                out[u16(e)] = (u16(e + 2), u32(e + 4), e + 8)
        except struct.error:
            pass
        return out

    res = {}
    try:
        ifd0 = entries(u32(4))
        if 0x8769 not in ifd0:
            return {}
        ex = entries(ifd0[0x8769][2] and u32(ifd0[0x8769][2]))
        if 0x829A in ex:                      # ExposureTime (RATIONAL, bei manchen DOUBLE)
            typ, _, vo = ex[0x829A]
            o = u32(vo)
            if typ == 12:
                res["tv_s"] = struct.unpack(end + "d", t[o:o + 8])[0]
            else:
                num, den = u32(o), u32(o + 4)
                if den:
                    res["tv_s"] = num / den
        if 0x8827 in ex:                      # ISO, SHORT
            res["iso"] = u16(ex[0x8827][2])
    except struct.error:
        pass
    return res


def fmt_tv(tv):
    tv = _nearest_log(tv, TV_STEPS)
    return ("1/%d" % round(1 / tv)) if tv < 0.3 else ("%g" % tv)


def shot_info(out):
    """Fokus (mm), den die Kamera bei der letzten Aufnahme je Position genommen hat."""
    info = {}
    for v in _returns(out):
        if v.startswith("SHOT:"):
            try:
                _, pid, focus = v.split(":")
                info[pid] = {"focus_mm": int(focus)}
            except ValueError:
                pass
    return info


def shoot_positions(c, positions, dest_fn, timeout=None):
    """Faehrt die Positionen an und loest jeweils aus.
    dest_fn(p) liefert den Zielpfad ohne Endung. Gibt {id: pfad|None} und Ausgabe zurueck."""
    cmds = [ENSURE_REC]
    targets = {}
    settle = c["settle_ms"]
    for p in positions:
        base = dest_fn(p)
        os.makedirs(os.path.dirname(base), exist_ok=True)
        targets[p["id"]] = base
        cmds.append("luar set_zoom(%d) sleep(%d) return get_zoom()" % (p["zoom"], settle))
        props = []
        if p.get("flash") in FLASH_MODES:
            props.append("set_prop(pc.FLASH_MODE,%d)" % FLASH_MODES[p["flash"]])
        if p.get("wb") in WB_MODES:
            props.append("set_prop(pc.WB_MODE,%d)" % WB_MODES[p["wb"]])
        if props:
            cmds.append("luar local pc=require'propcase' %s sleep(500) return 1" % " ".join(props))
        cmds.append("rs %s -nosubst%s" % (base, rs_args(p)))
        # was hat die Kamera tatsaechlich genommen? (Fokus/Belichtung der letzten Aufnahme)
        cmds.append("luar return 'SHOT:%s:'..get_focus()" % p["id"])
        if c["shot_pause_ms"]:
            cmds.append("luar sleep(%d) return 1" % c["shot_pause_ms"])
    if c["after"] == "home":
        cmds.append("luar set_zoom(0) sleep(1500) return get_zoom()")
    elif c["after"] == "play":
        cmds.append("play")
    cmds.append("luar return get_vbatt()")
    out = run_chdkptp(c, cmds, timeout=timeout or 60 + 40 * len(positions))
    res = {pid: _find_shot(base) for pid, base in targets.items()}
    return res, out


def capture(c=None, only=None, lock_timeout=120):
    """Eine Aufnahme-Runde. Gibt Ergebnis-Dict zurueck."""
    c = c or load_cfg()
    ensure_dirs()
    positions = [p for p in c["positions"] if p["enabled"]]
    if only:
        positions = [p for p in c["positions"] if p["id"] == only]
    if not positions:
        return {"ok": False, "error": "keine Position aktiv"}
    now = datetime.datetime.now()
    day = now.strftime("%Y-%m-%d")
    stamp = now.strftime("%Y%m%d_%H%M%S")

    def dest(p):
        return os.path.join(IMAGES, p["id"], day, stamp)

    result = {"time": now.isoformat(timespec="seconds"), "shots": {}, "ok": False}
    todo = positions
    out = ""
    with CamLock(timeout=lock_timeout):
        for attempt in range(c["retries"] + 1):
            res, out = shoot_positions(c, todo, dest)
            for p in todo:
                path = res.get(p["id"])
                if path:
                    final = os.path.join(IMAGES, p["id"], day, stamp + ".jpg")
                    if path != final:
                        os.replace(path, final)
                    result["shots"][p["id"]] = final
            todo = [p for p in todo if p["id"] not in result["shots"]]
            if not todo:
                break
            time.sleep(5)
    vals = _returns(out)
    if vals:
        try:
            result["vbatt_mv"] = int(vals[-1])
        except ValueError:
            pass
    for pid, path in result["shots"].items():
        make_thumb(path, os.path.join(THUMBS, pid, day, stamp + ".jpg"))
        _set_latest(pid, path)
    result["missing"] = [p["id"] for p in todo]
    result["ok"] = not todo
    if todo:
        errs = _errors(out)
        result["error"] = "; ".join(errs[:3]) or "kein Bild erhalten"
        log_error("Aufnahme fehlgeschlagen (%s): %s" % (",".join(result["missing"]),
                                                       result["error"]))
    log(CAP_LOG, "Runde %s: %d/%d Bilder%s" % (
        stamp, len(result["shots"]), len(positions),
        (" U=%dmV" % result["vbatt_mv"]) if "vbatt_mv" in result else ""))
    st = read_json(STATUS_FILE, {})
    st["last"] = result
    if result["ok"]:
        st["last_ok"] = result["time"]
    write_json_atomic(STATUS_FILE, st)
    return result


def preview(p, c=None):
    """Probebild einer (evtl. ungespeicherten) Position - landet nicht in der Zeitreihe."""
    c = c or load_cfg()
    ensure_dirs()
    p = validate_position(p, 0)
    base = os.path.join(PREVIEW, "preview")
    for f in os.listdir(PREVIEW):
        try:
            os.remove(os.path.join(PREVIEW, f))
        except OSError:
            pass
    with CamLock(timeout=60):
        res, out = shoot_positions(dict(c, after="stay"), [p], lambda _p: base)
    path = res.get(p["id"])
    if not path:
        errs = _errors(out)
        raise RuntimeError("; ".join(errs[:3]) or "kein Bild erhalten")
    final = os.path.join(PREVIEW, "preview.jpg")
    if path != final:
        os.replace(path, final)
    make_thumb(final, os.path.join(PREVIEW, "preview_small.jpg"), width=1280)
    info = shot_info(out).get(p["id"], {})
    ex = exif_exposure(final)          # Belichtung steht zuverlaessig nur im EXIF
    if ex.get("tv_s"):
        info["tv"] = fmt_tv(ex["tv_s"])
    if ex.get("iso"):
        info["iso"] = _nearest_log(ex["iso"], ISO_STEPS)
    return final, info


def liveview(zoom=None, c=None):
    """Schnelles Sucherbild (niedrige Aufloesung) ohne Ausloesen."""
    c = c or load_cfg()
    ensure_dirs()
    ppm = os.path.join(PREVIEW, "live.ppm")
    jpg = os.path.join(PREVIEW, "live.jpg")
    cmds = [ENSURE_REC]
    if zoom is not None:
        cmds.append("luar set_zoom(%d) sleep(%d) return get_zoom()"
                    % (_clamp(zoom, 0, ZOOM_MAX), c["settle_ms"]))
    cmds.append("lvdumpimg -count=1 -quiet -nosubst -vp=%s" % ppm)
    with CamLock(timeout=60):
        out = run_chdkptp(c, cmds, timeout=60)
    if not os.path.isfile(ppm):
        errs = _errors(out)
        raise RuntimeError("; ".join(errs[:3]) or "kein Sucherbild")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", ppm, "-q:v", "3", jpg],
                   capture_output=True, timeout=30)
    os.remove(ppm)
    return jpg


# ------------------------------------------------------------ Aufraeumen
def clear_logs():
    for f in (ERR_LOG, CAP_LOG):
        try:
            os.remove(f)
        except OSError:
            pass


def clear_images():
    """Loescht alle Bilder, Miniaturen und Vorschauen (Videos und Einstellungen bleiben)."""
    with CamLock(timeout=120):
        for d in (IMAGES, THUMBS, LATEST, PREVIEW):
            shutil.rmtree(d, ignore_errors=True)
        ensure_dirs()
        st = read_json(STATUS_FILE, {})
        st.pop("last", None)
        st.pop("last_ok", None)
        write_json_atomic(STATUS_FILE, st)


# ------------------------------------------------------------ Kommandozeile
def main(argv):
    if len(argv) < 2 or argv[1] not in ("capture", "camera", "info"):
        print(__doc__)
        return 2
    ensure_dirs()
    if not os.path.isfile(CFG_FILE):
        save_cfg(DEFAULT_CFG)
    c = load_cfg()
    cmd = argv[1]
    if cmd == "info":
        print(json.dumps({"data": DATA, "config": c}, indent=2, ensure_ascii=False))
        return 0
    if cmd == "camera":
        print(json.dumps(camera_status(c), indent=2))
        return 0
    only = None
    if "--pos" in argv:
        only = argv[argv.index("--pos") + 1]
    if "--scheduled" in argv and not due(c):
        return 0
    try:
        r = capture(c, only=only)
    except Exception as e:  # noqa: BLE001
        log_error("Aufnahme: %s" % e)
        print("Fehler:", e)
        return 1
    print(json.dumps(r, indent=2))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
