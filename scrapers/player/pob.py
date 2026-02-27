import base64
import zlib
import xml.etree.ElementTree as ET

import httpx

from scrapers.common import HEADERS

# Stats worth showing in the summary
_KEY_STATS = {
    "Life": "Life",
    "Mana": "Mana",
    "EnergyShield": "Energy Shield",
    "Armour": "Armour",
    "Evasion": "Evasion",
    "Ward": "Ward",
    "TotalDPS": "Total DPS",
    "AverageDamage": "Avg Damage",
    "Speed": "Attacks/Casts per Second",
    "HitChance": "Hit Chance",
}

# Slot display order (using real PoB slot names)
_SLOT_ORDER = [
    "Helmet", "Amulet", "Weapon 1", "Weapon 2", "Body Armour",
    "Gloves", "Belt", "Boots", "Ring 1", "Ring 2",
    "Flask 1", "Flask 2", "Flask 3", "Flask 4", "Flask 5",
    "Graft 1", "Graft 2",
    "Weapon 1 Swap", "Weapon 2 Swap",
]

# Item text metadata lines to skip (not mods)
_SKIP_PREFIXES = (
    "Unique ID:", "Item Level:", "LevelReq:", "Quality:", "Sockets:",
    "Energy Shield:", "EnergyShieldBasePercentile:",
    "Armour:", "ArmourBasePercentile:",
    "Evasion:", "EvasionBasePercentile:",
    "Ward:", "WardBasePercentile:",
    "Physical Damage:", "Elemental Damage:", "Chaos Damage:",
    "Critical Strike Chance:", "Attacks per Second:", "Weapon Range:",
    "Stack Size:", "Hunter Item", "Crusader Item", "Redeemer Item",
    "Warlord Item", "Elder Item", "Shaper Item", "Synthesised Item",
)

# Mod annotation prefixes added by PoB
_MOD_TAGS = ("{crafted}", "{mutated}", "{enchant}", "{fractured}", "{scourge}")


def _fetch_raw(url: str) -> str:
    """Resolve a share URL to a raw PoB base64 code string."""
    url = url.strip().rstrip("/")

    if "pobb.in" in url:
        # https://pobb.in/{id}            → https://pobb.in/{id}/raw
        # https://pobb.in/u/{user}/{id}   → https://pobb.in/u/{user}/{id}/raw
        raw_url = url + "/raw"
    elif "pastebin.com" in url:
        # https://pastebin.com/{id} → https://pastebin.com/raw/{id}
        paste_id = url.rstrip("/").split("/")[-1]
        raw_url = f"https://pastebin.com/raw/{paste_id}"
    else:
        raise ValueError("Unsupported URL. Supported: pobb.in, pastebin.com")

    resp = httpx.get(raw_url, headers=HEADERS, follow_redirects=True, timeout=30)
    resp.raise_for_status()
    return resp.text.strip()


def _decode_pob(code: str) -> ET.Element:
    """Decode a PoB base64 export string → XML root element."""
    rem = len(code) % 4
    if rem:
        code += "=" * (4 - rem)
    try:
        data = base64.urlsafe_b64decode(code)
        xml_bytes = zlib.decompress(data)
        return ET.fromstring(xml_bytes)
    except Exception as e:
        raise ValueError(f"Could not decode PoB code: {e}")


def _clean_mod(mod: str) -> str:
    """Strip PoB annotation tags like {crafted}, {mutated} from mod text."""
    for tag in _MOD_TAGS:
        if mod.startswith(tag):
            mod = mod[len(tag):]
    return mod.strip()


def _parse_build_info(root: ET.Element) -> dict:
    build = root.find("Build")
    if build is None:
        return {}

    info = {
        "class": build.get("className", "Unknown"),
        "ascendancy": build.get("ascendClassName", ""),
        "level": build.get("level", "?"),
        "bandit": build.get("bandit", ""),
        "pantheon_major": build.get("pantheonMajorGod", ""),
        "pantheon_minor": build.get("pantheonMinorGod", ""),
    }

    stats = {}
    for stat in build.findall("PlayerStat"):
        key = stat.get("stat", "")
        if key in _KEY_STATS:
            try:
                stats[key] = float(stat.get("value", "0"))
            except ValueError:
                pass
    info["stats"] = stats
    return info


