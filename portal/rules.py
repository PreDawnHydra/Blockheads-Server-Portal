"""World generation and gameplay rules for `--custom-rules`, as the 1.7.1 server and the 1.7.4 client define them.

The JSON is a flat object of rule name -> option string (CommandLineDelegate -init in the server, the same table in
the client's GameView). The server checks nothing — an unknown key is stored as is and bad JSON silently creates a
vanilla world — so the portal validates here.
"""

# (rule, options, default, expert-mode default when it differs)
RULES: list[tuple[str, list[str], str, str | None]] = [
    ("seed", ["random", "custom"], "random", None),
    ("oceans", ["no oceans", "small oceans", "normal", "large oceans", "ocean world"], "normal", None),
    ("temperature", ["very cold", "cold", "normal", "warm", "hot", "very hot"], "normal", None),
    ("rainfall", ["very dry", "dry", "normal", "wet", "very wet"], "normal", None),
    ("plants", ["no plants", "few plants", "normal", "more plants"], "normal", None),
    ("trees", ["no trees", "gem trees only", "sky island trees only", "few trees", "normal", "more trees"], "normal",
     None),
    ("terrain", ["totally flat", "quite flat", "normal", "mountainous"], "normal", None),
    ("caves", ["no caves", "normal", "more caves"], "normal", None),
    ("lakes", ["no lakes", "normal", "more lakes"], "normal", None),
    ("sky islands", ["no sky islands", "less sky islands", "normal", "more sky islands"], "normal", None),
    ("ore quantity", ["no ore", "less ore", "normal", "more ore"], "normal", None),
    ("ore distribution", ["small veins", "normal", "large veins"], "normal", None),
    ("gems", ["no gems", "less gems", "normal", "more gems"], "normal", None),
    ("treasure", ["no treasure", "less treasure", "normal", "more treasure"], "normal", None),
    ("health", ["one hit kill", "hard", "normal", "easy", "infinite health"], "normal", None),
    ("hunger", ["hungrier", "normal", "fuller", "always full"], "normal", None),
    ("happiness", ["sadder", "normal", "happier", "always happy"], "normal", None),
    ("clothing decay", ["no decay", "slower", "normal", "faster"], "normal", None),
    ("tool decay", ["no decay", "slower", "normal", "faster"], "normal", None),
    ("death", ["no death", "no RIP", "normal", "no regeneration", "die on exit"], "normal", None),
    ("death drops", ["all items", "some items", "no items"], "some items", "all items"),
    ("max blockheads", ["1", "2", "3", "4", "5"], "5", None),
    ("npc/mob difficulty", ["hard", "normal", "easy", "passive"], "normal", None),
    ("trade portals", ["normal", "disabled", "buy only", "sell only", "everything free", "jobs only"], "normal",
     None),
    ("trade prices", ["4x higher when buying", "10% higher when buying", "buy and sell prices equal"],
     "4x higher when buying", None),
    ("trade portal items", ["require discovery", "all items available"], "require discovery", None),
    ("day/night cycle", ["slower", "normal", "faster"], "normal", None),
    ("world modification", ["enabled", "admin only", "disabled"], "enabled", None),
    ("pole items", ["respawns, wears out", "one only", "lasts forever"], "respawns, wears out", None),
    ("teleportation", ["enabled", "requires diamond portal", "disabled"], "enabled", "requires diamond portal"),
    ("meditation", ["enabled", "disabled"], "enabled", "disabled"),
]
RULE_OPTIONS = {name: options for name, options, _, _ in RULES}
SUN_KEYS = ("sunColor_0", "sunColor_1", "sunColor_2")
SUN_DEFAULT = 127
SPAWN_SLOTS = 7


def schema() -> dict:
    return {
        "rules": [{"name": n, "options": o, "default": d, "expertDefault": e or d} for n, o, d, e in RULES],
        "sun": {"keys": list(SUN_KEYS), "default": SUN_DEFAULT},
        "spawnSlots": SPAWN_SLOTS,
    }


def validate(rules: dict) -> list[str]:
    """Problems with a custom rules object (empty when it is valid)."""
    if not isinstance(rules, dict):
        return ["Custom rules must be a JSON object."]
    errors = []
    for key, value in rules.items():
        if key in RULE_OPTIONS:
            if value not in RULE_OPTIONS[key]:
                errors.append(f'"{key}" must be one of: {", ".join(RULE_OPTIONS[key])}.')
        elif key == "custom_seed_value":
            if not isinstance(value, str) or not value:
                errors.append('"custom_seed_value" must be a non-empty string.')
        elif key in SUN_KEYS:
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 255:
                errors.append(f'"{key}" must be a whole number from 0 to 255.')
        elif key == "spawnItemSlots":
            if (not isinstance(value, list) or len(value) != SPAWN_SLOTS or not all(
                    isinstance(s, dict) and set(s) == {"type", "count"}
                    and all(isinstance(s[k], int) and not isinstance(s[k], bool) and s[k] >= 0 for k in s)
                    for s in value)):
                errors.append(f'"spawnItemSlots" must be {SPAWN_SLOTS} slots of {{"type": n, "count": n}}.')
            else:
                from . import items
                for n, s in enumerate(value, 1):
                    if not items.allowed_starting_item(s["type"]):
                        errors.append(f"Starting slot {n}: item {s['type']} cannot be a starting item.")
                    elif not 1 <= s["count"] <= items.MAX_COUNT:
                        errors.append(f"Starting slot {n}: the count must be 1 to {items.MAX_COUNT}.")
                    elif s["type"] in items.SINGLE_ONLY and s["count"] != 1:
                        errors.append(f"Starting slot {n}: that item can only start as 1.")
        else:
            errors.append(f'"{key}" is not a rule the server knows.')
    if rules.get("seed") == "custom" and "custom_seed_value" not in rules:
        errors.append('A custom seed needs "custom_seed_value".')
    return errors
