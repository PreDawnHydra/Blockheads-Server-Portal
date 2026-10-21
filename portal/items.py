"""Item types, their names and their inventory icons, for the starting-item slots of custom rules.

data/items.json holds every ItemType of the 1.7.1 server (DWARF enum) with the name the 1.7.4 client shows and
where its icon is: a 16 px cell of a 32-column atlas — Items.png for sprite items, TileMap.png (a face of the cube
the game draws) for block items — at 4x in the HD atlases. data/spawn_item_menu.json is the client's starting-item
picker (CustomGameRulesUI): its categories, their items in order, and the slot rules.

At setup the icons are cropped from the user's own atlases into ASSETS/items/<id>.png.
"""
import json
from pathlib import Path

from PIL import Image

DATA = Path(__file__).resolve().parent / "data"
TABLE = json.loads((DATA / "items.json").read_text())
MENU = json.loads((DATA / "spawn_item_menu.json").read_text())
BY_ID = {i["id"]: i for i in TABLE}
DEFAULT_MARKER, EMPTY_MARKER = 2, 5
SINGLE_ONLY = {1, 12}  # the client forces count 1 for these (World -setCustomSlotAtIndex:)
MAX_COUNT = 99


def allowed_starting_item(item_type: int) -> bool:
    return item_type in (DEFAULT_MARKER, EMPTY_MARKER) or bool(BY_ID.get(item_type, {}).get("startingItemAllowed"))


def _atlas(root: Path, name: str) -> tuple[Image.Image, int] | None:
    """The HD atlas (64 px cells) if present, else the standard one (16 px)."""
    for path, scale in ((root / "GameResources" / "HDTex" / name, 4), (root / "GameResources" / name, 1)):
        if path.exists():
            return Image.open(path).convert("RGBA"), scale
    return None


def derive(root: Path) -> None:
    out = root / "items"
    out.mkdir(exist_ok=True)
    atlases = {}
    for item in TABLE:
        icon = item.get("icon")
        if not icon:
            continue
        name = icon["atlas"]
        if name not in atlases:
            atlases[name] = _atlas(root, name)
        if not atlases[name]:
            continue
        img, scale = atlases[name]
        x, y, w, h = (icon[k] * scale for k in ("x", "y", "w", "h"))
        cell = img.crop((x, y, x + w, y + h))
        if "overlayIndex" in icon:  # e.g. paint: the bucket with its (untinted) paint overlay
            o = icon["overlayIndex"]
            ox, oy = (o % 32) * 16 * scale, (o // 32) * 16 * scale
            cell.alpha_composite(img.crop((ox, oy, ox + w, oy + h)))
        cell.save(out / f"{item['id']}.png")
    listing = [{"id": i["id"], "name": i["name"], "icon": f"/game/items/{i['id']}.png" if i.get("icon") else None,
                "startingItem": bool(i.get("startingItemAllowed")), "category": i.get("startingItemCategory")}
               for i in TABLE]
    (root / "items.json").write_text(json.dumps({"items": listing, "menu": MENU["menu"]}))
