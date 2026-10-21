"""Running Blockheads servers: one child process per world, driven through its stdin console.

The 1.7.1 server has no signal handlers, so stopping it is always `/stop` on stdin (it saves, logs "Exiting World."
and exits 0); it is killed only when it does not exit within STOP_TIMEOUT. Lines typed on stdin starting with `/`
are commands run with the owner's rights; other lines are chat from SERVER.

Everything a server prints is NSLog output: `YYYY-MM-DD HH:MM:SS.mmm blockheads_server171[pid:tid] message`, with
multi-line messages continuing on unprefixed lines. The log gives the live player list (connect / disconnect lines,
and `/players` replies) and chat.
"""
import asyncio
import collections
import os
import re
import socket
import time
from pathlib import Path

import psutil

from . import config, db, worlds
from .hub import hub

PREFIX = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3}) blockheads_server171\[\d+:\w+\] ?(.*)$")
CONNECTED = re.compile(r"^WORLD - Player Connected (.+?) \| (.+?) \| (\S+)\s*$")
DISCONNECTED = re.compile(r"^WORLD - Player Disconnected (.+?)\s*$")
PLAYERS_REPLY = re.compile(r"^There are (\d+) players? connected")
PLAYER_ROW = re.compile(r"^(.+?) \| (.+?) \| (\S+)\s*$")
CHAT = re.compile(r"^(.{1,40}?): (.*)$")
LOADED = "World load complete."
PORT_IN_USE = re.compile(r"Failed to start server\. Perhaps port (\d+) is already in use\?")

DEFAULTS = {
    "port": config.FIRST_GAME_PORT,
    "maxPlayers": 16,
    "saveDelay": 10,
    "autostart": False,
    "autorestart": True,
    "mods": [],
    "notify": {"crash": True, "giveUp": True, "backupFailed": True, "join": False, "leave": False},
    "backup": {"enabled": True, "intervalHours": 24, "keep": 7},
}


def server_config(world_id: str) -> dict:
    cfg = {**DEFAULTS, **(db.server_config(world_id) or {})}
    cfg["notify"] = {**DEFAULTS["notify"], **cfg.get("notify", {})}
    cfg["backup"] = {**DEFAULTS["backup"], **cfg.get("backup", {})}
    return cfg


