"""World save folders: reading their info, the player lists, world database edits, clone, import, export and trash.

A save folder `<id>/` holds `worldv2` (an XML plist summary), three LMDB environments (`world_db`, `server_db`,
`lightBlocks`) and the four list files. The authoritative world record is `world_db`, named db `main`, key `worldv2`
(a plist); the `worldv2` file is a summary the server writes alongside it.
"""
import datetime as dt
import io
import plistlib
import re
import secrets
import shutil
import time
import zipfile
from pathlib import Path

import lmdb

from . import config

LISTS = ("adminlist", "modlist", "blacklist", "whitelist")
# The first line of each list file is a comment the server ignores; these are the server's own (written when it
# creates a world; strings in the 1.7.1 binary), used when the portal writes a list for a world the server has not written yet.
LIST_HEADERS = {
    "adminlist": "Usernames in this file will be able to issue all server commands via chat, and pick up and remove "
                 "all objects. One username per line, non case sensitive. This first line is ignored.",
    "modlist": "Usernames in this file will be able to issue most server commands via chat. One username per line, "
               "non case sensitive. This first line is ignored.",
    "blacklist": "Usernames or IP addresses in this file will not be able to connect. One username or IP address per "
                 "line, non case sensitive. This first line is ignored.",
    "whitelist": "Only usernames or IP addresses in this file will be able to connect. One username or IP address per "
                 "line, non case sensitive. This first line is ignored.",
}
SIZES = {"1/16": 32, "1/4": 128, "1": 512, "4": 2048, "16": 8192}  # --world_width value -> worldWidthMacro
DAY_LENGTH = 3600.0  # worldTime units per day: the client's time of day is fmod(worldTime / 900 * 0.25, 1)
ID_RE = re.compile(r"^[0-9A-Za-z_-]{1,64}$")


class WorldError(Exception):
    pass


def path(world_id: str) -> Path:
    if not ID_RE.match(world_id):
        raise WorldError("Invalid world id.")
    return config.WORLDS / world_id


def new_id() -> str:
    while True:
        i = secrets.token_hex(16)
        if not (config.WORLDS / i).exists():
            return i


def exists(world_id: str) -> bool:
    try:
        return (path(world_id) / "world_db").is_dir()
    except WorldError:
        return False


def all_ids() -> list[str]:
    return sorted(p.name for p in config.WORLDS.iterdir() if (p / "world_db").is_dir()) if config.WORLDS.is_dir() \
        else []


# ---- LMDB / plist access ------------------------------------------------------------------------------------------

def _open(db_dir: Path, readonly: bool) -> lmdb.Environment:
    size = (db_dir / "data.mdb").stat().st_size if (db_dir / "data.mdb").exists() else 0
    return lmdb.open(str(db_dir), readonly=readonly, lock=True, max_dbs=64, subdir=True, create=False,
                     map_size=max(size * 2, 1 << 30))


def _load_plist(raw: bytes) -> tuple[dict, plistlib.PlistFormat]:
    fmt = plistlib.FMT_BINARY if raw.startswith(b"bplist") else plistlib.FMT_XML
    return plistlib.loads(raw), fmt


def read_record(world_id: str) -> dict:
    """world_db main/worldv2."""
    env = _open(path(world_id) / "world_db", readonly=True)
    try:
        with env.begin(db=env.open_db(b"main", create=False)) as t:
            raw = t.get(b"worldv2")
        if raw is None:
            raise WorldError("The world has no worldv2 record.")
        return _load_plist(raw)[0]
    finally:
        env.close()


def update_record(world_id: str, changes: dict) -> None:
    """Set keys of world_db main/worldv2 (and of the worldv2 summary file where it has them). Only while stopped."""
    p = path(world_id)
    env = _open(p / "world_db", readonly=False)
    try:
        db = env.open_db(b"main", create=False)
        with env.begin(db=db, write=True) as t:
            record, fmt = _load_plist(t.get(b"worldv2"))
            record.update(changes)
            t.put(b"worldv2", plistlib.dumps(record, fmt=fmt))
    finally:
        env.close()
    summary = p / "worldv2"
    if summary.exists():
        data = plistlib.loads(summary.read_bytes())
        touched = {k: v for k, v in changes.items() if k in data or k in ("worldName", "saveID")}
        if touched:
            data.update(touched)
            summary.write_bytes(plistlib.dumps(data, fmt=plistlib.FMT_XML))


