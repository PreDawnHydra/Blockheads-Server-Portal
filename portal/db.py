"""The portal's own state in SQLite: settings, per-server configuration, sessions and stats."""
import json
import sqlite3
import threading
import time

from . import config

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS servers (id TEXT PRIMARY KEY, config TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS stats (server TEXT NOT NULL, t REAL NOT NULL, players INTEGER, cpu REAL, rss INTEGER);
CREATE INDEX IF NOT EXISTS stats_server_t ON stats (server, t);
"""


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False, isolation_level=None)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(SCHEMA)
    return _conn


def execute(sql: str, args: tuple = ()) -> list[tuple]:
    with _lock:
        return conn().execute(sql, args).fetchall()


def get_setting(key: str, default=None):
    rows = execute("SELECT value FROM settings WHERE key=?", (key,))
    return json.loads(rows[0][0]) if rows else default


def set_setting(key: str, value) -> None:
    execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)))


# Per-server configuration (port, players, autostart, …), keyed by world id.
def server_config(world_id: str) -> dict | None:
    rows = execute("SELECT config FROM servers WHERE id=?", (world_id,))
    return json.loads(rows[0][0]) if rows else None


def all_server_configs() -> dict[str, dict]:
    return {i: json.loads(c) for i, c in execute("SELECT id, config FROM servers")}


def save_server_config(world_id: str, cfg: dict) -> None:
    execute("INSERT INTO servers (id, config) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET config=excluded.config",
            (world_id, json.dumps(cfg)))


def delete_server_config(world_id: str) -> None:
    execute("DELETE FROM servers WHERE id=?", (world_id,))
    execute("DELETE FROM stats WHERE server=?", (world_id,))


def add_stat(world_id: str, players: int, cpu: float, rss: int) -> None:
    execute("INSERT INTO stats VALUES (?, ?, ?, ?, ?)", (world_id, time.time(), players, cpu, rss))


def stats_since(world_id: str, since: float) -> list[tuple]:
    return execute("SELECT t, players, cpu, rss FROM stats WHERE server=? AND t>=? ORDER BY t", (world_id, since))


def prune_stats(before: float) -> None:
    execute("DELETE FROM stats WHERE t<?", (before,))