def _parse_skills(root: ET.Element) -> list[dict]:
    skills_el = root.find("Skills")
    if skills_el is None:
        return []

    groups = []
    for skill in skills_el.findall("Skill"):
        if skill.get("enabled", "true").lower() == "false":
            continue

        gems = []
        for gem in skill.findall("Gem"):
            if gem.get("enabled", "true").lower() == "false":
                continue
            name = gem.get("skillId") or gem.get("nameSpec", "")
            if name:
                gems.append({
                    "name": name,
                    "level": gem.get("level", ""),
                    "quality": gem.get("quality", "0"),
                })

        if gems:
            groups.append({
                "slot": skill.get("slot", ""),
                "label": skill.get("label", ""),
                "gems": gems,
            })

    return groups


def _parse_item_text(text: str) -> dict:
    """Parse a PoB item text block (no --- separators, uses Implicits: N)."""
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    result = {"rarity": "", "name": "", "base": "", "implicits": [], "mods": []}

    i = 0
    # Extract rarity
    while i < len(lines):
        if lines[i].startswith("Rarity:"):
            result["rarity"] = lines[i].removeprefix("Rarity:").strip()
            i += 1
            break
        i += 1

    # Extract name (line 1) and base type (line 2 for rare/unique)
    name_count = 0
    while i < len(lines):
        line = lines[i]
        if any(line.startswith(p) for p in _SKIP_PREFIXES) or line.startswith("Implicits:"):
            break
        if name_count == 0:
            result["name"] = line
        elif name_count == 1 and result["rarity"] in ("RARE", "UNIQUE", "MAGIC"):
            result["base"] = line
        else:
            break
        name_count += 1
        i += 1

    # Skip metadata lines until Implicits:
    while i < len(lines) and not lines[i].startswith("Implicits:"):
        i += 1

    # Parse implicits
    if i < len(lines) and lines[i].startswith("Implicits:"):
        try:
            n = int(lines[i].removeprefix("Implicits:").strip())
        except ValueError:
            n = 0
        i += 1
        for _ in range(n):
            if i < len(lines):
                result["implicits"].append(_clean_mod(lines[i]))
                i += 1

    # Remaining lines are explicit mods
    while i < len(lines):
        result["mods"].append(_clean_mod(lines[i]))
        i += 1

    return result


def _parse_items(root: ET.Element) -> list[dict]:
    items_el = root.find("Items")
    if items_el is None:
        return []

    # Build id → parsed item dict
    item_map: dict[str, dict] = {}
    for item in items_el.findall("Item"):
        iid = item.get("id", "")
        text = (item.text or "").strip()
        if iid and text:
            item_map[iid] = _parse_item_text(text)

    # Collect Slot elements — they live inside <ItemSet>, not directly under <Items>
    slot_sources: list[ET.Element] = list(items_el.findall("Slot"))
    for item_set in items_el.findall("ItemSet"):
        slot_sources.extend(item_set.findall("Slot"))

    # Map slot name → item (skip abyssal sockets and empty slots)
    slot_items: dict[str, dict] = {}
    for slot_el in slot_sources:
        slot_name = slot_el.get("name", "")
        iid = slot_el.get("itemId", "")
        if "Abyssal Socket" in slot_name:
            continue
        if iid and iid != "0" and iid in item_map:
            slot_items[slot_name] = item_map[iid]

    # Return in display order
    equipped: list[dict] = []
    seen: set[str] = set()
    for slot in _SLOT_ORDER:
        if slot in slot_items:
            equipped.append({"slot": slot, **slot_items[slot]})
            seen.add(slot)
    # Append any remaining slots not in the predefined order
    for slot, item in slot_items.items():
        if slot not in seen:
            equipped.append({"slot": slot, **item})

    return equipped


import re as _re

def _split_camel(name: str) -> str:
    """'TheBrineKing' → 'The Brine King'"""
    return _re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', name)


def _strip_pob_colors(text: str) -> str:
    """Remove PoB color codes: ^x RRGGBB and ^N (single digit)."""
    text = _re.sub(r'\^x[0-9A-Fa-f]{6}', '', text)
    text = _re.sub(r'\^[0-9]', '', text)
    return text.strip()


def _extract_stage_indices(title: str) -> list[int]:
    """Extract stage indices from a title like 'Level 1-20 {1}' or '{6,7}'."""
    m = _re.search(r'\{([\d,\s]+)\}', title)
    if not m:
        return []
    return [int(x.strip()) for x in m.group(1).split(',') if x.strip().isdigit()]


