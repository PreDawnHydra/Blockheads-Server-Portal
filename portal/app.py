"""The portal's web API and pages."""
import asyncio
import contextlib
import io
import json
import re
import time
import zipfile
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile, WebSocket, \
    WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import assets, auth, backups, config, db, jobs, rules, worlds
from .hub import hub
from .servers import DEFAULTS, manager, server_config

STATIC = Path(__file__).resolve().parent.parent / "static"


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    config.ensure_dirs()
    db.conn()
    tasks = [asyncio.create_task(jobs.stats_loop()), asyncio.create_task(jobs.backup_loop())]
    await manager.autostart()
    yield
    await manager.stop_all()
    for t in tasks:
        t.cancel()


app = FastAPI(title="Blockheads Server Portal", lifespan=lifespan, docs_url=None, redoc_url=None)
User = Depends(auth.current_user)


@app.exception_handler(worlds.WorldError)
async def world_error(_, e: worlds.WorldError):
    return JSONResponse({"detail": str(e)}, status_code=400)


@app.exception_handler(ValueError)
async def value_error(_, e: ValueError):
    return JSONResponse({"detail": str(e)}, status_code=400)


@app.exception_handler(RuntimeError)
async def runtime_error(_, e: RuntimeError):
    return JSONResponse({"detail": str(e)}, status_code=409)


# ---- Setup and login --------------------------------------------------------------------------------------------

class PasswordIn(BaseModel):
    password: str


class LoginIn(BaseModel):
    password: str
    remember: bool = False


class ChangePasswordIn(BaseModel):
    current: str
    new: str


@app.get("/api/state")
def state(request: Request):
    return {"configured": auth.is_configured(), "passwordFromEnvironment": config.ENV_PASSWORD is not None,
            "signedIn": auth.valid_session(request.cookies.get(auth.COOKIE)), "assets": assets.status()}


def _sign_in(response: Response, remember: bool) -> None:
    token, max_age = auth.new_session(remember)
    response.set_cookie(auth.COOKIE, token, max_age=max_age, httponly=True, samesite="strict")


@app.post("/api/setup/password")
def setup_password(body: PasswordIn, response: Response):
    if auth.is_configured():
        raise HTTPException(409, "The portal is set up already.")
    auth.set_password(body.password)
    _sign_in(response, remember=True)
    return {"ok": True}


@app.post("/api/login")
def login(body: LoginIn, request: Request, response: Response):
    address = auth.client_address(request)
    auth.check_rate_limit(address)
    if not auth.check_password(body.password):
        auth.record_failure(address)
        raise HTTPException(401, "Wrong password.")
    _sign_in(response, body.remember)
    return {"ok": True}


@app.post("/api/logout")
def logout(request: Request, response: Response):
    auth.end_session(request.cookies.get(auth.COOKIE))
    response.delete_cookie(auth.COOKIE)
    return {"ok": True}


@app.post("/api/password")
def change_password(body: ChangePasswordIn, request: Request, response: Response, _=User):
    if config.ENV_PASSWORD is not None:
        raise HTTPException(409, "The password is set by PORTAL_PASSWORD; change it there.")
    address = auth.client_address(request)
    auth.check_rate_limit(address)
    if not auth.check_password(body.current):
        auth.record_failure(address)
        raise HTTPException(401, "The current password is wrong.")
    auth.set_password(body.new)
    _sign_in(response, remember=True)
    return {"ok": True}


# ---- Game assets ------------------------------------------------------------------------------------------------

@app.post("/api/assets")
async def upload_assets(file: UploadFile = File(...), _=User):
    tmp = config.DATA / "tmp" / "upload.apk"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, "wb") as f:
        while chunk := await file.read(1 << 20):
            f.write(chunk)
    try:
        result = await asyncio.to_thread(assets.extract, tmp)
    finally:
        tmp.unlink(missing_ok=True)
    return result


@app.get("/api/rules")
def rule_schema(_=User):
    return rules.schema()


@app.get("/api/items")
def items(_=User):
    return assets.items()


# ---- Servers ------------------------------------------------------------------------------------------------------

