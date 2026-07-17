"""Prefix/suffix modifier lookup for rare items.

Sourced from Path of Building's static Mod*.lua data files (GGG's own mod
pool export, synced every patch) instead of scraping poedb.tw's per-item-type
pages. Each mod's `weightKey`/`weightVal` arrays are the real drop-weight
table GGG uses to decide which item bases a mod can roll on, which is more
precise than the ~70 hand-mapped poedb slugs this module used to rely on.
"""

import time

from scrapers.common import CACHE_TTL
from scrapers.pob_data import fetch_lua_file, parse_lua_table

_STANDARD = ("ModExplicit.lua", "ModCorrupted.lua")

# friendly name -> (data files to load, weightKey tags that make a mod eligible)
ITEM_TYPES: dict[str, tuple[tuple[str, ...], list[str]]] = {
    # One-Handed Weapons
    "claws": (_STANDARD, ["claw"]),
    "daggers": (_STANDARD, ["dagger"]),
    "rune daggers": (_STANDARD, ["dagger"]),
    "wands": (_STANDARD, ["wand"]),
    "one hand swords": (_STANDARD, ["sword"]),
    "thrusting one hand swords": (_STANDARD, ["sword", "rapier"]),
    "one hand axes": (_STANDARD, ["axe"]),
    "one hand maces": (_STANDARD, ["mace"]),
    "sceptres": (_STANDARD, ["sceptre"]),
    # Two-Handed Weapons
    "bows": (_STANDARD, ["bow"]),
    "staves": (_STANDARD, ["staff"]),
    "warstaves": (_STANDARD, ["staff"]),
    "two hand swords": (_STANDARD, ["sword"]),
    "two hand axes": (_STANDARD, ["axe"]),
    "two hand maces": (_STANDARD, ["mace"]),
    "fishing rods": (_STANDARD, ["fishing_rod"]),
    # Off-hand
    "quivers": (_STANDARD, ["quiver"]),
    # Jewellery
    "amulets": (_STANDARD, ["amulet"]),
    "rings": (_STANDARD, ["ring"]),
    "unset ring": (_STANDARD, ["ring", "unset_ring"]),
    "belts": (_STANDARD, ["belt"]),
    # Gloves
    "gloves str": (_STANDARD, ["gloves", "str_armour"]),
    "gloves dex": (_STANDARD, ["gloves", "dex_armour"]),
    "gloves int": (_STANDARD, ["gloves", "int_armour"]),
    "gloves str dex": (_STANDARD, ["gloves", "str_dex_armour"]),
    "gloves str int": (_STANDARD, ["gloves", "str_int_armour"]),
    "gloves dex int": (_STANDARD, ["gloves", "dex_int_armour"]),
    # Boots
    "boots str": (_STANDARD, ["boots", "str_armour"]),
    "boots dex": (_STANDARD, ["boots", "dex_armour"]),
    "boots int": (_STANDARD, ["boots", "int_armour"]),
    "boots str dex": (_STANDARD, ["boots", "str_dex_armour"]),
    "boots str int": (_STANDARD, ["boots", "str_int_armour"]),
    "boots dex int": (_STANDARD, ["boots", "dex_int_armour"]),
    # Body Armours
    "body armours str": (_STANDARD, ["body_armour", "str_armour"]),
    "body armours dex": (_STANDARD, ["body_armour", "dex_armour"]),
    "body armours int": (_STANDARD, ["body_armour", "int_armour"]),
    "body armours str dex": (_STANDARD, ["body_armour", "str_dex_armour"]),
    "body armours str int": (_STANDARD, ["body_armour", "str_int_armour"]),
    "body armours dex int": (_STANDARD, ["body_armour", "dex_int_armour"]),
    "body armours str dex int": (_STANDARD, ["body_armour", "str_dex_int_armour"]),
    # Helmets
    "helmets str": (_STANDARD, ["helmet", "str_armour"]),
    "helmets dex": (_STANDARD, ["helmet", "dex_armour"]),
    "helmets int": (_STANDARD, ["helmet", "int_armour"]),
    "helmets str dex": (_STANDARD, ["helmet", "str_dex_armour"]),
    "helmets str int": (_STANDARD, ["helmet", "str_int_armour"]),
    "helmets dex int": (_STANDARD, ["helmet", "dex_int_armour"]),
    # Shields
    "shields str": (_STANDARD, ["shield", "str_shield"]),
    "shields dex": (_STANDARD, ["shield", "dex_shield"]),
    "shields int": (_STANDARD, ["shield", "int_shield"]),
    "shields str dex": (_STANDARD, ["shield", "str_dex_shield"]),
    "shields str int": (_STANDARD, ["shield", "str_int_shield"]),
    "shields dex int": (_STANDARD, ["shield", "dex_int_shield"]),
    # Jewels — colour doesn't split the mod pool in-game, all regular jewels share one pool
    "crimson jewel": (("ModJewel.lua",), ["jewel"]),
    "viridian jewel": (("ModJewel.lua",), ["jewel"]),
    "cobalt jewel": (("ModJewel.lua",), ["jewel"]),
    "prismatic jewel": (("ModJewel.lua",), ["jewel"]),
    "murderous eye jewel": (("ModJewel.lua",), ["abyss_jewel"]),
    "searching eye jewel": (("ModJewel.lua",), ["abyss_jewel"]),
    "hypnotic eye jewel": (("ModJewel.lua",), ["abyss_jewel"]),
    "ghastly eye jewel": (("ModJewel.lua",), ["abyss_jewel"]),
    "large cluster jewel": (("ModJewelCluster.lua",), ["jewel"]),
    "medium cluster jewel": (("ModJewelCluster.lua",), ["jewel"]),
    "small cluster jewel": (("ModJewelCluster.lua",), ["jewel"]),
    # Flasks
    "life flasks": (("ModFlask.lua",), ["life_flask"]),
    "mana flasks": (("ModFlask.lua",), ["mana_flask"]),
    "utility flasks": (("ModFlask.lua",), ["utility_flask"]),
    "tinctures": (("ModTincture.lua",), ["tincture"]),
}