def _clean_title(title: str) -> str:
    """Strip color codes and stage index tags from a layout title."""
    title = _strip_pob_colors(title)
    title = _re.sub(r'\s*\{[\d,\s]+\}\s*$', '', title)
    return title.strip()


def _parse_layouts(root: ET.Element) -> list[dict]:
    """
    Extract progression stages by grouping ItemSets, Tree Specs, and SkillSets
    that share the same {N} index tag in their titles.
    Returns a list of stage dicts sorted by stage index.
    """
    # Collect all components keyed by stage index
    stages: dict[int, dict] = {}

    def ensure(idx: int) -> dict:
        if idx not in stages:
            stages[idx] = {"index": idx, "items_title": "", "skills_title": "",
                           "tree_title": "", "tree_nodes": 0}
        return stages[idx]

    # ItemSets
    items_el = root.find("Items")
    if items_el is not None:
        for iset in items_el.findall("ItemSet"):
            raw = iset.get("title", "")
            for idx in _extract_stage_indices(raw):
                ensure(idx)["items_title"] = _clean_title(raw)

    # Tree Specs
    tree_el = root.find("Tree")
    if tree_el is not None:
        for spec in tree_el.findall("Spec"):
            raw = spec.get("title", "")
            indices = _extract_stage_indices(raw)
            nodes = len([n for n in spec.get("nodes", "").split(",") if n.strip()])
            for idx in indices:
                s = ensure(idx)
                s["tree_title"] = _clean_title(raw)
                s["tree_nodes"] = nodes

    # SkillSets
    skills_el = root.find("Skills")
    if skills_el is not None:
        for sset in skills_el.findall("SkillSet"):
            raw = sset.get("title", "")
            for idx in _extract_stage_indices(raw):
                ensure(idx)["skills_title"] = _clean_title(raw)

    if not stages:
        return []

    return sorted(stages.values(), key=lambda s: s["index"])


def _parse_notes(root: ET.Element) -> str:
    """Extract the Notes section text, stripping PoB color codes and whitespace."""
    notes_el = root.find("Notes")
    if notes_el is None or not notes_el.text:
        return ""
    return _strip_pob_colors(notes_el.text).strip()


def _parse_passives(root: ET.Element) -> dict:
    tree_el = root.find("Tree")
    if tree_el is None:
        return {"keystones": [], "notables": [], "total": 0}

    spec = tree_el.find("Spec")
    if spec is None:
        return {"keystones": [], "notables": [], "total": 0}

    nodes_str = spec.get("nodes", "")
    if not nodes_str:
        return {"keystones": [], "notables": [], "total": 0}

    allocated_ids = set(nodes_str.split(","))
    total = len(allocated_ids)

    try:
        from scrapers.player.passives import _load_tree
        by_id = _load_tree()["by_id"]
        keystones, notables = [], []
        for nid in allocated_ids:
            node = by_id.get(nid)
            if not node:
                continue
            ntype = node.get("_type", "")
            name = node.get("name", "").strip()
            if not name:
                continue
            if ntype == "keystone":
                keystones.append(name)
            elif ntype == "notable":
                notables.append(name)
    except Exception:
        keystones, notables = [], []

    return {
        "keystones": sorted(keystones),
        "notables": sorted(notables),
        "total": total,
    }


