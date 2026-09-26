"""Settings, read from the environment or from .env in the project directory
(see .env.example). Standard library only, so it also runs on Python 3.8.
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_env(path):
    """Sets KEY=VALUE lines from path as environment variables, unless
    they're already set."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_env(os.path.join(BASE_DIR, ".env"))

DATA_DIR = os.getenv("DATA_DIR") or os.path.join(BASE_DIR, "data")
# The files as downloaded from gov.pl, plus sources.json describing them.
DOWNLOAD_DIR = os.path.join(DATA_DIR, "downloads")
# Question pictures and videos, converted for browsers.
MEDIA_DIR = os.path.join(DATA_DIR, "media")
DB_FILE = os.path.join(DATA_DIR, "questions.db")
# Accounts and exam results; unlike DB_FILE, never rebuilt.
USERS_DB = os.path.join(DATA_DIR, "users.db")
WEB_DIR = os.path.join(BASE_DIR, "web")

WEB_HOST = os.getenv("WEB_HOST") or "0.0.0.0"
WEB_PORT = int(os.getenv("WEB_PORT") or "8073")

# The ministry page linking the question catalog and its media.
SOURCE_PAGE = os.getenv("SOURCE_PAGE") or (
    "https://www.gov.pl/web/infrastruktura/jak-uzyskac-prawo-jazdy")

# Path to ffmpeg; by default the one on PATH, else imageio-ffmpeg's.
FFMPEG = os.getenv("FFMPEG", "")
# How many media files to convert at once.
MEDIA_WORKERS = int(os.getenv("MEDIA_WORKERS") or str(os.cpu_count() or 2))