def _require_world(world_id: str) -> None:
    worlds.path(world_id)
    if not worlds.exists(world_id) and not (db.server_config(world_id) or {}).get("create"):
        raise HTTPException(404, "No such server.")


def _require_stopped(world_id: str) -> None:
    if manager.is_running(world_id):
        raise HTTPException(409, "Stop the server first.")


def _overview(world_id: str) -> dict:
    s = manager.get(world_id)
    cfg = server_config(world_id)
    try:
        summary = worlds.summary(world_id) if worlds.exists(world_id) else \
            {"id": world_id, "name": cfg["create"]["name"].upper(), "size": cfg["create"]["size"],
             "expert": cfg["create"].get("expert", False), "custom": cfg["create"].get("customRules") is not None,
             "created": None}
    except Exception:
        summary = {"id": world_id, "name": world_id}
    return {**summary, **s.snapshot(), "config": {k: v for k, v in cfg.items() if k != "create"},
            "creating": bool(cfg.get("create"))}


@app.get("/api/servers")
def list_servers(_=User):
    return [_overview(i) for i in manager.known_ids()]


class CreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    size: str = "1"
    expert: bool = False
    customRules: dict | None = None
    port: int | None = None
    maxPlayers: int = Field(default=16, ge=1, le=32)
    saveDelay: int = Field(default=10, ge=1, le=3600)
    autostart: bool = False
    start: bool = True


@app.post("/api/servers")
async def create_server(body: CreateIn, _=User):
    if body.size not in worlds.SIZES:
        raise HTTPException(400, "Unknown world size.")
    if body.customRules is not None and (errors := rules.validate(body.customRules)):
        raise HTTPException(400, " ".join(errors))
    if any(c in body.name for c in "\n\r\""):
        raise HTTPException(400, "The name contains characters the server cannot use.")
    world_id = worlds.new_id()
    port = body.port or manager.next_free_port()
    cfg = {**DEFAULTS, "port": port, "maxPlayers": body.maxPlayers, "saveDelay": body.saveDelay,
           "autostart": body.autostart,
           "create": {"name": worlds.unique_name(body.name.strip()), "size": body.size, "expert": body.expert,
                      "customRules": body.customRules}}
    db.save_server_config(world_id, cfg)
    server = manager.get(world_id)
    try:
        await server.start()
    except Exception:
        db.delete_server_config(world_id)
        raise

    async def finish():
        if await server.wait_loaded(600) and not body.start:
            await server.stop()
    asyncio.create_task(finish())
    return _overview(world_id)


@app.get("/api/servers/{world_id}")
def get_server(world_id: str, _=User):
    _require_world(world_id)
    out = _overview(world_id)
    if worlds.exists(world_id):
        out["world"] = worlds.info(world_id)
        out["lists"] = {n: worlds.read_list(world_id, n) for n in worlds.LISTS}
    return out


class ConfigIn(BaseModel):
    port: int | None = Field(default=None, ge=1024, le=65535)
    maxPlayers: int | None = Field(default=None, ge=1, le=32)
    saveDelay: int | None = Field(default=None, ge=1, le=3600)
    autostart: bool | None = None
    autorestart: bool | None = None
    mods: list[str] | None = None
    notify: dict | None = None
    backup: dict | None = None


@app.patch("/api/servers/{world_id}/config")
def update_config(world_id: str, body: ConfigIn, _=User):
    _require_world(world_id)
    cfg = db.server_config(world_id) or dict(DEFAULTS)
    changes = body.model_dump(exclude_none=True)
    if "port" in changes and changes["port"] != cfg.get("port"):
        if any(server_config(i)["port"] == changes["port"] for i in db.all_server_configs() if i != world_id):
            raise HTTPException(409, f"Another server uses port {changes['port']}.")
    if "mods" in changes:
        for m in changes["mods"]:
            if not (config.MODS / m).is_file() or "/" in m:
                raise HTTPException(400, f"No mod named {m}.")
    if "notify" in changes:
        changes["notify"] = {k: bool(changes["notify"].get(k, v)) for k, v in server_config(world_id)["notify"].items()}
    if "backup" in changes:
        b = {**server_config(world_id)["backup"], **changes["backup"]}
        changes["backup"] = {"enabled": bool(b["enabled"]), "intervalHours": max(1, int(b["intervalHours"])),
                             "keep": max(1, int(b["keep"]))}
    cfg.update(changes)
    db.save_server_config(world_id, cfg)
    return _overview(world_id)