def udp_port_free(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


class Server:
    def __init__(self, world_id: str):
        self.id = world_id
        self.proc: asyncio.subprocess.Process | None = None
        self.status = "stopped"  # stopped | starting | running | stopping | crashed
        self.players: dict[str, dict] = {}
        self.history: collections.deque[str] = collections.deque(maxlen=config.CONSOLE_HISTORY)
        self.crashes: list[float] = []
        self.started_at: float | None = None
        self.last_error: str | None = None
        self._stopping = False
        self._pending_players: dict[str, dict] | None = None
        self._pending_count = 0
        self._last_message = ""
        self._loaded = asyncio.Event()
        self.log_dir = config.LOGS / world_id
        self.log_dir.mkdir(parents=True, exist_ok=True)
        log = self.log_dir / "server.log"
        if log.exists():
            self.history.extend(log.read_text(errors="replace").splitlines()[-config.CONSOLE_HISTORY:])

    # ---- state -------------------------------------------------------------------------------------------------

    @property
    def pid(self) -> int | None:
        return self.proc.pid if self.proc and self.proc.returncode is None else None

    def snapshot(self) -> dict:
        return {"id": self.id, "status": self.status, "players": list(self.players.values()),
                "startedAt": self.started_at, "lastError": self.last_error, "pid": self.pid}

    def _set_status(self, status: str) -> None:
        self.status = status
        hub.publish({"type": "status", "server": self.id, **self.snapshot()})

    # ---- launching -------------------------------------------------------------------------------------------

    def _arguments(self, cfg: dict) -> list[str]:
        common = ["--port", str(cfg["port"]), "--max_players", str(cfg["maxPlayers"]),
                  "--save_delay", str(cfg["saveDelay"])]
        create = cfg.get("create")
        if create:  # first launch: the world does not exist yet
            args = ["--new", create["name"], "--world_id", self.id, "--world_width", create["size"]] + common
            if create.get("expert"):
                args.append("--expert-mode")
            if create.get("customRules") is not None:
                import json
                args += ["--custom-rules", json.dumps(create["customRules"], separators=(",", ":"))]
            return args
        args = ["--load", self.id] + common
        if cfg.get("convertToCustomRules"):
            args.append("--convert-to-custum-rules")  # sic: the server's spelling
        return args

    def _environment(self, cfg: dict) -> dict:
        env = dict(os.environ)
        env.pop("LD_PRELOAD", None)
        mods = [str(config.MODS / m) for m in cfg.get("mods", []) if (config.MODS / m).is_file()]
        if mods:
            env["LD_PRELOAD"] = ":".join(mods)
        return env

    async def start(self) -> None:
        if self.proc and self.proc.returncode is None:
            return
        cfg = server_config(self.id)
        if not cfg.get("create") and not worlds.exists(self.id):
            raise RuntimeError("The world's save folder is missing.")
        port = cfg["port"]
        if any(s is not self and s.pid and server_config(s.id)["port"] == port for s in manager.servers.values()) \
                or not udp_port_free(port):
            raise RuntimeError(f"UDP port {port} is already in use.")
        self.players.clear()
        self.last_error = None
        self._stopping = False
        self._loaded.clear()
        self._set_status("starting")
        self._log_line(f"[portal] Starting: {' '.join(self._arguments(cfg))}")
        self.proc = await asyncio.create_subprocess_exec(
            str(config.SERVER_BINARY), *self._arguments(cfg), cwd=str(config.SERVER_CWD), env=self._environment(cfg),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        self.started_at = time.time()
        asyncio.create_task(self._read(self.proc))

    async def wait_loaded(self, timeout: float) -> bool:
        try:
            await asyncio.wait_for(self._loaded.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def stop(self, timeout: float = config.STOP_TIMEOUT) -> None:
        proc = self.proc
        if not proc or proc.returncode is not None:
            return
        self._stopping = True
        self._set_status("stopping")
        try:
            proc.stdin.write(b"/stop\n")
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout)
        except asyncio.TimeoutError:
            self._log_line(f"[portal] The server did not stop within {timeout} s; killing it.")
            proc.kill()
            await proc.wait()

    async def command(self, line: str) -> None:
        proc = self.proc
        if not proc or proc.returncode is not None or self.status != "running":
            raise RuntimeError("The server is not running.")
        line = line.replace("\r", " ").replace("\n", " ").strip()
        if not line:
            return
        self._log_line(f"[console] {line}")
        proc.stdin.write(line.encode() + b"\n")
        await proc.stdin.drain()

    # ---- output ------------------------------------------------------------------------------------------------

    async def _read(self, proc: asyncio.subprocess.Process) -> None:
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            self._handle(raw.decode(errors="replace").rstrip("\n"))
        code = await proc.wait()
        await self._exited(code)

    def _handle(self, line: str) -> None:
        self._log_line(line)
        m = PREFIX.match(line)
        if m:
            self._message(m.group(2), continuation=False)
        else:
            self._message(line, continuation=True)

    def _message(self, msg: str, continuation: bool) -> None:
        if continuation:
            if self._pending_players is not None:
                row = PLAYER_ROW.match(msg.strip())
                if row:
                    alias, ip, pid = row.groups()
                    self._pending_players[alias] = {"name": alias, "ip": ip, "id": pid}
                    if len(self._pending_players) >= self._pending_count:
                        self._finish_players_reply()
            return
        if self._pending_players is not None:
            self._finish_players_reply()
        if msg == LOADED:
            self._loaded.set()
            cfg = db.server_config(self.id) or {}
            one_off = [cfg.pop(k, None) for k in ("create", "convertToCustomRules")]  # first-launch-only flags
            if any(v is not None for v in one_off):
                db.save_server_config(self.id, cfg)
            self._set_status("running")
            return
        if m := PORT_IN_USE.search(msg):
            self.last_error = f"UDP port {m.group(1)} is already in use."
            return
        if m := CONNECTED.match(msg):
            alias, ip, pid = m.groups()
            self.players[alias] = {"name": alias, "ip": ip, "id": pid, "since": time.time()}
            self._players_changed()
            if server_config(self.id)["notify"]["join"]:
                hub.notify(self.id, "join", f"{alias} joined {self._name()}.")
            return
        if m := DISCONNECTED.match(msg):
            alias = m.group(1)
            self.players.pop(alias, None)
            self._players_changed()
            if server_config(self.id)["notify"]["leave"]:
                hub.notify(self.id, "leave", f"{alias} left {self._name()}.")
            return
        if m := PLAYERS_REPLY.match(msg):
            self._pending_count = int(m.group(1))
            self._pending_players = {}
            if self._pending_count == 0:
                self._finish_players_reply()
            return
        if m := CHAT.match(msg):
            alias, text = m.groups()
            if alias == "SERVER" or alias in self.players:
                hub.publish({"type": "chat", "server": self.id, "name": alias, "text": text, "t": time.time()})

    def _finish_players_reply(self) -> None:
        found, self._pending_players = self._pending_players or {}, None
        for alias, p in found.items():
            p["since"] = self.players.get(alias, {}).get("since", time.time())
        self.players = found
        self._players_changed()

    def _players_changed(self) -> None:
        hub.publish({"type": "players", "server": self.id, "players": list(self.players.values())})

    def _name(self) -> str:
        try:
            return worlds.summary(self.id)["name"]
        except Exception:
            return self.id

    def _log_line(self, line: str) -> None:
        self.history.append(line)
        log = self.log_dir / "server.log"
        try:
            if log.exists() and log.stat().st_size > config.LOG_ROTATE_BYTES:
                for n in range(config.LOG_KEEP, 0, -1):
                    older = self.log_dir / f"server.log.{n}"
                    newer = self.log_dir / (f"server.log.{n - 1}" if n > 1 else "server.log")
                    if newer.exists():
                        newer.replace(older)
            with open(log, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass
        hub.publish({"type": "log", "server": self.id, "line": line})

    async def _exited(self, code: int) -> None:
        self.players.clear()
        self._players_changed()
        self._log_line(f"[portal] The server exited with code {code}.")
        if self._stopping or code == 0:
            self.started_at = None
            self._set_status("stopped")
            return
        # A crash.
        now = time.time()
        self.crashes = [t for t in self.crashes if now - t < config.CRASH_WINDOW] + [now]
        self.last_error = self.last_error or f"The server crashed (exit code {code})."
        self._set_status("crashed")
        cfg = server_config(self.id)
        if cfg.get("create"):
            return  # creating the world failed; nothing to restart
        if not cfg["autorestart"]:
            if cfg["notify"]["crash"]:
                hub.notify(self.id, "crash", f"{self._name()} crashed.")
            return
        if len(self.crashes) >= config.CRASH_LIMIT:
            if cfg["notify"]["giveUp"]:
                hub.notify(self.id, "giveUp", f"{self._name()} crashed {len(self.crashes)} times in "
                                              f"{config.CRASH_WINDOW // 60} minutes; not restarting it again.")
            return
        if cfg["notify"]["crash"]:
            hub.notify(self.id, "crash", f"{self._name()} crashed; restarting it.")
        await asyncio.sleep(3)
        if self.status == "crashed":
            try:
                await self.start()
            except Exception as e:
                self.last_error = str(e)
                self._set_status("crashed")

    def usage(self) -> tuple[float, int]:
        """CPU percent and resident memory of the running process."""
        pid = self.pid
        if not pid:
            return 0.0, 0
        try:
            p = psutil.Process(pid)
            return p.cpu_percent(interval=None), p.memory_info().rss
        except psutil.Error:
            return 0.0, 0


class Manager:
    def __init__(self):
        self.servers: dict[str, Server] = {}

    def get(self, world_id: str) -> Server:
        if world_id not in self.servers:
            self.servers[world_id] = Server(world_id)
        return self.servers[world_id]

    def known_ids(self) -> list[str]:
        ids = set(worlds.all_ids()) | set(db.all_server_configs())
        return sorted(ids)

    def next_free_port(self) -> int:
        used = {server_config(i)["port"] for i in db.all_server_configs()}
        port = config.FIRST_GAME_PORT
        while port in used or not udp_port_free(port):
            port += 1
        return port

    def is_running(self, world_id: str) -> bool:
        s = self.servers.get(world_id)
        return bool(s and s.pid)

    async def autostart(self) -> None:
        for world_id, cfg in db.all_server_configs().items():
            if cfg.get("autostart") and worlds.exists(world_id):
                try:
                    await self.get(world_id).start()
                except Exception as e:
                    self.get(world_id).last_error = str(e)

    async def stop_all(self) -> None:
        await asyncio.gather(*(s.stop() for s in self.servers.values() if s.pid), return_exceptions=True)


manager = Manager()
