from scrapers.common import Cache
from scrapers.pob_data import fetch_lua_file, parse_lua_assignments, parse_lua_table

_gem_cache: Cache[list[dict]] = Cache()

SKILL_FILES = [
    "act_dex.lua", "act_int.lua", "act_str.lua", "glove.lua",
    "minion.lua", "other.lua", "spectre.lua",
    "sup_dex.lua", "sup_int.lua", "sup_str.lua",
]

_COLOR_NAMES = {1: "red (strength)", 2: "green (dexterity)", 3: "blue (intelligence)"}


def _load_all_skills() -> dict:
    """Merge every Skills/*.lua file into one dict keyed by grantedEffectId."""
    skills = {}
    for filename in SKILL_FILES:
        try:
            text = fetch_lua_file(f"Skills/{filename}")
        except Exception:
            continue
        skills.update(parse_lua_assignments(text, "skills"))
    return skills


def _get_all_gems() -> list[dict]:
    """Fetch and merge Path of Building's gem catalogue (Gems.lua) with per-skill data (Skills/*.lua)."""
    cached = _gem_cache.get()
    if cached is not None:
        return cached

    gem_data = parse_lua_table(fetch_lua_file("Gems.lua"))
    skills = _load_all_skills()

    gems = []
    for gem_id, entry in gem_data.items():
        if not isinstance(entry, dict) or "name" not in entry:
            continue
        skill = skills.get(entry.get("grantedEffectId"), {})
        gems.append({
            "name": entry.get("name", ""),
            "gem_id": gem_id,
            "tag_string": entry.get("tagString", ""),
            "req_str": entry.get("reqStr", 0),
            "req_dex": entry.get("reqDex", 0),
            "req_int": entry.get("reqInt", 0),
            "max_level": entry.get("naturalMaxLevel", 20),
            "vaal": bool(entry.get("vaalGem")),
            "description": skill.get("description", ""),
            "color": _COLOR_NAMES.get(skill.get("color"), ""),
            "cast_time": skill.get("castTime"),
            "levels": skill.get("levels", {}),
            "quality_stats": skill.get("qualityStats", []),
        })

    _gem_cache.set(gems)
    return gems


def search_gem(query: str) -> str:
    """Search for Path of Exile gems by name or description keyword.

    Args:
        query: Search keyword to match against gem names and descriptions.
    """
    gems = _get_all_gems()
    query_lower = query.lower()

    matches = []
    for gem in gems:
        name_lower = gem["name"].lower()
        desc_lower = gem["description"].lower()

        if query_lower in name_lower:
            score = 3 if name_lower == query_lower else 2
        elif query_lower in desc_lower:
            score = 1
        else:
            continue

        matches.append((score, gem))

    matches.sort(key=lambda x: (-x[0], x[1]["name"]))

    if not matches:
        return f"No gems found matching '{query}'."

    lines = [f"Found {len(matches)} gem(s) matching '{query}':\n"]
    for _, gem in matches[:20]:
        lines.append(f"- **{gem['name']}** ({gem['tag_string']})")
        if gem["description"]:
            desc = gem["description"]
            lines.append(f"  {desc[:120]}{'...' if len(desc) > 120 else ''}")
        lines.append("")

    if len(matches) > 20:
        lines.append(f"... and {len(matches) - 20} more results.")

    return "\n".join(lines)


def get_gem_detail(gem_name: str) -> str:
    """Get detailed information about a specific Path of Exile gem.

    Args:
        gem_name: The gem name, e.g. "Fireball" or "Leap Slam".
    """
    gems = _get_all_gems()
    query_lower = gem_name.lower()

    match = None
    for gem in gems:
        if gem["name"].lower() == query_lower:
            match = gem
            break
    if not match:
        for gem in gems:
            if query_lower in gem["name"].lower():
                match = gem
                break

    if not match:
        return f"Could not find gem '{gem_name}'. Try search_gem to find the correct name."

    sections = [f"# {match['name']}"]
    if match["tag_string"]:
        sections.append(f"**Tags:** {match['tag_string']}")
    if match["color"]:
        sections.append(f"**Gem colour:** {match['color']}")

    reqs = []
    if match["req_str"]:
        reqs.append(f"{match['req_str']} Str")
    if match["req_dex"]:
        reqs.append(f"{match['req_dex']} Dex")
    if match["req_int"]:
        reqs.append(f"{match['req_int']} Int")
    if reqs:
        sections.append(f"**Base attribute requirements:** {', '.join(reqs)}")
    sections.append(f"**Max level:** {match['max_level']}")
    if match["cast_time"]:
        sections.append(f"**Cast/attack time:** {match['cast_time']}s")
    sections.append("")

    if match["description"]:
        sections.append(f"*{match['description']}*\n")

    if match["quality_stats"]:
        sections.append("**Quality bonus (per 1% Quality):**")
        for stat in match["quality_stats"]:
            if isinstance(stat, list) and len(stat) >= 2:
                stat_name = str(stat[0]).replace("_", " ")
                sections.append(f"- {stat_name}: {stat[1]}")
        sections.append("")

    levels = match["levels"]
    if levels:
        sample_levels = sorted(set([1, 10, 20, match["max_level"]]) & set(levels.keys()))
        sections.append("**Level scaling (selected levels):**")
        sections.append("| Level | Level Req | Mana Cost | Damage Effectiveness | Crit Chance |")
        sections.append("| --- | --- | --- | --- | --- |")
        for lvl in sample_levels:
            data = levels[lvl]
            level_req = data.get("levelRequirement", "-")
            mana = data.get("cost", {}).get("Mana", "-") if isinstance(data.get("cost"), dict) else "-"
            eff = data.get("damageEffectiveness", "-")
            crit = data.get("critChance", "-")
            sections.append(f"| {lvl} | {level_req} | {mana} | {eff} | {crit} |")
        sections.append("")
        sections.append(
            "_Note: raw scaling data from Path of Building — not the fully rendered "
            "in-game tooltip text (e.g. exact damage ranges), which requires GGG's stat "
            "description templates._"
        )

    return "\n".join(sections)