@app.post("/api/servers/{world_id}/start")
async def start_server(world_id: str, _=User):
    _require_world(world_id)
    s = manager.get(world_id)
    s.crashes.clear()
    await s.start()
    return s.snapshot()


@app.post("/api/servers/{world_id}/stop")
async def stop_server(world_id: str, _=User):
    s = manager.get(world_id)
    await s.stop()
    return s.snapshot()


@app.post("/api/servers/{world_id}/restart")
async def restart_server(world_id: str, _=User):
    s = manager.get(world_id)
    await s.stop()
    s.crashes.clear()
    await s.start()
    return s.snapshot()


class LineIn(BaseModel):
    line: str = Field(min_length=1, max_length=500)


@app.post("/api/servers/{world_id}/command")
async def console_command(world_id: str, body: LineIn, _=User):
    await manager.get(world_id).command(body.line)
    return {"ok": True}


@app.post("/api/servers/{world_id}/chat")
async def chat(world_id: str, body: LineIn, _=User):
    text = body.line.lstrip("/")  # a line starting with / would be a command
    await manager.get(world_id).command(text)
    return {"ok": True}


@app.get("/api/servers/{world_id}/console")
def console_history(world_id: str, _=User):
    return {"lines": list(manager.get(world_id).history)}


@app.post("/api/servers/{world_id}/diagnostics")
async def diagnostics(world_id: str, _=User):
    s = manager.get(world_id)
    before = len(s.history)
    marker = s.history[-1] if s.history else None
    await s.command("/debug-log")
    await asyncio.sleep(1.5)
    lines = list(s.history)
    start = lines.index(marker) + 1 if marker in lines else max(0, len(lines) - (len(lines) - before))
    return {"lines": [l for l in lines[start:] if not l.startswith("[console]")]}


PLAYER_COMMANDS = {"kick": "/kick", "ban": "/ban", "ban-no-device": "/ban-no-device", "unban": "/unban",
                   "mod": "/mod", "unmod": "/unmod", "admin": "/admin", "unadmin": "/unadmin",
                   "whitelist": "/whitelist", "unwhitelist": "/unwhitelist"}


@app.post("/api/servers/{world_id}/players/{name}/{action}")
async def player_action(world_id: str, name: str, action: str, _=User):
    if action not in PLAYER_COMMANDS or not re.fullmatch(r"[^\s/]{1,64}", name):
        raise HTTPException(400, "Unknown action.")
    await manager.get(world_id).command(f"{PLAYER_COMMANDS[action]} {name}")
    return {"ok": True}


# Each list's add / remove commands, used while the server runs (it rewrites the files itself).
LIST_COMMANDS = {"adminlist": ("/admin", "/unadmin"), "modlist": ("/mod", "/unmod"),
                 "blacklist": ("/ban", "/unban"), "whitelist": ("/whitelist", "/unwhitelist")}


class ListIn(BaseModel):
    entries: list[str]


@app.put("/api/servers/{world_id}/lists/{name}")
async def set_list(world_id: str, name: str, body: ListIn, _=User):
    _require_world(world_id)
    if name not in worlds.LISTS:
        raise HTTPException(404, "No such list.")
    entries = [e.strip() for e in body.entries if e.strip()]
    if any(re.search(r"\s", e) for e in entries):
        raise HTTPException(400, "Names and addresses cannot contain spaces.")
    if manager.is_running(world_id):
        s = manager.get(world_id)
        current = {e.lower(): e for e in worlds.read_list(world_id, name)}
        wanted = {e.lower(): e for e in entries}
        add, remove = LIST_COMMANDS[name]
        for key in wanted.keys() - current.keys():
            await s.command(f"{add} {wanted[key]}")
        for key in current.keys() - wanted.keys():
            await s.command(f"{remove} {current[key]}")
        await asyncio.sleep(0.5)
    else:
        worlds.write_list(world_id, name, entries)
    return {"entries": worlds.read_list(world_id, name)}


