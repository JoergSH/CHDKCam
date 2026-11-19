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
    today_done = c["light_end"] < 24 and c["light_start"] < c["light_end"] \
        and now.hour >= c["light_end"]
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
                continue
            files = render.collect(core.IMAGES, p["id"], day, day)
            if len(files) < 2:
                continue
            try:
                render.render(files, out, fps=c["day_fps"], width=c["day_width"])
                core.log(core.CAP_LOG, "Tagesvideo %s (%d Bilder)" % (os.path.basename(out),
                                                                     len(files)))
                made += 1
            except Exception as e:  # noqa: BLE001
                core.log_error("Tagesvideo %s/%s: %s" % (p["id"], day, e))
    return made


if __name__ == "__main__":
    core.ensure_dirs()
    run(force="--force" in sys.argv)