def _date(v) -> str | None:
    if isinstance(v, dt.datetime):
        return (v if v.tzinfo else v.replace(tzinfo=dt.timezone.utc)).isoformat()
    return None


def info(world_id: str) -> dict:
    """Everything the world page shows."""
    r = read_record(world_id)
    width = r.get("worldWidthMacro")
    size = next((k for k, v in SIZES.items() if v == width), str(width))
    world_time = float(r.get("worldTime", 0) or 0)
    p = path(world_id)
    summary = plistlib.loads((p / "worldv2").read_bytes()) if (p / "worldv2").exists() else {}
    custom = r.get("customRulesDict", summary.get("customRulesDict"))
    return {
        "id": world_id,
        "name": r.get("worldName", summary.get("worldName", world_id)),
        "size": size,
        "expert": bool(r.get("expertMode", False)),
        "seed": r.get("randomSeed"),
        "customRules": custom if isinstance(custom, dict) else None,
        "created": _date(r.get("creationDate")),
        "saved": _date(r.get("saveDate")),
        "worldTime": world_time,
        "day": int(world_time // DAY_LENGTH) + 1,
        "port": r.get("hostPort"),
        "maxPlayers": r.get("maxPlayers"),
        "passwordSet": bool(r.get("serverPassword")),
        "pvp": not r.get("pvpDisabled", False),
        "welcomeMessage": r.get("welcomeMessage", ""),
        "diskBytes": sum(f.stat().st_size for f in p.rglob("*") if f.is_file()),
    }


def summary(world_id: str) -> dict:
    """A cheap summary for lists (the worldv2 file, falling back to the database record)."""
    p = path(world_id)
    try:
        s = plistlib.loads((p / "worldv2").read_bytes())
    except Exception:
        s = {}
    if "worldName" not in s:
        try:
            s = read_record(world_id)
        except Exception:
            s = {}
    width = s.get("worldWidthMacro")
    return {
        "id": world_id,
        "name": s.get("worldName", world_id),
        "size": next((k for k, v in SIZES.items() if v == width), str(width) if width else "?"),
        "expert": bool(s.get("expertMode", False)),
        "custom": bool(s.get("customRulesDict")),
        "created": _date(s.get("creationDate")),
    }


# ---- Player lists ---------------------------------------------------------------------------------------------------

def read_list(world_id: str, name: str) -> list[str]:
    f = path(world_id) / f"{name}.txt"
    if not f.exists():
        return []
    lines = f.read_text(errors="replace").splitlines()[1:]
    return [l.strip() for l in lines if l.strip()]


def write_list(world_id: str, name: str, entries: list[str]) -> None:
    f = path(world_id) / f"{name}.txt"
    header = f.read_text(errors="replace").splitlines()[0] if f.exists() and f.read_text().strip() \
        else LIST_HEADERS[name]
    clean = []
    for e in entries:
        e = e.strip()
        if e and "\n" not in e and e.lower() not in (c.lower() for c in clean):
            clean.append(e)
    f.write_text("\n".join([header] + clean) + "\n")


# ---- Copies -------------------------------------------------------------------------------------------------------

def unique_name(name: str) -> str:
    taken = {summary(i)["name"].upper() for i in all_ids()}
    if name.upper() not in taken:
        return name
    n = 2
    while f"{name} ({n})".upper() in taken:
        n += 1
    return f"{name} ({n})"


def _copy_lmdb(src: Path, dst: Path) -> None:
    """A consistent copy of an LMDB environment, safe while the server is writing it."""
    dst.mkdir(parents=True, exist_ok=True)
    env = _open(src, readonly=True)
    try:
        env.copy(str(dst), compact=True)
    finally:
        env.close()


def snapshot(world_id: str, dest: Path) -> None:
    """Copy a save folder to dest (a new directory), consistently even while its server runs."""
    src = path(world_id)
    dest.mkdir(parents=True)
    for item in src.iterdir():
        if item.is_dir() and (item / "data.mdb").exists():
            _copy_lmdb(item, dest / item.name)
        elif item.is_file():
            shutil.copy2(item, dest / item.name)


def clone(world_id: str, name: str | None = None) -> str:
    new = new_id()
    tmp = config.WORLDS / f".tmp-{new}"
    snapshot(world_id, tmp)
    tmp.rename(config.WORLDS / new)
    base = name or summary(world_id)["name"]
    update_record(new, {"saveID": new, "worldName": unique_name(base).upper()})
    return new


def export_zip(world_id: str) -> Path:
    """A .zip of a consistent copy of the save folder, its top directory named by the world id."""
    work = config.DATA / "tmp" / f"export-{secrets.token_hex(6)}"
    snapshot(world_id, work / world_id)
    out = work.with_suffix(".zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in (work / world_id).rglob("*"):
            if f.is_file() and f.name != "lock.mdb":
                z.write(f, f.relative_to(work))
    shutil.rmtree(work)
    return out


def import_zip(data: bytes) -> str:
    """Install an exported world. Keeps its id unless one exists already; then a new id and " (2)" on the name."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise WorldError("That is not a .zip file.")
    names = [n for n in z.namelist() if not n.endswith("/")]
    roots = {n.split("/")[0] for n in names}
    # Either <id>/world_db/... or the folder's contents at the top level.
    if len(roots) == 1 and any(n.split("/")[1:2] == ["world_db"] for n in names if "/" in n):
        root = roots.pop() + "/"
    elif any(n.startswith("world_db/") for n in names):
        root = ""
    else:
        raise WorldError("The .zip does not contain a Blockheads world (no world_db folder).")
    tmp = config.WORLDS / f".import-{secrets.token_hex(6)}"
    tmp.mkdir()
    try:
        for n in names:
            if not n.startswith(root):
                continue
            rel = Path(n[len(root):])
            if rel.is_absolute() or ".." in rel.parts or not rel.parts:
                raise WorldError("The .zip contains unsafe paths.")
            target = tmp / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(n) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
        env = _open(tmp / "world_db", readonly=True)
        try:
            with env.begin(db=env.open_db(b"main", create=False)) as t:
                record = _load_plist(t.get(b"worldv2"))[0]
        except Exception:
            raise WorldError("The world database in the .zip could not be read.")
        finally:
            env.close()
        wanted = str(record.get("saveID") or (root.rstrip("/") if root else ""))
        name = str(record.get("worldName", "IMPORTED WORLD"))
        if wanted and ID_RE.match(wanted) and not (config.WORLDS / wanted).exists():
            world_id = wanted
            tmp.rename(config.WORLDS / world_id)
        else:
            world_id = new_id()
            tmp.rename(config.WORLDS / world_id)
            update_record(world_id, {"saveID": world_id, "worldName": unique_name(name).upper()})
        return world_id
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


# ---- Trash --------------------------------------------------------------------------------------------------------

def to_trash(world_id: str) -> None:
    src = path(world_id)
    name = summary(world_id)["name"]
    dest = config.TRASH / f"{int(time.time())}-{world_id}"
    src.rename(dest)
    (dest / ".portal-trash").write_text(name)


def trash_items() -> list[dict]:
    out = []
    for d in sorted(config.TRASH.iterdir(), reverse=True) if config.TRASH.is_dir() else []:
        stamp, _, world_id = d.name.partition("-")
        if not stamp.isdigit():
            continue
        name = (d / ".portal-trash").read_text() if (d / ".portal-trash").exists() else world_id
        out.append({"key": d.name, "id": world_id, "name": name, "deleted": int(stamp),
                    "purge": int(stamp) + config.TRASH_DAYS * 86400})
    return out


def restore_from_trash(key: str) -> str:
    d = config.TRASH / key
    if "/" in key or not d.is_dir():
        raise WorldError("Not in the trash.")
    world_id = key.partition("-")[2]
    if (config.WORLDS / world_id).exists():
        raise WorldError("A world with that id exists already.")
    (d / ".portal-trash").unlink(missing_ok=True)
    d.rename(config.WORLDS / world_id)
    return world_id


def empty_trash(older_than: float | None = None) -> None:
    for item in trash_items():
        if older_than is None or item["deleted"] < older_than:
            shutil.rmtree(config.TRASH / item["key"], ignore_errors=True)
