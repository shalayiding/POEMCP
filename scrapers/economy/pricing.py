"""poe.ninja economy data — price checking and currency overview."""

import re
import time

import httpx

from scrapers.common import HEADERS

NINJA_CURRENCY_URL = "https://poe.ninja/api/data/currencyoverview"
NINJA_ITEM_URL = "https://poe.ninja/api/data/itemoverview"
NINJA_HOME = "https://poe.ninja/"

CURRENCY_TYPES = ["Currency", "Fragment"]
ITEM_TYPES = {
    "unique": ["UniqueWeapon", "UniqueArmour", "UniqueAccessory", "UniqueFlask", "UniqueJewel"],
    "gem": ["SkillGem"],
    "divcard": ["DivinationCard"],
    "map": ["Map"],
    "essence": ["Essence"],
    "scarab": ["Scarab"],
    "oil": ["Oil"],
    "fossil": ["Fossil"],
    "cluster": ["ClusterJewel"],
    "base": ["BaseType"],
    "vial": ["Vial"],
    "omen": ["Omen"],
    "invitation": ["Invitation"],
}

# Categories searched when no category hint is given (most common first)
DEFAULT_SEARCH_ORDER = ["currency", "unique", "gem", "divcard", "map"]

# --- Caches ---
_league_cache: str | None = None
_league_cache_ts: float = 0
_LEAGUE_TTL = 3600  # 1 hour

_ninja_cache: dict[tuple[str, str], tuple[float, list]] = {}
_NINJA_TTL = 900  # 15 minutes


def _get_current_league() -> str:
    """Auto-detect current temp league from poe.ninja homepage.

    Scrapes the poe.ninja homepage for league names referenced in URLs
    like /economy/phrecia/ and validates the league has data.
    Falls back to Standard if no temp league is found.
    """
    global _league_cache, _league_cache_ts
    if _league_cache and (time.time() - _league_cache_ts) < _LEAGUE_TTL:
        return _league_cache

    permanent = {"standard", "hardcore"}
    try:
        resp = httpx.get(NINJA_HOME, headers=HEADERS, follow_redirects=True, timeout=15)
        resp.raise_for_status()
        # Find league names in URLs like /economy/phrecia/ or /challenge/phrecia
        candidates = re.findall(r'/(?:economy|challenge)/([a-z][a-z0-9-]+)', resp.text.lower())
        seen = set()
        for c in candidates:
            if c in permanent or c in seen:
                continue
            seen.add(c)
            # Capitalize for API use and validate it has data
            league_name = c.capitalize()
            test = _fetch_ninja_raw(NINJA_CURRENCY_URL, league_name, "Currency")
            if test:
                _league_cache = league_name
                _league_cache_ts = time.time()
                return league_name
    except Exception:
        pass
    _league_cache = "Standard"
    _league_cache_ts = time.time()
    return _league_cache


def _resolve_league(league: str) -> str:
    return league if league else _get_current_league()


def _fetch_ninja_raw(base_url: str, league: str, type_name: str) -> list:
    """Fetch data from poe.ninja API (no caching)."""
    try:
        resp = httpx.get(
            base_url,
            params={"league": league, "type": type_name},
            headers=HEADERS,
            follow_redirects=True,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("lines", [])
    except Exception:
        return []


def _fetch_ninja(base_url: str, league: str, type_name: str) -> list:
    """Fetch data from poe.ninja API with caching."""
    key = (league, type_name)
    cached = _ninja_cache.get(key)
    if cached and (time.time() - cached[0]) < _NINJA_TTL:
        return cached[1]
    lines = _fetch_ninja_raw(base_url, league, type_name)
    _ninja_cache[key] = (time.time(), lines)
    return lines


def _fetch_currency(league: str, type_name: str) -> list:
    return _fetch_ninja(NINJA_CURRENCY_URL, league, type_name)


def _fetch_items(league: str, type_name: str) -> list:
    return _fetch_ninja(NINJA_ITEM_URL, league, type_name)


def _match_score(query: str, name: str) -> int:
    """Score match quality: 3=exact, 2=startswith, 1=contains, 0=no match."""
    q = query.lower()
    n = name.lower()
    if q == n:
        return 3
    if n.startswith(q):
        return 2
    if q in n:
        return 1
    return 0


def _format_trend(sparkline: dict | None) -> str:
    """Format 7-day price trend from sparkline data."""
    if not sparkline:
        return "n/a"
    change = sparkline.get("totalChange", 0)
    if change is None:
        return "n/a"
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.1f}%"


