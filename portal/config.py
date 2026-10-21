"""Paths and settings from the environment.

Everything the portal keeps lives under DATA (one volume); backups go to /backups when that is mounted.
"""
import os
from pathlib import Path

DATA = Path(os.environ.get("PORTAL_DATA", "/data"))
WORLDS = DATA / "worlds"  # the server's saves directory (/saves is a symlink to it)
TRASH = DATA / "trash"
MODS = DATA / "mods"
ASSETS = DATA / "assets"
LOGS = DATA / "logs"
DB_PATH = DATA / "portal.db"
BACKUPS = Path("/backups") if Path("/backups").is_dir() else DATA / "backups"

SERVER_BINARY = Path(os.environ.get("PORTAL_SERVER_BINARY", "/app/blockheads_server171"))
SERVER_CWD = SERVER_BINARY.parent

PORT = int(os.environ.get("PORTAL_PORT", "8080"))
HOST = os.environ.get("PORTAL_HOST", "0.0.0.0")
ENV_PASSWORD = os.environ.get("PORTAL_PASSWORD") or None

FIRST_GAME_PORT = 15151
TRASH_DAYS = 7
STOP_TIMEOUT = 30          # seconds to wait for /stop before killing
CRASH_LIMIT = 3            # crashes ...
CRASH_WINDOW = 10 * 60     # ... within this many seconds stop the auto restart
LOG_ROTATE_BYTES = 5 * 1024 * 1024
LOG_KEEP = 5
CONSOLE_HISTORY = 1000
STATS_INTERVAL = 30
STATS_KEEP_DAYS = 7


def ensure_dirs() -> None:
    for d in (DATA, WORLDS, TRASH, MODS, ASSETS, LOGS, BACKUPS):
        d.mkdir(parents=True, exist_ok=True)
