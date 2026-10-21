"""World backups: .zip files of consistent save-folder copies under BACKUPS/<world id>/.

Taken on a per-server schedule (kept to the newest `keep`) and automatically before every risky action (delete,
import over, rule change, world database edit, restore). Automatic ones are kept apart from the scheduled count but
pruned after 30 days.
"""
import calendar
import shutil
import time
import zipfile
from pathlib import Path

from . import config, worlds
from .hub import hub

AUTO_KEEP_SECONDS = 30 * 86400


def folder(world_id: str) -> Path:
    worlds.path(world_id)  # validates the id
    return config.BACKUPS / world_id


def create(world_id: str, reason: str) -> dict:
    """reason: "scheduled", "manual" or what it precedes ("before-delete", ...)."""
    out_dir = folder(world_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    zipped = worlds.export_zip(world_id)
    target = out_dir / f"{stamp}-{reason}.zip"
    shutil.move(zipped, target)
    return describe(target)


def describe(f: Path) -> dict:
    # <YYYYmmdd>-<HHMMSS>-<reason>.zip, UTC
    reason = f.stem.split("-", 2)[-1]
    t = calendar.timegm(time.strptime(f.stem[:15], "%Y%m%d-%H%M%S"))
    return {"file": f.name, "time": t, "reason": reason, "bytes": f.stat().st_size}


def listing(world_id: str) -> list[dict]:
    d = folder(world_id)
    return sorted((describe(f) for f in d.glob("*.zip")), key=lambda b: b["time"], reverse=True) if d.is_dir() \
        else []


def file(world_id: str, name: str) -> Path:
    f = folder(world_id) / name
    if "/" in name or not f.is_file():
        raise worlds.WorldError("No such backup.")
    return f


def prune(world_id: str, keep: int) -> None:
    now = time.time()
    scheduled = [b for b in listing(world_id) if b["reason"] == "scheduled"]
    for b in scheduled[keep:]:
        (folder(world_id) / b["file"]).unlink(missing_ok=True)
    for b in listing(world_id):
        if b["reason"] not in ("scheduled", "manual") and now - b["time"] > AUTO_KEEP_SECONDS:
            (folder(world_id) / b["file"]).unlink(missing_ok=True)


def safe_create(world_id: str, reason: str) -> dict | None:
    try:
        return create(world_id, reason)
    except Exception as e:
        hub.notify(world_id, "backupFailed", f"Backup of {world_id} failed: {e}")
        return None


def restore(world_id: str, name: str) -> None:
    """Replace a (stopped) world's save folder with a backup; the current state is backed up first."""
    src = file(world_id, name)
    create(world_id, "before-restore")
    target = worlds.path(world_id)
    work = config.DATA / "tmp" / f"restore-{world_id}-{int(time.time())}"
    work.mkdir(parents=True)
    try:
        with zipfile.ZipFile(src) as z:
            for n in z.namelist():
                rel = Path(n)
                if rel.is_absolute() or ".." in rel.parts:
                    raise worlds.WorldError("The backup contains unsafe paths.")
            z.extractall(work)
        restored = work / world_id
        if not (restored / "world_db").is_dir():
            raise worlds.WorldError("The backup does not contain this world.")
        old = work / "old"
        target.rename(old)
        restored.rename(target)
    finally:
        shutil.rmtree(work, ignore_errors=True)