@app.post("/api/servers/{world_id}/lists/reload")
async def reload_lists(world_id: str, _=User):
    await manager.get(world_id).command("/load-lists")
    return {"ok": True}


class WorldEditIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=32)
    welcomeMessage: str | None = Field(default=None, max_length=500)
    password: str | None = Field(default=None, max_length=16)  # "" removes it
    pvp: bool | None = None


@app.patch("/api/servers/{world_id}/world")
async def edit_world(world_id: str, body: WorldEditIn, _=User):
    _require_world(world_id)
    running = manager.is_running(world_id)
    if running:
        if body.name is not None or body.welcomeMessage is not None:
            raise HTTPException(409, "Stop the server to change its name or welcome message.")
        s = manager.get(world_id)
        if body.password is not None:
            await s.command(f"/set-password {body.password}" if body.password else "/remove-password")
        if body.pvp is not None:
            await s.command("/pvp-on" if body.pvp else "/pvp-off")
        return {"ok": True}
    changes = {}
    if body.name is not None:
        changes["worldName"] = body.name.strip().upper()
    if body.welcomeMessage is not None:
        changes["welcomeMessage"] = body.welcomeMessage
    if body.password is not None:
        changes["serverPassword"] = body.password
    if body.pvp is not None:
        changes["pvpDisabled"] = not body.pvp
    if changes:
        await asyncio.to_thread(backups.create, world_id, "before-edit")
        worlds.update_record(world_id, changes)
    return worlds.info(world_id)


@app.post("/api/servers/{world_id}/convert-custom-rules")
async def convert_custom_rules(world_id: str, _=User):
    _require_world(world_id)
    _require_stopped(world_id)
    await asyncio.to_thread(backups.create, world_id, "before-rules")
    cfg = db.server_config(world_id) or dict(DEFAULTS)
    cfg["convertToCustomRules"] = True
    db.save_server_config(world_id, cfg)
    return {"ok": True, "note": "The world converts to custom rules the next time it starts."}


@app.get("/api/servers/{world_id}/stats")
def stats(world_id: str, range: str = "24h", _=User):
    seconds = {"24h": 86400, "7d": 7 * 86400}.get(range, 86400)
    return [{"t": t, "players": p, "cpu": c, "rss": r} for t, p, c, r in db.stats_since(world_id, time.time() - seconds)]


@app.get("/api/servers/{world_id}/logs")
def download_logs(world_id: str, _=User):
    d = manager.get(world_id).log_dir
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(d.glob("server.log*")):
            z.write(f, f.name)
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{world_id}-logs.zip"'})


class CloneIn(BaseModel):
    name: str | None = Field(default=None, max_length=32)


@app.post("/api/servers/{world_id}/clone")
async def clone_world(world_id: str, body: CloneIn, _=User):
    _require_world(world_id)
    new = await asyncio.to_thread(worlds.clone, world_id, body.name)
    cfg = {**server_config(world_id), "port": manager.next_free_port(), "autostart": False}
    cfg.pop("create", None)
    db.save_server_config(new, cfg)
    return _overview(new)


def _file_response(path: Path, filename: str) -> StreamingResponse:
    def chunks():
        with open(path, "rb") as f:
            while data := f.read(1 << 20):
                yield data
        path.unlink(missing_ok=True)
    return StreamingResponse(chunks(), media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9 ()_-]", "", name).strip() or "world"


@app.get("/api/servers/{world_id}/export")
async def export_world(world_id: str, _=User):
    _require_world(world_id)
    out = await asyncio.to_thread(worlds.export_zip, world_id)
    return _file_response(out, f"{_safe_filename(worlds.summary(world_id)['name'])}.zip")


@app.post("/api/worlds/import")
async def import_world(file: UploadFile = File(...), _=User):
    data = await file.read()
    world_id = await asyncio.to_thread(worlds.import_zip, data)
    cfg = {**DEFAULTS, "port": manager.next_free_port()}
    db.save_server_config(world_id, cfg)
    return _overview(world_id)


