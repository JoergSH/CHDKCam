"""Zeitraffer-Video aus den Bildern einer Position (ffmpeg)."""
import os
import re
import subprocess
import tempfile

IMG_RE = re.compile(r"^\d{8}_\d{6}\.jpg$")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def collect(images_dir, pid, day_from=None, day_to=None):
    base = os.path.join(images_dir, pid)
    if not os.path.isdir(base):
        return []
    files = []
    for day in sorted(os.listdir(base)):
        if not DAY_RE.match(day):
            continue
        if day_from and day < day_from:
            continue
        if day_to and day > day_to:
            continue
        d = os.path.join(base, day)
        files += [os.path.join(d, f) for f in sorted(os.listdir(d)) if IMG_RE.match(f)]
    return files


def encoder():
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                             capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        out = ""
    return "libx264" if "libx264" in out else "mpeg4"


def render(files, out_path, fps=24, width=1920, on_progress=None):
    """Baut das Video. on_progress(frame, total) wird regelmaessig aufgerufen."""
    if not files:
        raise RuntimeError("keine Bilder im Zeitraum")
    enc = encoder()
    with tempfile.TemporaryDirectory(prefix="chdkcam-") as tmp:
        for i, f in enumerate(files):
            os.symlink(f, os.path.join(tmp, "%06d.jpg" % i))
        vf = "scale=%d:-2:flags=bicubic,format=yuv420p" % width
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-framerate", str(fps), "-i", os.path.join(tmp, "%06d.jpg"),
               "-vf", vf, "-c:v", enc]
        if enc == "libx264":
            cmd += ["-preset", "veryfast", "-crf", "22"]
        else:
            cmd += ["-q:v", "3"]
        part = out_path + ".part.mp4"
        cmd += ["-movflags", "+faststart", "-progress", "pipe:1", "-nostats", part]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        total = len(files)
        for line in p.stdout:
            if line.startswith("frame=") and on_progress:
                try:
                    on_progress(int(line.split("=", 1)[1]), total)
                except ValueError:
                    pass
        err = p.stderr.read()
        if p.wait() != 0:
            try:
                os.remove(part)
            except OSError:
                pass
            raise RuntimeError("ffmpeg: " + err.strip()[-300:])
        os.replace(part, out_path)
    return out_path


def concat(videos, out_path):
    """Fuegt fertige Videos ohne Neukodieren aneinander (gleiche Groesse/FPS noetig)."""
    if not videos:
        raise RuntimeError("keine Tagesvideos im Zeitraum")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        for v in videos:
            f.write("file '%s'\n" % v.replace("'", "'\\''"))
        lst = f.name
    part = out_path + ".part.mp4"
    try:
        p = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat",
                            "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", part],
                           capture_output=True, text=True, timeout=3600)
        if p.returncode != 0:
            raise RuntimeError("ffmpeg: " + p.stderr.strip()[-300:])
        os.replace(part, out_path)
    finally:
        os.remove(lst)
        if os.path.exists(part):
            os.remove(part)
    return out_path
