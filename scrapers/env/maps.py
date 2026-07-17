import httpx

from scrapers.common import BASE_URL, Cache, fetch_page

_map_cache: Cache[list[dict]] = Cache()


def _get_all_maps() -> list[dict]:
    """Scrape /us/Maps and return all maps with tier/boss/tileset info."""
    cached = _map_cache.get()
    if cached is not None:
        return cached

    soup = fetch_page(f"{BASE_URL}/Maps")

    # Find the Maps List table (header contains "Maps List")
    table = None
    for h5 in soup.find_all("h5"):
        if "Maps List" in h5.get_text(strip=True):
            card = h5.find_parent("div", class_="card")
            if card:
                table = card.find("table")
            break

    if not table:
        return []

    maps = []
    for tr in table.find_all("tr")[1:]:  # skip header row
        tds = tr.find_all("td")
        if len(tds) < 7:
            continue

        # Columns: T, Imprint, Icon, Name, Tier, Boss, Tileset
        name_td = tds[3]
        name_link = name_td.find("a")
        if not name_link:
            continue

        name = name_link.get_text(strip=True)
        href = name_link.get("href", "")
        url = f"https://poedb.tw/us/{href}" if not href.startswith("http") else href

        tiers = tds[4].get_text(strip=True)

        # Boss may have multiple links separated by <br>
        boss_links = tds[5].find_all("a")
        bosses = [a.get_text(strip=True) for a in boss_links if a.get_text(strip=True)]
        boss = ", ".join(bosses) if bosses else tds[5].get_text(strip=True)

        tileset_link = tds[6].find("a")
        tileset = tileset_link.get_text(strip=True) if tileset_link else tds[6].get_text(strip=True)

        maps.append({
            "name": name,
            "url": url,
            "tiers": tiers,
            "boss": boss,
            "tileset": tileset,
        })

    _map_cache.set(maps)
    return maps


def format_map(m: dict) -> str:
    """Format a map dict as a concise search result line."""
    parts = [f"- **{m['name']}**"]
    if m["tiers"]:
        parts.append(f"(T{m['tiers']})")
    if m["boss"]:
        parts.append(f"— Boss: {m['boss']}")
    return " ".join(parts)


def get_map_detail(name: str) -> str:
    """Fetch a map's detail page and return formatted info."""
    maps = _get_all_maps()

    # Find map in cache (exact then case-insensitive)
    cached = None
    name_lower = name.lower()
    for m in maps:
        if m["name"] == name:
            cached = m
            break
    if not cached:
        for m in maps:
            if m["name"].lower() == name_lower:
                cached = m
                break

    if cached:
        url = cached["url"]
    else:
        url = f"{BASE_URL}/{name.replace(' ', '_')}"

    sections = []

    if cached:
        sections.append(f"# {cached['name']}")
        if cached["tiers"]:
            sections.append(f"**Tiers:** {cached['tiers']}")
        if cached["boss"]:
            sections.append(f"**Boss:** {cached['boss']}")
        if cached["tileset"]:
            sections.append(f"**Tileset:** {cached['tileset']}")
        sections.append("")

    # Try to fetch detail page for extras
    try:
        soup = fetch_page(url)
    except httpx.HTTPStatusError:
        if cached:
            sections.append(f"**Full details:** {url}")
            return "\n".join(sections)
        return f"Could not find map '{name}'. Try env_search to find the correct name."

    if not cached:
        sections.append(f"# {name}")
        sections.append("")

    # Table 0 has area attributes including Atlas Linked
    tables = soup.find_all("table")
    if tables:
        attr_table = tables[0]
        for tr in attr_table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue
            key = tds[0].get_text(strip=True)
            if key == "Atlas Linked":
                linked = [a.get_text(strip=True) for a in tds[1].find_all("a")]
                if linked:
                    sections.append(f"**Connected maps:** {', '.join(linked)}")
            elif key == "Level":
                sections.append(f"**Area level:** {tds[1].get_text(strip=True)}")
            elif key == "Vaal Area":
                sections.append(f"**Vaal area:** {tds[1].get_text(strip=True)}")

    # Community Wiki link
    wiki_link = soup.find("a", string="Community Wiki")
    if wiki_link and wiki_link.get("href"):
        sections.append(f"**Community Wiki:** {wiki_link['href']}")

    sections.append(f"**Full details:** {url}")
    return "\n".join(sections)
