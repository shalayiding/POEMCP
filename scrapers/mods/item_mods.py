"""Prefix/suffix modifier lookup for rare items from poedb.tw."""

import json
import re
import time

import httpx

from scrapers.common import BASE_URL, CACHE_TTL, HEADERS

# ---------------------------------------------------------------------------
# Slug mapping — friendly name → poedb URL slug
# ---------------------------------------------------------------------------

ITEM_TYPE_SLUGS: dict[str, str] = {
    # One-Handed Weapons
    "claws": "Claws",
    "daggers": "Daggers",
    "wands": "Wands",
    "one hand swords": "One_Hand_Swords",
    "one hand axes": "One_Hand_Axes",
    "one hand maces": "One_Hand_Maces",
    "sceptres": "Sceptres",
    "rune daggers": "Rune_Daggers",
    "thrusting one hand swords": "Thrusting_One_Hand_Swords",
    # Two-Handed Weapons
    "bows": "Bows",
    "staves": "Staves",
    "two hand swords": "Two_Hand_Swords",
    "two hand axes": "Two_Hand_Axes",
    "two hand maces": "Two_Hand_Maces",
    "warstaves": "Warstaves",
    "fishing rods": "Fishing_Rods",
    # Jewellery
    "amulets": "Amulets",
    "rings": "Rings",
    "belts": "Belts",
    "trinkets": "Trinkets",
    # Gloves
    "gloves str": "Gloves_str",
    "gloves dex": "Gloves_dex",
    "gloves int": "Gloves_int",
    "gloves str dex": "Gloves_str_dex",
    "gloves str int": "Gloves_str_int",
    "gloves dex int": "Gloves_dex_int",
    # Boots
    "boots str": "Boots_str",
    "boots dex": "Boots_dex",
    "boots int": "Boots_int",
    "boots str dex": "Boots_str_dex",
    "boots str int": "Boots_str_int",
    "boots dex int": "Boots_dex_int",
    # Body Armours
    "body armours str": "Body_Armours_str",
    "body armours dex": "Body_Armours_dex",
    "body armours int": "Body_Armours_int",
    "body armours str dex": "Body_Armours_str_dex",
    "body armours str int": "Body_Armours_str_int",
    "body armours dex int": "Body_Armours_dex_int",
    "body armours str dex int": "Body_Armours_str_dex_int",
    # Helmets
    "helmets str": "Helmets_str",
    "helmets dex": "Helmets_dex",
    "helmets int": "Helmets_int",
    "helmets str dex": "Helmets_str_dex",
    "helmets str int": "Helmets_str_int",
    "helmets dex int": "Helmets_dex_int",
    # Shields
    "shields str": "Shields_str",
    "shields dex": "Shields_dex",
    "shields int": "Shields_int",
    "shields str dex": "Shields_str_dex",
    "shields str int": "Shields_str_int",
    "shields dex int": "Shields_dex_int",
    # Off-hand
    "quivers": "Quivers",
    # Jewels
    "crimson jewel": "Crimson_Jewel",
    "viridian jewel": "Viridian_Jewel",
    "cobalt jewel": "Cobalt_Jewel",
    "prismatic jewel": "Prismatic_Jewel",
    "murderous eye jewel": "Murderous_Eye_Jewel",
    "searching eye jewel": "Searching_Eye_Jewel",
    "hypnotic eye jewel": "Hypnotic_Eye_Jewel",
    "ghastly eye jewel": "Ghastly_Eye_Jewel",
    "timeless jewel": "Timeless_Jewel",
    "large cluster jewel": "Large_Cluster_Jewel",
    "medium cluster jewel": "Medium_Cluster_Jewel",
    "small cluster jewel": "Small_Cluster_Jewel",
    # Flasks
    "life flasks": "Life_Flasks",
    "mana flasks": "Mana_Flasks",
    "utility flasks": "Utility_Flasks",
    "tinctures": "Tinctures",
    # Special items
    "unset ring": "Unset_Ring",
    "bone ring": "Bone_Ring",
    "convoking wand": "Convoking_Wand",
    "bone spirit shield": "Bone_Spirit_Shield",
    "runic crown": "Runic_Crown",
    "runic sabatons": "Runic_Sabatons",
    "runic gauntlets": "Runic_Gauntlets",
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
# Cache — one entry per slug
# ---------------------------------------------------------------------------

_mod_cache: dict[str, tuple[float, dict]] = {}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MOD_JSON_RE = re.compile(r"new\s+ModsView\s*\(\s*(\{.*?\})\s*\)\s*;?\s*\}", re.DOTALL)


def _clean_mod_text(html_str: str) -> str:
    """Strip HTML tags from a mod's 'str' field, returning plain text."""
    return _HTML_TAG_RE.sub("", html_str).strip()


def _resolve_item_type(item_type: str) -> str | None:
    """Resolve user input to a valid poedb URL slug.

    Accepts:
      - Exact slug: "Helmets_str"
      - Lowercase friendly: "helmets str", "daggers"
      - Attribute aliases: "helmets strength" → "Helmets_str"
    """
    # Direct slug match (case-insensitive)
    for slug in ITEM_TYPE_SLUGS.values():
        if item_type.lower().replace(" ", "_") == slug.lower():
            return slug

    # Friendly name match
    key = item_type.lower().strip()
    if key in ITEM_TYPE_SLUGS:
        return ITEM_TYPE_SLUGS[key]

    # Try replacing attribute aliases
    normalized = key
    for alias, short in _ATTR_ALIASES.items():
        normalized = normalized.replace(alias, short)
    if normalized in ITEM_TYPE_SLUGS:
        return ITEM_TYPE_SLUGS[normalized]

    # Partial / substring match — pick best
    matches = []
    for friendly, slug in ITEM_TYPE_SLUGS.items():
        if key in friendly or key in slug.lower():
            matches.append((friendly, slug))

    if len(matches) == 1:
        return matches[0][1]
    if matches:
        # Prefer exact word boundary matches
        for friendly, slug in matches:
            if friendly.startswith(key) or slug.lower().startswith(key.replace(" ", "_")):
                return slug
        return matches[0][1]

    return None


def _fetch_mods(slug: str) -> dict:
    """Fetch modifier JSON for an item type slug. Returns parsed dict with 'normal' and 'corrupted' arrays."""
    # Check cache
    if slug in _mod_cache:
        ts, data = _mod_cache[slug]
        if time.time() - ts < CACHE_TTL:
            return data

    url = f"{BASE_URL}/{slug}"
    resp = httpx.get(url, headers=HEADERS, follow_redirects=True, timeout=30)
    resp.raise_for_status()
    text = resp.text.replace("\u2014", "-")

    # Extract JSON from new ModsView({...})
    match = _MOD_JSON_RE.search(text)
    if not match:
        raise ValueError(f"Could not find ModsView JSON data on {url}")

    raw_json = match.group(1)
    data = json.loads(raw_json)

    result = {
        "normal": data.get("normal", []),
        "corrupted": data.get("corrupted", []),
    }

    _mod_cache[slug] = (time.time(), result)
    return result


def _format_mod(mod: dict) -> str:
    """Format a single modifier entry into readable text."""
    gen_id = mod.get("ModGenerationTypeID", "")
    if gen_id == "1":
        mod_type = "Prefix"
    elif gen_id == "2":
        mod_type = "Suffix"
    elif gen_id == "5":
        mod_type = "Corrupted"
    else:
        mod_type = f"Type {gen_id}"

    name = mod.get("Name", "?")
    level = mod.get("Level", "?")
    text = _clean_mod_text(mod.get("str", ""))
    families = ", ".join(mod.get("ModFamilyList", []))

    lines = [f"- **{name}** ({mod_type}, iLvl {level})"]
    lines.append(f"  {text}")
    if families:
        lines.append(f"  Mod family: {families}")
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
    slug = _resolve_item_type(item_type)
    if not slug:
        # Build a helpful list of valid types
        categories: dict[str, list[str]] = {}
        for friendly in ITEM_TYPE_SLUGS:
            cat = friendly.split()[0].title()
            categories.setdefault(cat, []).append(friendly)

        lines = [f"Unknown item type '{item_type}'. Valid types include:\n"]
        for cat, names in sorted(categories.items()):
            lines.append(f"**{cat}:** {', '.join(names[:5])}")
            if len(names) > 5:
                lines.append(f"  ... and {len(names) - 5} more")
        return "\n".join(lines)

    try:
        data = _fetch_mods(slug)
    except (httpx.HTTPStatusError, ValueError) as e:
        return f"Error fetching modifiers for '{slug}': {e}"

    normal = data["normal"]
    corrupted = data["corrupted"]

    display_name = slug.replace("_", " ")

    if query:
        return _search_with_query(display_name, normal, corrupted, query)
    else:
        return _overview(display_name, slug, normal, corrupted)


def _search_with_query(
    display_name: str,
    normal: list[dict],
    corrupted: list[dict],
    query: str,
) -> str:
    """Filter mods by keyword and return matching prefixes/suffixes."""
    q = query.lower()

    prefixes = []
    suffixes = []
    corrupted_matches = []

    for mod in normal:
        text = _clean_mod_text(mod.get("str", "")).lower()
        families = " ".join(mod.get("ModFamilyList", [])).lower()
        name = mod.get("Name", "").lower()
        if q in text or q in families or q in name:
            gen_id = mod.get("ModGenerationTypeID", "")
            if gen_id == "1":
                prefixes.append(mod)
            elif gen_id == "2":
                suffixes.append(mod)

    for mod in corrupted:
        text = _clean_mod_text(mod.get("str", "")).lower()
        families = " ".join(mod.get("ModFamilyList", [])).lower()
        if q in text or q in families:
            corrupted_matches.append(mod)

    # Sort by level
    prefixes.sort(key=lambda m: int(m.get("Level", "0")))
    suffixes.sort(key=lambda m: int(m.get("Level", "0")))
    corrupted_matches.sort(key=lambda m: int(m.get("Level", "0")))

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

    lines.append(f"Source: {BASE_URL}/{display_name.replace(' ', '_')}#ModifiersCalc")
    return "\n".join(lines)


def _overview(
    display_name: str,
    slug: str,
    normal: list[dict],
    corrupted: list[dict],
) -> str:
    """Return a grouped overview of all mods for an item type."""
    prefixes: dict[str, list[dict]] = {}
    suffixes: dict[str, list[dict]] = {}

    for mod in normal:
        gen_id = mod.get("ModGenerationTypeID", "")
        families = mod.get("ModFamilyList", [])
        family = families[0] if families else "Unknown"
        if gen_id == "1":
            prefixes.setdefault(family, []).append(mod)
        elif gen_id == "2":
            suffixes.setdefault(family, []).append(mod)

    total_pre = sum(len(v) for v in prefixes.values())
    total_suf = sum(len(v) for v in suffixes.values())

    lines = [f"## {display_name} - Modifier Overview\n"]

    if prefixes:
        lines.append(f"### Prefixes ({total_pre} mods, {len(prefixes)} families)\n")
        for family in sorted(prefixes):
            mods = prefixes[family]
            levels = sorted(int(m.get("Level", "0")) for m in mods)
            sample = _clean_mod_text(mods[0].get("str", ""))
            lvl_range = f"iLvl {levels[0]}-{levels[-1]}" if len(levels) > 1 else f"iLvl {levels[0]}"
            lines.append(f"- **{family}** ({len(mods)}): {sample} ({lvl_range})")
        lines.append("")

    if suffixes:
        lines.append(f"### Suffixes ({total_suf} mods, {len(suffixes)} families)\n")
        for family in sorted(suffixes):
            mods = suffixes[family]
            levels = sorted(int(m.get("Level", "0")) for m in mods)
            sample = _clean_mod_text(mods[0].get("str", ""))
            lvl_range = f"iLvl {levels[0]}-{levels[-1]}" if len(levels) > 1 else f"iLvl {levels[0]}"
            lines.append(f"- **{family}** ({len(mods)}): {sample} ({lvl_range})")
        lines.append("")

    if corrupted:
        lines.append(f"### Corrupted Implicits ({len(corrupted)} mods)\n")
        for mod in corrupted[:10]:
            text = _clean_mod_text(mod.get("str", ""))
            lines.append(f"- {text}")
        if len(corrupted) > 10:
            lines.append(f"- ... and {len(corrupted) - 10} more")
        lines.append("")

    lines.append(f"Use `search_mods(\"{slug}\", \"keyword\")` to filter by specific mod.\n")
    lines.append(f"Source: {BASE_URL}/{slug}#ModifiersCalc")
    return "\n".join(lines)
