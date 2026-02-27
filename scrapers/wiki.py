import re

import httpx
from bs4 import BeautifulSoup

from scrapers.common import HEADERS

# Sections worth extracting from poewiki.net pages
_USEFUL_SECTIONS = {
    "Mechanics", "Item acquisition", "Recipes",
    "Skill functions and interactions",
    "Foulborn modifiers", "Alternate artwork",
}
# Sections to skip
_SKIP_SECTIONS = {
    "Contents", "See also", "References", "Item skins",
    "Version history", "External links",
}


def _clean_wiki_text(el) -> str:
    """Extract text from a wiki element with proper spacing and punctuation."""
    text = el.get_text(" ", strip=True)
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text


def _extract_section_text(heading, content_div) -> list[str]:
    """Extract text from elements following a heading until the next heading of same or higher level."""
    lines = []
    level = int(heading.name[1])  # h2 -> 2, h3 -> 3
    for sibling in heading.find_next_siblings():
        if sibling.name and sibling.name in ("h2", "h3"):
            sib_level = int(sibling.name[1])
            if sib_level <= level:
                break
            if level == 2 and sib_level == 3:
                break
        if sibling.name == "p":
            text = _clean_wiki_text(sibling)
            if text:
                lines.append(text)
        elif sibling.name == "ul":
            for li in sibling.find_all("li", recursive=False):
                text = _clean_wiki_text(li)
                if text:
                    lines.append(f"- {text}")
        elif sibling.name == "table":
            rows = []
            for tr in sibling.find_all("tr"):
                cells = []
                for td in tr.find_all(["th", "td"]):
                    cells.append(td.get_text(" ", strip=True))
                if cells:
                    rows.append(cells)
            if rows:
                lines.append("| " + " | ".join(rows[0]) + " |")
                lines.append("| " + " | ".join(["---"] * len(rows[0])) + " |")
                for row in rows[1:]:
                    padded = row + [""] * (len(rows[0]) - len(row))
                    lines.append("| " + " | ".join(padded[:len(rows[0])]) + " |")
        elif sibling.name == "div" and "navbox" in " ".join(sibling.get("class", [])):
            break
    return lines


def fetch_wiki_page(wiki_url: str) -> str:
    """Fetch useful content from a poewiki.net page, stripping navigation and noise.

    Use this to get detailed mechanics, acquisition info, and recipes from the
    Community Wiki link returned by get_item_detail or get_gem_detail.

    Args:
        wiki_url: Full poewiki.net URL, e.g. "https://www.poewiki.net/wiki/Headhunter"
    """
    if "poewiki.net" not in wiki_url:
        return "This tool only works with poewiki.net URLs."

    try:
        resp = httpx.get(wiki_url, headers=HEADERS, follow_redirects=True, timeout=30)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        return f"Failed to fetch wiki page (HTTP {e.response.status_code})."

    soup = BeautifulSoup(resp.text, "html.parser")
    content = soup.select_one("div.mw-parser-output")
    if not content:
        return "Could not find wiki content on this page."

    # Strip inline tooltip popups (keep only the visible activator text)
    for popup in content.select(".hoverbox__display"):
        popup.decompose()

    sections = []

    # Page title
    title_el = soup.select_one("h1#firstHeading, h1.firstHeading")
    title = title_el.get_text(strip=True) if title_el else wiki_url.split("/")[-1].replace("_", " ")
    sections.append(f"# {title}")
    sections.append("")

    # Intro paragraphs (before first h2)
    for child in content.children:
        if hasattr(child, "name") and child.name == "h2":
            break
        if hasattr(child, "name") and child.name == "p":
            text = _clean_wiki_text(child)
            if text:
                sections.append(text)
                sections.append("")

    # Extract useful sections
    for heading in content.find_all(["h2", "h3"]):
        span = heading.select_one("span.mw-headline")
        section_name = span.get_text(strip=True) if span else heading.get_text(strip=True)

        if section_name in _SKIP_SECTIONS:
            continue

        lines = _extract_section_text(heading, content)
        if lines:
            prefix = "##" if heading.name == "h2" else "###"
            sections.append(f"{prefix} {section_name}")
            sections.extend(lines)
            sections.append("")

    sections.append(f"**Source:** {wiki_url}")
    return "\n".join(sections)
