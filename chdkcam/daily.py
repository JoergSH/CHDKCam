#!/usr/bin/env python3
"""Tagesvideos: erstellt fuer jede Position und jeden abgeschlossenen Tag ein Zeitraffer-Video.

Laeuft per Timer stuendlich, rendert aber nur bei ausgeschaltetem Licht (CPU-Last).
Aufruf: python3 daily.py [--force]   (--force: auch bei Licht an)
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402
import render  # noqa: E402


def day_name(pid, day):
    return "tag_%s_%s.mp4" % (pid, day)


def finished_days(c, pid, now):
    """Tage mit Bildern, die abgeschlossen sind (vor heute, oder heute nach Lichtende)."""
    base = os.path.join(core.IMAGES, pid)
    if not os.path.isdir(base):
        return []
    today = now.strftime("%Y-%m-%d")
    s, e = core.light_window(c)
    today_done = e < 1440 and s < e and now.hour * 60 + now.minute >= e
    days = []
    for d in sorted(os.listdir(base)):
        if not render.DAY_RE.match(d):
            continue
        if d < today or (d == today and today_done):
            days.append(d)
    return days


def run(force=False):
    c = core.load_cfg()
    if not c.get("day_video"):
        return 0
    now = datetime.datetime.now()
    if core.light_on(c, now) and not force:
        return 0
    made = 0
    for p in c["positions"]:
        for day in finished_days(c, p["id"], now):
            out = os.path.join(core.VIDEOS, day_name(p["id"], day))
            if os.path.exists(out):
                archive(c, p["id"], day, out)
                continue
            files = render.collect(core.image_dirs(c), p["id"], day, day)
            if len(files) < 2:
                continue
            try:
                render.render(files, out, fps=c["day_fps"], width=c["day_width"],
                              overlay=c["overlay"])
                core.log(core.CAP_LOG, "Tagesvideo %s (%d Bilder)" % (os.path.basename(out),
                                                                     len(files)))
                made += 1
            except Exception as e:  # noqa: BLE001
                core.log_error("Tagesvideo %s/%s: %s" % (p["id"], day, e))
                continue
            archive(c, p["id"], day, out)
    return made


def archive(c, pid, day, video):
    """Tag sichern, wenn Archiv aktiv und lokal noch Bilder liegen (erst nach fertigem Video)."""
    if not c.get("archive") or not os.path.isfile(video):
        return
    if not os.path.isdir(os.path.join(core.IMAGES, pid, day)):
        return
    marker = os.path.join(core.IMAGES, pid, day, ".archived")
    if os.path.exists(marker) and not c.get("archive_delete"):
        return
    try:
        n = core.archive_day(pid, day, video, c)
        if os.path.isdir(os.path.dirname(marker)):
            open(marker, "w").close()
        core.log(core.CAP_LOG, "Archiv: %s/%s gesichert (%d Dateien)%s" % (
            pid, day, n, ", lokal geloescht" if c.get("archive_delete") else ""))
    except Exception as e:  # noqa: BLE001
        core.log_error("Archiv %s/%s: %s" % (pid, day, e))


if __name__ == "__main__":
    core.ensure_dirs()
    run(force="--force" in sys.argv)