# Attribute name aliases for fuzzy resolution
_ATTR_ALIASES: dict[str, str] = {
    "strength": "str",
    "dexterity": "dex",
    "intelligence": "int",
    "str/dex": "str_dex",
    "str/int": "str_int",
    "dex/int": "dex_int",
    "str/dex/int": "str_dex_int",
}

# ---------------------------------------------------------------------------
# Cache — one entry per Lua data file
# ---------------------------------------------------------------------------

_file_cache: dict[str, tuple[float, dict]] = {}


def _load_file(filename: str) -> dict:
    cached = _file_cache.get(filename)
    if cached and (time.time() - cached[0]) < CACHE_TTL:
        return cached[1]
    text = fetch_lua_file(filename)
    data = parse_lua_table(text)
    _file_cache[filename] = (time.time(), data)
    return data


def _resolve_item_type(item_type: str) -> str | None:
    """Resolve user input to a key in ITEM_TYPES.

    Accepts exact friendly names, underscore/space variants, and attribute aliases
    (e.g. "helmets strength" -> "helmets str").
    """
    key = item_type.lower().strip().replace("_", " ")
    if key in ITEM_TYPES:
        return key

    normalized = key
    for alias, short in _ATTR_ALIASES.items():
        normalized = normalized.replace(alias, short)
    if normalized in ITEM_TYPES:
        return normalized

    matches = [name for name in ITEM_TYPES if key in name]
    if len(matches) == 1:
        return matches[0]
    if matches:
        for name in matches:
            if name.startswith(key):
                return name
        return matches[0]

    return None


def _get_mod_pool(category: str) -> tuple[list[dict], list[dict]]:
    """Return (normal, corrupted) mod entries eligible for a resolved category."""
    files, tags = ITEM_TYPES[category]
    tag_set = set(tags)

    normal = []
    corrupted = []
    for filename in files:
        data = _load_file(filename)
        for name, entry in data.items():
            if not isinstance(entry, dict):
                continue
            if not tag_set.intersection(entry.get("weightKey", [])):
                continue
            text = (entry.get("_array") or [""])[0]
            mod = {
                "name": name,
                "type": entry.get("type", ""),
                "affix": entry.get("affix", ""),
                "text": text,
                "level": entry.get("level", 0),
                "group": entry.get("group", ""),
            }
            if mod["type"] == "Corrupted":
                corrupted.append(mod)
            elif mod["type"] in ("Prefix", "Suffix"):
                normal.append(mod)

    return normal, corrupted


def _format_mod(mod: dict) -> str:
    lines = [f"- **{mod['group'] or mod['name']}** ({mod['type']}, iLvl {mod['level']})"]
    lines.append(f"  {mod['text']}")
    if mod["affix"]:
        lines.append(f"  Affix: \"{mod['affix']}\"")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public tool
# ---------------------------------------------------------------------------