def parse_pob(code_or_url: str) -> str:
    """Parse a Path of Building export code or share URL.

    Accepts:
    - Raw PoB export code (base64 string from PoB's Export button)
    - pobb.in URL (https://pobb.in/xxxxx or https://pobb.in/u/username/xxxxx)
    - Pastebin URL (https://pastebin.com/xxxxx)

    Returns a build summary including class, level, key stats, skill links,
    equipped items with mods, and allocated keystones and notable passives.

    Args:
        code_or_url: PoB export code, pobb.in share URL, or pastebin URL.
    """
    code = code_or_url.strip()

    if code.startswith("http"):
        try:
            code = _fetch_raw(code)
        except httpx.HTTPStatusError as e:
            return f"Failed to fetch PoB data: HTTP {e.response.status_code} from {e.request.url}"
        except Exception as e:
            return f"Failed to fetch PoB data: {e}"

    try:
        root = _decode_pob(code)
    except Exception as e:
        return str(e)

    build = _parse_build_info(root)
    skills = _parse_skills(root)
    items = _parse_items(root)
    passives = _parse_passives(root)
    notes = _parse_notes(root)
    layouts = _parse_layouts(root)

    lines: list[str] = []

    # ── Header ──────────────────────────────────────────────────
    char_class = build.get("class", "Unknown")
    asc = build.get("ascendancy", "")
    level = build.get("level", "?")

    title = f"# {char_class}"
    if asc and asc != char_class:
        title += f" ({asc})"
    title += f"  —  Level {level}"
    lines += [title, ""]

    # ── Notes ────────────────────────────────────────────────────
    if notes:
        lines.append("## Notes")
        lines.append(notes)
        lines.append("")

    # ── Progression Stages ───────────────────────────────────────
    if layouts:
        lines.append("## Progression Stages")
        for stage in layouts:
            idx = stage["index"]
            # Pick the most descriptive title across the three components
            title = stage["items_title"] or stage["tree_title"] or stage["skills_title"]
            lines.append(f"**Stage {idx}** — {title}")
            if stage["tree_title"] and stage["tree_nodes"]:
                lines.append(f"  - Tree: {stage['tree_title']} ({stage['tree_nodes']} nodes)")
            if stage["skills_title"]:
                lines.append(f"  - Skills: {stage['skills_title']}")
            if stage["items_title"]:
                lines.append(f"  - Items: {stage['items_title']}")
        lines.append("")

    # ── Build Details ────────────────────────────────────────────
    details = []
    bandit = build.get("bandit", "")
    if bandit:
        details.append(f"**Bandit:** {bandit}")
    major = build.get("pantheon_major", "")
    minor = build.get("pantheon_minor", "")
    if major or minor:
        pantheon = " / ".join(_split_camel(p) for p in [major, minor] if p)
        details.append(f"**Pantheon:** {pantheon}")
    if details:
        lines += details + [""]

    # ── Key Stats ────────────────────────────────────────────────
    stats = build.get("stats", {})
    if stats:
        lines.append("## Key Stats")
        for key, label in _KEY_STATS.items():
            val = stats.get(key)
            if val is None or val == 0:
                continue
            if key in ("TotalDPS", "AverageDamage"):
                lines.append(f"- **{label}:** {val:,.0f}")
            elif key == "HitChance":
                lines.append(f"- **{label}:** {val:.1f}%")
            elif key == "Speed":
                lines.append(f"- **{label}:** {val:.2f}")
            else:
                lines.append(f"- **{label}:** {int(val):,}")
        lines.append("")

    # ── Skill Links ──────────────────────────────────────────────
    if skills:
        lines.append("## Skills")
        for group in skills:
            slot = group["slot"] or group["label"] or "—"
            gem_parts = []
            for g in group["gems"]:
                name = g["name"]
                lvl = g["level"]
                qual = g["quality"]
                tag = f"L{lvl}" if lvl else ""
                if qual and qual != "0":
                    tag += f"/Q{qual}"
                gem_parts.append(f"{name} ({tag})" if tag else name)
            lines.append(f"- **{slot}:** " + " — ".join(gem_parts))
        lines.append("")

    # ── Equipped Items ───────────────────────────────────────────
    if items:
        lines.append("## Equipped Items")
        for item in items:
            slot = item["slot"]
            name = item.get("name", "")
            base = item.get("base", "")
            rarity = item.get("rarity", "")
            implicits = item.get("implicits", [])
            mods = item.get("mods", [])

            # Slot header
            display_name = name
            if base and base != name:
                display_name += f" *({base})*"
            rarity_tag = f" [{rarity}]" if rarity else ""
            lines.append(f"**{slot}:** {display_name}{rarity_tag}")

            # Show implicits then explicit mods
            all_mods = implicits + mods
            for mod in all_mods[:10]:
                lines.append(f"  - {mod}")
            if len(all_mods) > 10:
                lines.append(f"  - *... and {len(all_mods) - 10} more*")
        lines.append("")

    # ── Passives ─────────────────────────────────────────────────
    total = passives.get("total", 0)
    keystones = passives.get("keystones", [])
    notables = passives.get("notables", [])

    if total > 0:
        lines.append(f"## Passive Tree  ({total} nodes)")
        if keystones:
            lines.append(f"**Keystones:** {', '.join(keystones)}")
        if notables:
            lines.append(f"**Notables ({len(notables)}):** {', '.join(notables)}")
        lines.append("")

    return "\n".join(lines)