def _search_currency(query: str, league: str) -> list[dict]:
    """Search currency/fragment types."""
    results = []
    for type_name in CURRENCY_TYPES:
        lines = _fetch_currency(league, type_name)
        for line in lines:
            name = line.get("currencyTypeName", "")
            score = _match_score(query, name)
            if score > 0:
                chaos = line.get("chaosEquivalent", 0)
                receive = line.get("receive") or {}
                results.append({
                    "name": name,
                    "chaos_value": chaos,
                    "divine_value": None,
                    "listing_count": receive.get("listing_count", 0),
                    "trend_7d": _format_trend(line.get("receiveSparkLine")),
                    "category": type_name,
                    "_score": score,
                })
    return results


def _search_items(query: str, league: str, categories: list[str]) -> list[dict]:
    """Search item types."""
    results = []
    for cat in categories:
        type_names = ITEM_TYPES.get(cat, [])
        for type_name in type_names:
            lines = _fetch_items(league, type_name)
            for line in lines:
                name = line.get("name", "")
                # For gems, include variant info
                variant = line.get("variant", "")
                display = f"{name} ({variant})" if variant else name
                score = _match_score(query, name)
                if score > 0:
                    results.append({
                        "name": display,
                        "chaos_value": line.get("chaosValue", 0),
                        "divine_value": line.get("divineValue"),
                        "listing_count": line.get("listingCount", 0),
                        "trend_7d": _format_trend(line.get("sparkline")),
                        "category": type_name,
                        "links": line.get("links"),
                        "gem_level": line.get("gemLevel"),
                        "gem_quality": line.get("gemQuality"),
                        "_score": score,
                    })
    return results


def _format_results(results: list[dict], max_results: int = 10) -> str:
    """Format matched results into readable output."""
    # Sort by score desc, then chaos value desc
    results.sort(key=lambda r: (-r["_score"], -(r["chaos_value"] or 0)))
    results = results[:max_results]

    if not results:
        return "No results found."

    lines = []
    for r in results:
        parts = [f"**{r['name']}**"]
        parts.append(f"  Chaos: {r['chaos_value']:.1f}")
        if r.get("divine_value") is not None:
            parts.append(f"  Divine: {r['divine_value']:.2f}")
        if r.get("links"):
            parts.append(f"  Links: {r['links']}")
        if r.get("gem_level"):
            parts.append(f"  Level: {r['gem_level']}")
        if r.get("gem_quality"):
            parts.append(f"  Quality: {r['gem_quality']}%")
        parts.append(f"  Listings: {r['listing_count']}")
        parts.append(f"  7d trend: {r['trend_7d']}")
        parts.append(f"  Category: {r['category']}")
        lines.append("\n".join(parts))

    return "\n\n".join(lines)


async def price_check(query: str, league: str = "", category: str = "") -> str:
    """Search poe.ninja for an item/currency by name.

    Args:
        query: Search keyword to match against item names.
        league: Optional league name. Defaults to current temp league (auto-detected).
        category: Optional hint — "currency", "unique", "gem", "divcard", "map", etc. If empty, searches across common categories.
    """
    league = _resolve_league(league)
    results: list[dict] = []

    if category:
        cat = category.lower()
        if cat in ("currency", "fragment"):
            results = _search_currency(query, league)
        elif cat in ITEM_TYPES:
            results = _search_items(query, league, [cat])
        else:
            return f"Unknown category '{category}'. Available: currency, {', '.join(ITEM_TYPES.keys())}"
    else:
        # Search common categories, stop early if we have enough
        results = _search_currency(query, league)
        if len(results) < 10:
            search_cats = [c for c in DEFAULT_SEARCH_ORDER if c != "currency"]
            for cat in search_cats:
                results.extend(_search_items(query, league, [cat]))
                if len(results) >= 10:
                    break

    header = f"**Price Check** — League: {league}\n\n"
    return header + _format_results(results)


async def currency_overview(league: str = "") -> str:
    """Returns top currency exchange rates for quick reference.

    Args:
        league: Optional league name. Defaults to current temp league (auto-detected).
    """
    league = _resolve_league(league)
    lines = _fetch_currency(league, "Currency")

    if not lines:
        return f"No currency data found for league '{league}'."

    # Sort by chaos value descending
    lines.sort(key=lambda x: x.get("chaosEquivalent", 0), reverse=True)
    top = lines[:20]

    rows = [f"**Currency Overview** — League: {league}\n"]
    rows.append(f"{'Name':<30} {'Chaos Value':>12}")
    rows.append("-" * 44)
    for item in top:
        name = item.get("currencyTypeName", "?")
        chaos = item.get("chaosEquivalent", 0)
        rows.append(f"{name:<30} {chaos:>12,.1f}")

    return "\n".join(rows)