def search_mods(item_type: str, query: str = "") -> str:
    """Search for Path of Exile item modifiers (prefix/suffix) by item type.

    Returns available prefixes and suffixes that can roll on the given item type.
    Optionally filter by keyword (e.g. "life", "fire resistance", "attack speed").

    Args:
        item_type: The item type to look up modifiers for.
                   Examples: "Helmets_str", "daggers", "amulets", "boots dex",
                   "body armours str int", "gloves dex", "cobalt jewel"
        query: Optional keyword to filter modifiers. If empty, returns a grouped overview.
    """
    category = _resolve_item_type(item_type)
    if not category:
        categories: dict[str, list[str]] = {}
        for friendly in ITEM_TYPES:
            cat = friendly.split()[0].title()
            categories.setdefault(cat, []).append(friendly)

        lines = [f"Unknown item type '{item_type}'. Valid types include:\n"]
        for cat, names in sorted(categories.items()):
            lines.append(f"**{cat}:** {', '.join(names[:5])}")
            if len(names) > 5:
                lines.append(f"  ... and {len(names) - 5} more")
        return "\n".join(lines)

    normal, corrupted = _get_mod_pool(category)
    display_name = category.title()

    if query:
        return _search_with_query(display_name, normal, corrupted, query)
    return _overview(display_name, category, normal, corrupted)


def _search_with_query(display_name: str, normal: list[dict], corrupted: list[dict], query: str) -> str:
    q = query.lower()

    def matches(mod: dict) -> bool:
        return q in mod["text"].lower() or q in mod["group"].lower() or q in mod["affix"].lower()

    prefixes = sorted((m for m in normal if m["type"] == "Prefix" and matches(m)), key=lambda m: m["level"])
    suffixes = sorted((m for m in normal if m["type"] == "Suffix" and matches(m)), key=lambda m: m["level"])
    corrupted_matches = sorted((m for m in corrupted if matches(m)), key=lambda m: m["level"])

    total = len(prefixes) + len(suffixes) + len(corrupted_matches)
    if total == 0:
        return f"No modifiers matching '{query}' found on {display_name}."

    lines = [f"## Modifiers matching '{query}' on {display_name} ({total} found)\n"]

    if prefixes:
        lines.append(f"### Prefixes ({len(prefixes)})\n")
        for mod in prefixes:
            lines.append(_format_mod(mod))
        lines.append("")

    if suffixes:
        lines.append(f"### Suffixes ({len(suffixes)})\n")
        for mod in suffixes:
            lines.append(_format_mod(mod))
        lines.append("")

    if corrupted_matches:
        lines.append(f"### Corrupted Implicits ({len(corrupted_matches)})\n")
        for mod in corrupted_matches:
            lines.append(_format_mod(mod))
        lines.append("")

    return "\n".join(lines)


def _overview(display_name: str, category: str, normal: list[dict], corrupted: list[dict]) -> str:
    prefixes: dict[str, list[dict]] = {}
    suffixes: dict[str, list[dict]] = {}

    for mod in normal:
        bucket = prefixes if mod["type"] == "Prefix" else suffixes
        bucket.setdefault(mod["group"] or "Unknown", []).append(mod)

    total_pre = sum(len(v) for v in prefixes.values())
    total_suf = sum(len(v) for v in suffixes.values())

    lines = [f"## {display_name} - Modifier Overview\n"]

    if prefixes:
        lines.append(f"### Prefixes ({total_pre} mods, {len(prefixes)} families)\n")
        for group in sorted(prefixes):
            mods = prefixes[group]
            levels = sorted(m["level"] for m in mods)
            lvl_range = f"iLvl {levels[0]}-{levels[-1]}" if len(levels) > 1 else f"iLvl {levels[0]}"
            lines.append(f"- **{group}** ({len(mods)}): {mods[0]['text']} ({lvl_range})")
        lines.append("")

    if suffixes:
        lines.append(f"### Suffixes ({total_suf} mods, {len(suffixes)} families)\n")
        for group in sorted(suffixes):
            mods = suffixes[group]
            levels = sorted(m["level"] for m in mods)
            lvl_range = f"iLvl {levels[0]}-{levels[-1]}" if len(levels) > 1 else f"iLvl {levels[0]}"
            lines.append(f"- **{group}** ({len(mods)}): {mods[0]['text']} ({lvl_range})")
        lines.append("")

    if corrupted:
        lines.append(f"### Corrupted Implicits ({len(corrupted)} mods)\n")
        for mod in corrupted[:10]:
            lines.append(f"- {mod['text']}")
        if len(corrupted) > 10:
            lines.append(f"- ... and {len(corrupted) - 10} more")
        lines.append("")

    lines.append(f"Use `search_mods(\"{category}\", \"keyword\")` to filter by specific mod.")
    return "\n".join(lines)
