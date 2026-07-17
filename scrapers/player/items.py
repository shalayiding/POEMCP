import re

import httpx

from scrapers.common import HEADERS, Cache

_item_cache: Cache[list[dict]] = Cache()

PATHOFBUILDING_RAW = (
    "https://raw.githubusercontent.com/PathOfBuildingCommunity/PathOfBuilding/dev/src/Data/Uniques"
)

# Files containing plain item-text blocks (`[[ ... ]]`).
# Excludes Special/Generated.lua, Special/WatchersEye.lua, Special/BoundByDestiny.lua —
# those store procedural mod pools in a different Lua structure, not item text.
UNIQUE_DATA_FILES = [
    "amulet.lua", "axe.lua", "belt.lua", "body.lua", "boots.lua", "bow.lua",
    "claw.lua", "dagger.lua", "fishing.lua", "flask.lua", "gloves.lua", "graft.lua",
    "helmet.lua", "jewel.lua", "mace.lua", "quiver.lua", "ring.lua", "shield.lua",
    "staff.lua", "sword.lua", "tincture.lua", "wand.lua",
    "Special/New.lua", "Special/race.lua",
]

# Metadata line prefixes to skip while scanning toward "Implicits:".
_SKIP_PREFIXES = (
    "Variant:", "League:", "Source:", "Requires Level", "LevelReq:",
    "Unique ID:", "Item Level:", "Quality:", "Sockets:", "Selling Price:",
    "Radius:", "Limited to:", "Has Alt Variant", "Show Alt Variant",
)

_ITEM_BLOCK_RE = re.compile(r"\[\[(.*?)\]\]", re.DOTALL)
_VARIANT_TAG_RE = re.compile(r"\{variant:([\d,]+)\}")
_ANNOTATION_RE = re.compile(r"\{[^}]*\}")


def _clean_mod(text: str) -> str:
    return _ANNOTATION_RE.sub("", text).strip()


def _parse_item_block(block: str) -> dict | None:
    lines = [l.strip() for l in block.strip().splitlines() if l.strip()]
    if len(lines) < 2:
        return None

    name = lines[0]
    base_type = lines[1]
    i = 2

    variants = []
    while i < len(lines) and lines[i].startswith("Variant:"):
        variants.append(lines[i].removeprefix("Variant:").strip())
        i += 1

    # Skip remaining metadata lines until "Implicits:"
    while i < len(lines) and not lines[i].startswith("Implicits:"):
        i += 1

    implicits = []
    if i < len(lines) and lines[i].startswith("Implicits:"):
        try:
            n = int(lines[i].removeprefix("Implicits:").strip())
        except ValueError:
            n = 0
        i += 1
        for _ in range(n):
            if i < len(lines):
                implicits.append(_clean_mod(lines[i]))
                i += 1

    current_variant = len(variants) if variants else None
    explicits = []
    for line in lines[i:]:
        m = _VARIANT_TAG_RE.search(line)
        if m and current_variant is not None:
            applies_to = {int(v) for v in m.group(1).split(",")}
            if current_variant not in applies_to:
                continue
        explicits.append(_clean_mod(line))

    return {
        "name": name,
        "base_type": base_type,
        "implicits": implicits,
        "explicits": explicits,
    }


def _get_all_items() -> list[dict]:
    """Fetch and parse Path of Building's unique item data files (GGG's own game data export)."""
    cached = _item_cache.get()
    if cached is not None:
        return cached

    items = []
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30) as client:
        for filename in UNIQUE_DATA_FILES:
            try:
                resp = client.get(f"{PATHOFBUILDING_RAW}/{filename}")
                resp.raise_for_status()
            except httpx.HTTPError:
                continue
            for match in _ITEM_BLOCK_RE.finditer(resp.text):
                item = _parse_item_block(match.group(1))
                if item:
                    items.append(item)

    _item_cache.set(items)
    return items


def _fuzzy_score(query: str, item: dict) -> int:
    """Score an item against a search query. Higher = better match. 0 = no match."""
    q = query.lower()
    name_l = item["name"].lower()
    base_l = item["base_type"].lower()
    all_mods_l = " ".join(item["implicits"] + item["explicits"]).lower()

    if name_l == q:
        return 100
    if name_l.startswith(q):
        return 80
    if q in name_l:
        return 60

    words = q.split()
    if len(words) > 1 and all(w in name_l for w in words):
        return 50
    if q in base_l:
        return 40

    combined = f"{name_l} {base_l}"
    if all(w in combined for w in words):
        return 35
    if q in all_mods_l:
        return 20

    everything = f"{combined} {all_mods_l}"
    if all(w in everything for w in words):
        return 10

    return 0


def _format_item(item: dict) -> str:
    lines = [f"# {item['name']}"]
    lines.append(f"**Base type:** {item['base_type']}")
    lines.append("")
    if item["implicits"]:
        lines.append("**Implicit:**")
        for mod in item["implicits"]:
            lines.append(f"- {mod}")
        lines.append("")
    if item["explicits"]:
        lines.append("**Explicit:**")
        for mod in item["explicits"]:
            lines.append(f"- {mod}")
        lines.append("")
    return "\n".join(lines)


def search_item(query: str) -> str:
    """Search for Path of Exile unique items by name, base type, or mod keyword.

    Supports fuzzy matching — partial names, base types, and mod text all work.
    Examples: "headhunter", "leather belt", "culling strike", "life leech dagger"

    Args:
        query: Search keyword(s) to match against item names, base types, and mods.
    """
    items = _get_all_items()

    matches = []
    for item in items:
        score = _fuzzy_score(query, item)
        if score > 0:
            matches.append((score, item))

    matches.sort(key=lambda x: (-x[0], x[1]["name"]))

    if not matches:
        return f"No items found matching '{query}'."

    lines = [f"Found {len(matches)} item(s) matching '{query}':\n"]
    for score, item in matches[:20]:
        lines.append(f"- **{item['name']}** ({item['base_type']})")
        for mod in item["explicits"][:3]:
            lines.append(f"  - {mod}")
        if len(item["explicits"]) > 3:
            lines.append(f"  - ... and {len(item['explicits']) - 3} more mods")
        lines.append("")

    if len(matches) > 20:
        lines.append(f"... and {len(matches) - 20} more results.")

    return "\n".join(lines)


def get_item_detail(item_name: str) -> str:
    """Get detailed information about a specific Path of Exile item.

    Args:
        item_name: The item name, e.g. "Headhunter" or "Lifesprig".
    """
    items = _get_all_items()
    query_lower = item_name.lower()

    match = None
    for item in items:
        if item["name"].lower() == query_lower:
            match = item
            break

    if not match:
        for item in items:
            if query_lower in item["name"].lower():
                match = item
                break

    if not match:
        return f"Could not find item '{item_name}'. Try search_item to find the correct name."

    return _format_item(match)
