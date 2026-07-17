import httpx

from scrapers.common import BASE_URL, Cache, fetch_page

_scarab_cache: Cache[list[dict]] = Cache()


def _get_all_scarabs() -> list[dict]:
    """Scrape /us/Scarab and return all scarabs with effect info."""
    cached = _scarab_cache.get()
    if cached is not None:
        return cached

    soup = fetch_page(f"{BASE_URL}/Scarab")
    scarabs = []

    for entry in soup.select("div.d-flex.border-top.rounded"):
        links = entry.find_all("a")
        if len(links) < 2:
            continue

        text_link = links[1]
        name = text_link.get_text(strip=True)
        if not name:
            continue

        href = text_link.get("href", "")
        url = f"https://poedb.tw/us/{href}" if not href.startswith("http") else href

        # Parse properties (Stack Size, Limit) and effect from inner div
        stack_size = ""
        limit = ""
        effect = ""

        for prop_div in entry.select("div.property"):
            text = prop_div.get_text(strip=True)
            if text.startswith("Stack Size:"):
                stack_size = text.replace("Stack Size:", "").strip()
            elif text.startswith("Limit:"):
                limit = text.replace("Limit:", "").strip()

        effect_divs = entry.select("div.explicitMod")
        if effect_divs:
            effect = " ".join(d.get_text(strip=True) for d in effect_divs)

        scarabs.append({
            "name": name,
            "url": url,
            "stack_size": stack_size,
            "limit": limit,
            "effect": effect,
        })

    _scarab_cache.set(scarabs)
    return scarabs


def format_scarab(s: dict) -> str:
    """Format a scarab dict as a concise search result line."""
    parts = [f"- **{s['name']}**"]
    if s["effect"]:
        parts.append(f"— {s['effect']}")
    return " ".join(parts)


def get_scarab_detail(name: str) -> str:
    """Return scarab info from cached data (detail pages add little)."""
    scarabs = _get_all_scarabs()

    cached = None
    name_lower = name.lower()
    for s in scarabs:
        if s["name"] == name:
            cached = s
            break
    if not cached:
        for s in scarabs:
            if s["name"].lower() == name_lower:
                cached = s
                break

    if not cached:
        return f"Could not find scarab '{name}'. Try env_search to find the correct name."

    sections = [f"# {cached['name']}"]
    if cached["stack_size"]:
        sections.append(f"**Stack Size:** {cached['stack_size']}")
    if cached["limit"]:
        sections.append(f"**Limit:** {cached['limit']}")
    sections.append("")
    if cached["effect"]:
        sections.append(f"**Effect:** {cached['effect']}")
        sections.append("")
    sections.append(f"**Full details:** {cached['url']}")
    return "\n".join(sections)
