from scrapers.env.maps import _get_all_maps, format_map, get_map_detail
from scrapers.env.scarabs import _get_all_scarabs, format_scarab, get_scarab_detail

CATEGORIES = {
    "maps": (_get_all_maps, format_map, get_map_detail, "name"),
    "scarabs": (_get_all_scarabs, format_scarab, get_scarab_detail, "name"),
}

CATEGORY_ALIASES = {
    "map": "maps",
    "scarab": "scarabs",
}


def _resolve_category(category: str) -> str | None:
    """Resolve a category string to a canonical key, or None."""
    if not category:
        return None
    c = category.lower().strip()
    if c in CATEGORIES:
        return c
    return CATEGORY_ALIASES.get(c)


def _fuzzy_score(query: str, entry: dict, name_key: str) -> int:
    """Score an entry against a search query. Higher = better match."""
    q = query.lower()
    name_l = entry[name_key].lower()

    if name_l == q:
        return 100
    if name_l.startswith(q):
        return 80
    if q in name_l:
        return 60

    words = q.split()
    if len(words) > 1 and all(w in name_l for w in words):
        return 50

    # Search across all string fields
    all_text = " ".join(str(v) for v in entry.values() if isinstance(v, str)).lower()
    if q in all_text:
        return 20
    if len(words) > 1 and all(w in all_text for w in words):
        return 10

    return 0


def env_search(query: str, category: str = "") -> str:
    """Search for Path of Exile maps and scarabs by name or keyword.

    Searches across maps (name, boss, tileset) and scarabs (name, effect).
    Optionally filter by category.

    Args:
        query: Search keyword(s) to match against names and descriptions.
        category: Optional filter: "maps" or "scarabs". If empty, searches all.
    """
    resolved = _resolve_category(category)
    if category and resolved is None:
        valid = ", ".join(f'"{k}"' for k in CATEGORIES)
        return f"Unknown category '{category}'. Valid categories: {valid}"

    cats_to_search = [resolved] if resolved else list(CATEGORIES.keys())
    all_sections = []

    for cat in cats_to_search:
        get_all, fmt, _, name_key = CATEGORIES[cat]
        entries = get_all()

        matches = []
        for entry in entries:
            score = _fuzzy_score(query, entry, name_key)
            if score > 0:
                matches.append((score, entry))

        matches.sort(key=lambda x: (-x[0], x[1][name_key]))

        if matches:
            lines = [f"**{cat.title()}** ({len(matches)} match{'es' if len(matches) != 1 else ''}):\n"]
            for _, entry in matches[:15]:
                lines.append(fmt(entry))
            if len(matches) > 15:
                lines.append(f"  ... and {len(matches) - 15} more")
            lines.append("")
            all_sections.append("\n".join(lines))

    if not all_sections:
        return f"No results found matching '{query}'."

    return "\n".join(all_sections)


def env_detail(name: str) -> str:
    """Get detailed information about a specific map or scarab.

    Looks up the name across all environment categories (maps, scarabs).
    Returns full details including connected maps, boss info, or scarab effects.

    Args:
        name: The exact name, e.g. "Strand Map" or "Breach Scarab".
    """
    name_lower = name.lower()

    # Try exact match first, then case-insensitive, across all categories
    for cat_key, (get_all, _, detail_fn, name_key) in CATEGORIES.items():
        entries = get_all()
        for entry in entries:
            if entry[name_key] == name:
                return detail_fn(name)

    for cat_key, (get_all, _, detail_fn, name_key) in CATEGORIES.items():
        entries = get_all()
        for entry in entries:
            if entry[name_key].lower() == name_lower:
                return detail_fn(entry[name_key])

    return f"Could not find '{name}'. Try env_search to find the correct name."
