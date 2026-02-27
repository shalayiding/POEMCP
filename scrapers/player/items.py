import httpx

from scrapers.common import BASE_URL, Cache, fetch_page

_item_cache = Cache()

ITEM_CATEGORIES = {
    # One Handed Weapons
    "Claws": "One Handed Weapons",
    "Daggers": "One Handed Weapons",
    "Wands": "One Handed Weapons",
    "One Hand Swords": "One Handed Weapons",
    "One Hand Axes": "One Handed Weapons",
    "One Hand Maces": "One Handed Weapons",
    "Sceptres": "One Handed Weapons",
    "Rune Daggers": "One Handed Weapons",
    "Thrusting One Hand Swords": "One Handed Weapons",
    # Two Handed Weapons
    "Bows": "Two Handed Weapons",
    "Staves": "Two Handed Weapons",
    "Two Hand Swords": "Two Handed Weapons",
    "Two Hand Axes": "Two Handed Weapons",
    "Two Hand Maces": "Two Handed Weapons",
    "Warstaves": "Two Handed Weapons",
    "Fishing Rods": "Two Handed Weapons",
    # Off-hand
    "Quivers": "Off-hand",
    "Shields": "Off-hand",
    # Armour
    "Gloves": "Armour",
    "Boots": "Armour",
    "Body Armours": "Armour",
    "Helmets": "Armour",
    # Jewellery
    "Amulets": "Jewellery",
    "Rings": "Jewellery",
    "Belts": "Jewellery",
    "Trinkets": "Jewellery",
}


def _get_all_items() -> list[dict]:
    """Scrape /us/Unique_item and return all unique items with mods."""
    cached = _item_cache.get()
    if cached is not None:
        return cached

    soup = fetch_page(f"{BASE_URL}/Unique_item")
    items = []

    for entry in soup.select("div.d-flex.border-top.rounded"):
        links = entry.find_all("a")
        if len(links) < 2:
            continue

        name_span = entry.select_one("span.uniqueName")
        type_span = entry.select_one("span.uniqueTypeLine")
        if not name_span:
            continue

        name = name_span.get_text(strip=True)
        base_type = type_span.get_text(strip=True) if type_span else ""

        href = links[1].get("href", "")
        url = f"https://poedb.tw{href}" if href.startswith("/") else href

        implicits = [m.get_text(" ", strip=True) for m in entry.select("div.implicitMod")]
        explicits = [m.get_text(" ", strip=True) for m in entry.select("div.explicitMod")]

        items.append({
            "name": name,
            "base_type": base_type,
            "url": url,
            "implicits": implicits,
            "explicits": explicits,
        })

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


def _format_item_from_cache(item: dict) -> str:
    """Format an item using only cached list data (fallback when detail page fails)."""
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
    lines.append(f"**Full details:** {item['url']}")
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
        lines.append(f"  URL: {item['url']}")
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
    cached = None
    for item in items:
        if item["name"].lower() == query_lower:
            cached = item
            break

    if cached:
        url = cached["url"]
    else:
        url = f"{BASE_URL}/{item_name.replace(' ', '_')}"

    soup = None
    try:
        soup = fetch_page(url)
    except httpx.HTTPStatusError:
        if cached:
            return _format_item_from_cache(cached)
        return f"Could not find item '{item_name}'. Try search_item to find the correct name."

    sections = []

    if cached:
        sections.append(f"# {cached['name']}")
        sections.append(f"**Base type:** {cached['base_type']}")
        sections.append("")
        if cached["implicits"]:
            sections.append("**Implicit:**")
            for mod in cached["implicits"]:
                sections.append(f"- {mod}")
            sections.append("")
        if cached["explicits"]:
            sections.append("**Explicit:**")
            for mod in cached["explicits"]:
                sections.append(f"- {mod}")
            sections.append("")
    else:
        sections.append(f"# {item_name}")
        sections.append("")

    if soup:
        flavor = soup.select_one("div.flavourText")
        if flavor:
            sections.append(f"*{flavor.get_text(strip=True)}*\n")

        popup = soup.select_one("div.gemPopup")
        if popup:
            desc = popup.select_one("div.secDescrText")
            if desc:
                sections.append(f"*{desc.get_text(strip=True)}*\n")

        for card in soup.select("div.card"):
            header = card.select_one("h5.card-header")
            if not header:
                continue
            header_text = header.get_text(strip=True)
            if "Acquisition" in header_text:
                sources = []
                for tr in card.select("tbody tr"):
                    tds = tr.find_all("td")
                    if tds:
                        source = tds[0].get_text(strip=True)
                        if source:
                            sources.append(source)
                if sources:
                    sections.append("**Acquisition:**")
                    for src in sources:
                        sections.append(f"- {src}")
                    sections.append("")

        wiki_link = soup.find("a", string="Community Wiki")
        if wiki_link and wiki_link.get("href"):
            sections.append(f"**Community Wiki:** {wiki_link['href']}")

    sections.append(f"**Full details:** {url}")
    return "\n".join(sections)
