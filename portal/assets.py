"""The theme's game assets, extracted from the user's own copy of The Blockheads for Android (the APK).

Nothing from the game ships with the portal: on first run the user uploads their APK and this copies the images,
fonts and sounds the theme uses into ASSETS, then derives the cut-outs the pages need (item icons) as the game
itself does.
"""
import json
import shutil
import zipfile
from pathlib import Path

from . import config

# Files that identify the APK as The Blockheads.
REQUIRED = ("assets/GameResources/Items.png", "assets/GameResources/Fonts/Blockheads_64.fnt", "assets/Info.plist")
# What is copied: (prefix inside the APK, suffixes). Kept to the folders the theme draws from.
COPY = [
    ("assets/GameResources/", (".png", ".fnt", ".wav", ".otf", ".TTF")),
    ("assets/GameResources/Fonts/", (".png", ".fnt", ".otf", ".TTF")),
    ("assets/GameResources/HDTex/Items.png", ()),
    ("assets/", (".png", ".otf")),
]
VERSION = 1  # bump when the extraction changes, so existing installs re-extract from a fresh upload


def status() -> dict:
    marker = config.ASSETS / "extracted.json"
    if not marker.exists():
        return {"ready": False}
    info = json.loads(marker.read_text())
    return {"ready": info.get("version") == VERSION, "source": info.get("source"), "files": info.get("files")}


def _wanted(name: str) -> str | None:
    """The path under ASSETS a file of the APK is copied to, or None."""
    for prefix, suffixes in COPY:
        if not name.startswith(prefix):
            continue
        rest = name[len(prefix):]
        if not suffixes:
            return rest if rest and "/" not in rest else name[len("assets/"):]
        if "/" in rest or not rest.endswith(suffixes):
            continue
        return name[len("assets/"):]
    return None


def extract(apk: Path, source_name: str | None = None) -> dict:
    try:
        z = zipfile.ZipFile(apk)
    except zipfile.BadZipFile:
        raise ValueError("That is not an APK (not a zip file).")
    names = set(z.namelist())
    missing = [r for r in REQUIRED if r not in names]
    if missing:
        raise ValueError("That APK is not The Blockheads (missing " + ", ".join(missing) + ").")
    staging = config.DATA / "tmp" / "assets"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    count = 0
    for name in sorted(names):
        target = _wanted(name)
        if not target:
            continue
        out = staging / target
        out.parent.mkdir(parents=True, exist_ok=True)
        with z.open(name) as src, open(out, "wb") as dst:
            shutil.copyfileobj(src, dst)
        count += 1
    # The game's launcher icon (one 512 px image) as the portal's favicon.
    if "res/drawable-xxhdpi-v4/icon.png" in names:
        with z.open("res/drawable-xxhdpi-v4/icon.png") as src, open(staging / "icon.png", "wb") as dst:
            shutil.copyfileobj(src, dst)
    derive(staging)
    (staging / "extracted.json").write_text(json.dumps({"version": VERSION, "source": source_name or apk.name, "files": count}))
    old = config.ASSETS.with_name("assets.old")
    shutil.rmtree(old, ignore_errors=True)
    if config.ASSETS.exists():
        config.ASSETS.rename(old)
    staging.rename(config.ASSETS)
    shutil.rmtree(old, ignore_errors=True)
    return status()


def derive(root: Path) -> None:
    """Cut-outs computed from the copied files (item icons); see items.py."""
    from . import items as item_table
    item_table.derive(root)


def items() -> dict:
    f = config.ASSETS / "items.json"
    return json.loads(f.read_text()) if f.exists() else {"items": [], "menu": []}
