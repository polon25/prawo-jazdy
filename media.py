"""Turns the catalog's media into files browsers can show: videos (WMV in
the archives) become H.264 MP4, pictures are scaled down to at most
MAX_WIDTH pixels wide (some are 9 MB photos). Only files the catalog uses
are converted, straight from the downloaded zip archives, into MEDIA_DIR.
A file already there is kept, so an interrupted run carries on where it
stopped.
"""

import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

import config
from catalog import VIDEO_EXTENSIONS

log = logging.getLogger("media")

MAX_WIDTH = 1280
_SCALE = "scale='trunc(min(%d,iw*sar)/2)*2':-2,setsar=1" % MAX_WIDTH


def find_ffmpeg():
    if config.FFMPEG:
        return config.FFMPEG
    path = shutil.which("ffmpeg")
    if path:
        return path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        raise SystemExit("ffmpeg not found: install it, or imageio-ffmpeg "
                         "(pip install -r requirements.txt), or set FFMPEG")


def is_video(name):
    return name.lower().endswith(VIDEO_EXTENSIONS)


def output_name(name):
    """The converted file's name: videos get .mp4, pictures keep theirs."""
    if is_video(name):
        return os.path.splitext(name)[0] + ".mp4"
    return name


def _command(ffmpeg, source, target):
    command = [ffmpeg, "-nostdin", "-y", "-loglevel", "error", "-i", source]
    if is_video(target):
        command += ["-map", "0:v:0", "-map", "0:a:0?", "-vf",
                    _SCALE + ",format=yuv420p", "-c:v", "libx264",
                    "-preset", "veryfast", "-crf", "23", "-c:a", "aac",
                    "-b:a", "96k", "-movflags", "+faststart", "-threads", "2"]
    else:
        command += ["-vf", _SCALE, "-q:v", "3", "-frames:v", "1"]
    return command + [target]


def _convert(ffmpeg, archive, member, target):
    """Extracts member from archive to a temporary file and converts it to
    target. Returns an error message, or None."""
    stem, extension = os.path.splitext(target)
    partial = stem + ".part" + extension  # ffmpeg picks the format by it
    with tempfile.TemporaryDirectory(dir=config.DATA_DIR) as tmp:
        with zipfile.ZipFile(archive) as z:
            source = z.extract(member, tmp)
        result = subprocess.run(_command(ffmpeg, source, partial),
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE)
        if result.returncode == 0 and os.path.exists(partial):
            os.replace(partial, target)
            return None
        if os.path.exists(partial):
            os.remove(partial)
        error = result.stderr.decode("utf-8", "replace").strip()[-500:] \
            or "ffmpeg failed"
        if is_video(target):
            return error
        # A few ".jpg" files are really AVIF or WebP, which older ffmpeg
        # can't read but browsers show fine: keep those as they are.
        log.info("Can't convert %s (%s), keeping it as it is",
                 os.path.basename(member), error.splitlines()[-1])
        shutil.move(source, target)
        return None


def prepare(archives, names):
    """Converts the media files named in names (as the catalog names them)
    from the zip archives. Returns {catalog name: converted file name} for
    those that are ready; the others are logged."""
    os.makedirs(config.MEDIA_DIR, exist_ok=True)
    members = {}  # lowercase file name -> (archive, member in the archive)
    for archive in archives:
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                if not info.is_dir():
                    base = os.path.basename(info.filename)
                    members.setdefault(base.lower(), (archive, info.filename))

    ready, jobs, missing = {}, [], []
    for name in sorted(set(names)):
        target = os.path.join(config.MEDIA_DIR, output_name(name))
        if os.path.exists(target):
            ready[name] = output_name(name)
        elif name.lower() in members:
            jobs.append((name, target) + members[name.lower()])
        else:
            missing.append(name)
    if missing:
        log.warning("%d media files named in the catalog aren't in the "
                    "archives, their questions are left out: %s%s",
                    len(missing), ", ".join(missing[:10]),
                    ", ..." if len(missing) > 10 else "")
    if not jobs:
        return ready

    ffmpeg = find_ffmpeg()
    videos = sum(1 for job in jobs if is_video(job[0]))
    log.info("Converting %d media files (%d videos) with %d workers",
             len(jobs), videos, config.MEDIA_WORKERS)
    lock = threading.Lock()
    progress = {"done": 0, "reported": time.time()}
    started = time.time()

    def work(job):
        name, target, archive, member = job
        error = _convert(ffmpeg, archive, member, target)
        with lock:
            progress["done"] += 1
            if error:
                log.warning("Can't convert %s, its questions are left "
                            "out: %s", name, error)
            else:
                ready[name] = os.path.basename(target)
            now = time.time()
            if now - progress["reported"] > 30:
                progress["reported"] = now
                done = progress["done"]
                left = (now - started) / done * (len(jobs) - done)
                log.info("  media: %d/%d, about %d min left",
                         done, len(jobs), left // 60 + 1)

    with ThreadPoolExecutor(config.MEDIA_WORKERS) as pool:
        list(pool.map(work, jobs))
    log.info("Media converted in %d min", (time.time() - started) // 60)
    return ready