@app.delete("/api/servers/{world_id}")
async def delete_server(world_id: str, _=User):
    _require_world(world_id)
    s = manager.get(world_id)
    await s.stop()
    if worlds.exists(world_id):
        await asyncio.to_thread(backups.safe_create, world_id, "before-delete")
        worlds.to_trash(world_id)
    else:
        db.delete_server_config(world_id)
    manager.servers.pop(world_id, None)
    return {"ok": True}


# ---- Trash, backups, mods ------------------------------------------------------------------------------------

@app.get("/api/trash")
def trash(_=User):
    return worlds.trash_items()


@app.post("/api/trash/{key}/restore")
def restore_trash(key: str, _=User):
    world_id = worlds.restore_from_trash(key)
    if not db.server_config(world_id):
        db.save_server_config(world_id, {**DEFAULTS, "port": manager.next_free_port()})
    return _overview(world_id)


@app.delete("/api/trash/{key}")
def purge_trash(key: str, _=User):
    item = next((i for i in worlds.trash_items() if i["key"] == key), None)
    if not item:
        raise HTTPException(404, "Not in the trash.")
    import shutil
    shutil.rmtree(config.TRASH / key, ignore_errors=True)
    if not worlds.exists(item["id"]):
        db.delete_server_config(item["id"])
    return {"ok": True}


@app.get("/api/servers/{world_id}/backups")
def list_backups(world_id: str, _=User):
    return backups.listing(world_id)


@app.post("/api/servers/{world_id}/backups")
async def make_backup(world_id: str, _=User):
    _require_world(world_id)
    return await asyncio.to_thread(backups.create, world_id, "manual")


@app.get("/api/servers/{world_id}/backups/{name}")
def download_backup(world_id: str, name: str, _=User):
    return FileResponse(backups.file(world_id, name), filename=name, media_type="application/zip")


@app.post("/api/servers/{world_id}/backups/{name}/restore")
async def restore_backup(world_id: str, name: str, _=User):
    _require_world(world_id)
    _require_stopped(world_id)
    await asyncio.to_thread(backups.restore, world_id, name)
    return {"ok": True}


@app.delete("/api/servers/{world_id}/backups/{name}")
def delete_backup(world_id: str, name: str, _=User):
    backups.file(world_id, name).unlink()
    return {"ok": True}


@app.get("/api/mods")
def list_mods(_=User):
    used = {}
    for i, cfg in db.all_server_configs().items():
        for m in cfg.get("mods", []):
            used.setdefault(m, []).append(i)
    return [{"name": f.name, "bytes": f.stat().st_size, "servers": used.get(f.name, [])}
            for f in sorted(config.MODS.glob("*.so"))]


@app.post("/api/mods")
async def upload_mod(file: UploadFile = File(...), _=User):
    name = Path(file.filename or "").name
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}\.so", name):
        raise HTTPException(400, "A mod must be a .so file with a simple name.")
    data = await file.read()
    if not data.startswith(b"\x7fELF"):
        raise HTTPException(400, "That is not a Linux shared library.")
    (config.MODS / name).write_bytes(data)
    return {"name": name, "bytes": len(data)}


@app.delete("/api/mods/{name}")
def delete_mod(name: str, _=User):
    f = config.MODS / Path(name).name
    if not f.is_file():
        raise HTTPException(404, "No such mod.")
    for i, cfg in db.all_server_configs().items():
        if name in cfg.get("mods", []):
            cfg["mods"] = [m for m in cfg["mods"] if m != name]
            db.save_server_config(i, cfg)
    f.unlink()
    return {"ok": True}


@app.get("/api/notifications")
def notifications(_=User):
    return hub.recent_notifications


# ---- Live events -------------------------------------------------------------------------------------------------

@app.websocket("/ws")
async def events(ws: WebSocket):
    if not auth.valid_session(ws.cookies.get(auth.COOKIE)):
        await ws.close(code=4401)
        return
    await ws.accept()
    q = hub.subscribe()
    try:
        while True:
            event = await q.get()
            await ws.send_text(json.dumps(event))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.unsubscribe(q)


# ---- Pages ---------------------------------------------------------------------------------------------------------

app.mount("/game", StaticFiles(directory=config.ASSETS, check_dir=False), name="game")
app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
