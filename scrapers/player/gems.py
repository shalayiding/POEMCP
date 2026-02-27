import httpx

from scrapers.common import BASE_URL, Cache, fetch_page

_gem_cache = Cache()


def _get_all_gems() -> list[dict]:
    cached = _gem_cache.get()
    if cached is not None:
        return cached

    soup = fetch_page(f"{BASE_URL}/Gem")
    gems = []

    for entry in soup.select("div.d-flex.border-top.rounded"):
        links = entry.find_all("a")
        if len(links) < 2:
            continue

        text_link = links[1]
        name = text_link.get_text(strip=True)
        href = text_link.get("href", "")
        url = f"https://poedb.tw{href}" if href.startswith("/") else href

        gem_class = text_link.get("class", [])
        gem_type = "unknown"
        for cls in gem_class:
            if cls.startswith("gem_"):
                gem_type = cls.replace("gem_", "")
                break

        desc_div = entry.select_one("div.flex-grow-1 > div")
        description = desc_div.get_text(strip=True) if desc_div else ""

        gems.append({
            "name": name,
            "url": url,
            "type": gem_type,
            "description": description,
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
            score = 2
            if name_lower == query_lower:
                score = 3
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
        lines.append(f"- **{gem['name']}** ({gem['type']})")
        if gem["description"]:
            lines.append(
                f"  {gem['description'][:120]}{'...' if len(gem['description']) > 120 else ''}"
            )
        lines.append(f"  URL: {gem['url']}")
        lines.append("")

    if len(matches) > 20:
        lines.append(f"... and {len(matches) - 20} more results.")

    return "\n".join(lines)


def get_gem_detail(gem_name: str) -> str:
    """Get detailed information about a specific Path of Exile gem.

    Args:
        gem_name: The gem name, e.g. "Fireball" or "Leap Slam".
    """
    url_name = gem_name.replace(" ", "_")
    url = f"{BASE_URL}/{url_name}"

    try:
        soup = fetch_page(url)
    except httpx.HTTPStatusError as e:
        return f"Could not find gem '{gem_name}' (HTTP {e.response.status_code}). Check the gem name and try again."

    sections = []

    popup = soup.select_one("div.gemPopup")
    if popup:
        name_el = popup.select_one("span.lc")
        gem_display_name = name_el.get_text(strip=True) if name_el else gem_name

        tags = [a.get_text(strip=True) for a in popup.select("a.GemTags")]

        properties = []
        for prop_div in popup.select("div.property"):
            if prop_div.find("a", class_="GemTags"):
                continue
            text = prop_div.get_text(" ", strip=True)
            properties.append(text)

        req = popup.select_one("div.requirements")
        requirements = req.get_text(" ", strip=True) if req else ""

        desc = popup.select_one("div.secDescrText")
        description = desc.get_text(strip=True) if desc else ""

        mods = [m.get_text(" ", strip=True) for m in popup.select("div.explicitMod")]
        quality_mods = [q.get_text(" ", strip=True) for q in popup.select("div.qualityMod")]

        sections.append(f"# {gem_display_name}")
        if tags:
            sections.append(f"**Tags:** {', '.join(tags)}")
        for prop in properties:
            sections.append(f"- {prop}")
        if requirements:
            sections.append(f"- {requirements}")
        sections.append("")
        if description:
            sections.append(f"*{description}*\n")
        if mods:
            sections.append("**Stats:**")
            for mod in mods:
                sections.append(f"- {mod}")
            sections.append("")
        if quality_mods:
            sections.append("**Quality bonus:**")
            for qm in quality_mods:
                sections.append(f"- {qm}")
            sections.append("")

    # Level Effect table
    for card in soup.select("div.card"):
        header = card.select_one("h5.card-header")
        if not header:
            continue
        if "Level Effect" not in header.get_text(strip=True):
            continue

        table = None
        for t in card.find_all("table"):
            ths = [th.get_text(strip=True) for th in t.find_all("th")]
            if "Level" in ths:
                table = t
                break
        if not table:
            continue

        headers = [th.get_text(" ", strip=True) for th in table.find_all("th")]
        rows = []
        for tr in table.find_all("tr")[1:]:
            cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if cells:
                rows.append(cells)

        if rows:
            sections.append("**Level Scaling (selected levels):**")
            selected = []
            for row in rows:
                if row and row[0] in ("1", "10", "20"):
                    selected.append(row)
            if rows[-1] not in selected:
                selected.append(rows[-1])

            sections.append("| " + " | ".join(headers) + " |")
            sections.append("| " + " | ".join(["---"] * len(headers)) + " |")
            for row in selected:
                padded = row + [""] * (len(headers) - len(row))
                sections.append("| " + " | ".join(padded[:len(headers)]) + " |")
            sections.append("")
        break

    sections.append(f"**Full details:** {url}")
    return "\n".join(sections)
