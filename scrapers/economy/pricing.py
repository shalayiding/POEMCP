"""poe.ninja economy data — price checking and currency overview.

poe.ninja restructured its site around the PoE1/PoE2 split (mid-2026):
the old per-type endpoints (`/api/data/currencyoverview`, `/api/data/itemoverview`)
are gone, replaced by a single bulk endpoint. League auto-detection no longer
scrapes the poe.ninja homepage (it now serves obfuscated placeholder league
names); it queries the official pathofexile.com leagues API instead.
"""

import re
import time

import httpx

from scrapers.common import HEADERS

POE_LEAGUES_URL = "https://www.pathofexile.com/api/leagues"
NINJA_DENSE_URL = "https://poe.ninja/poe1/api/economy/current/dense/overviews"

# Maps our category hints to poe.ninja's `type` field.
# Covers every type returned by the dense overview endpoint (checked against a live response).
ITEM_TYPES = {
    "currency": ["Currency", "Fragment"],
    "unique": [
        "UniqueWeapon", "UniqueArmour", "UniqueAccessory", "UniqueFlask", "UniqueJewel",
        "UniqueMap", "UniqueRelic", "UniqueIdol", "UniqueTincture",
    ],
    "gem": ["SkillGem"],
    "imbuedgem": ["ImbuedGem"],
    "divcard": ["DivinationCard"],
    "map": ["Map"],
    "blightedmap": ["BlightedMap"],
    "blightravagedmap": ["BlightRavagedMap"],
    "scourgedmap": ["ScourgedMap"],
    "valdomap": ["ValdoMap"],
    "essence": ["Essence"],
    "scarab": ["Scarab"],
    "oil": ["Oil"],
    "fossil": ["Fossil"],
    "resonator": ["Resonator"],
    "cluster": ["ClusterJewel"],
    "forbiddenjewel": ["ForbiddenJewel"],
    "base": ["BaseType"],
    "vial": ["Vial"],
    "omen": ["Omen"],
    "invitation": ["Invitation"],
    "beast": ["Beast"],
    "incubator": ["Incubator"],
    "deliriumorb": ["DeliriumOrb"],
    "artifact": ["Artifact"],
    "tattoo": ["Tattoo"],
    "memory": ["Memory"],
    "incursiontemple": ["IncursionTemple"],
    "coffin": ["Coffin"],
    "allflameember": ["AllflameEmber"],
    "kalguuranrune": ["KalguuranRune"],
    "runegraft": ["Runegraft"],
    "wombgift": ["Wombgift"],
    "djinncoin": ["DjinnCoin"],
    "astrolabe": ["Astrolabe"],
    "shrinebelt": ["ShrineBelt"],
}

# Categories searched when no category hint is given (most common first)
DEFAULT_SEARCH_ORDER = ["currency", "unique", "gem", "divcard", "map"]

_PRIVATE_LEAGUE_RE = re.compile(r"\(PL\d+\)$")

# --- Caches ---
_league_cache: str | None = None
_league_cache_ts: float = 0
_LEAGUE_TTL = 3600  # 1 hour

_dense_cache: dict[str, tuple[float, dict]] = {}
_NINJA_TTL = 900  # 15 minutes


def _get_current_league() -> str:
    """Auto-detect current temp league from the official pathofexile.com leagues API.

    Falls back to Standard if the API is unreachable or no temp league is found.
    """
    global _league_cache, _league_cache_ts
    if _league_cache and (time.time() - _league_cache_ts) < _LEAGUE_TTL:
        return _league_cache

    permanent = {"Standard", "Hardcore"}
    try:
        resp = httpx.get(
            POE_LEAGUES_URL,
            params={"type": "main", "realm": "pc"},
            headers=HEADERS,
            follow_redirects=True,
            timeout=15,
        )
        resp.raise_for_status()
        leagues = resp.json()

        candidates = []
        for league in leagues:
            league_id = league.get("id", "")
            if league_id in permanent or _PRIVATE_LEAGUE_RE.search(league_id):
                continue
            rules = {rule.get("id") for rule in league.get("rules", [])}
            if "NoParties" in rules or "HardMode" in rules:
                continue
            candidates.append(league_id)

        if candidates:
            # Prefer the softcore variant if both are present.
            softcore = [c for c in candidates if "Hardcore" not in c]
            chosen = softcore[0] if softcore else candidates[0]
            _league_cache = chosen
            _league_cache_ts = time.time()
            return chosen
    except Exception:
        pass
    _league_cache = "Standard"
    _league_cache_ts = time.time()
    return _league_cache


def _resolve_league(league: str) -> str:
    return league if league else _get_current_league()


def _fetch_dense_overview(league: str) -> dict:
    """Fetch and cache poe.ninja's bulk 'dense overviews' blob for a league.

    Returns {type_name: [line, ...]}, merging currencyOverviews and
    itemOverviews (poe.ninja duplicates Currency/Fragment in both).
    """
    cached = _dense_cache.get(league)
    if cached and (time.time() - cached[0]) < _NINJA_TTL:
        return cached[1]

    type_to_lines: dict = {}
    try:
        resp = httpx.get(
            NINJA_DENSE_URL,
            params={"league": league, "language": "en"},
            headers=HEADERS,
            follow_redirects=True,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        for section in ("itemOverviews", "currencyOverviews"):
            for overview in data.get(section, []):
                type_to_lines[overview.get("type")] = overview.get("lines", [])
    except Exception:
        pass

    _dense_cache[league] = (time.time(), type_to_lines)
    return type_to_lines


def _get_divine_rate(league: str) -> float | None:
    """Chaos value of a Divine Orb, used to offer chaos<->divine context."""
    lines = _fetch_dense_overview(league).get("Currency", [])
    for line in lines:
        if line.get("name") == "Divine Orb":
            return line.get("chaos")
    return None


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


def _format_trend(graph: list) -> str:
    """Format the most recent daily % change from poe.ninja's 7-point graph."""
    if not graph:
        return "n/a"
    latest = graph[-1]
    if latest is None:
        return "n/a"
    sign = "+" if latest >= 0 else ""
    return f"{sign}{latest:.1f}% (24h)"


def _search_type(query: str, league: str, type_names: list[str]) -> list[dict]:
    """Search one or more poe.ninja overview types for a name match."""
    overviews = _fetch_dense_overview(league)
    results = []
    for type_name in type_names:
        for line in overviews.get(type_name, []):
            name = line.get("name", "")
            score = _match_score(query, name)
            if score == 0:
                continue
            results.append({
                "name": name,
                "variant": line.get("variant"),
                "chaos_value": line.get("chaos", 0),
                "trend": _format_trend(line.get("graph")),
                "category": type_name,
                "_score": score,
            })
    return results


def _format_results(results: list[dict], divine_rate: float | None, max_results: int = 10) -> str:
    """Format matched results into readable output."""
    results.sort(key=lambda r: (-r["_score"], -(r["chaos_value"] or 0)))
    results = results[:max_results]

    if not results:
        return "No results found."

    lines = []
    for r in results:
        display_name = f"{r['name']} ({r['variant']})" if r.get("variant") else r["name"]
        parts = [f"**{display_name}**"]
        parts.append(f"  Chaos: {r['chaos_value']:,.1f}")
        if divine_rate:
            parts.append(f"  Divine: {r['chaos_value'] / divine_rate:.2f}")
        parts.append(f"  Trend: {r['trend']}")
        parts.append(f"  Category: {r['category']}")
        lines.append("\n".join(parts))

    return "\n\n".join(lines)


async def price_check(query: str, league: str = "", category: str = "") -> str:
    """Search poe.ninja for an item/currency by name.

    Args:
        query: Search keyword to match against item names.
        league: Optional league name. Defaults to current temp league (auto-detected).
        category: Optional hint — "currency", "unique", "gem", "divcard", "map", "scarab", "essence",
            "fossil", "oil", "vial", "omen", "invitation", "beast", "incubator", "deliriumorb",
            "tattoo", "artifact", "cluster", "resonator", etc. If empty, searches across common categories.
    """
    league = _resolve_league(league)
    divine_rate = _get_divine_rate(league)
    results: list[dict] = []

    if category:
        cat = category.lower()
        if cat not in ITEM_TYPES:
            return f"Unknown category '{category}'. Available: {', '.join(ITEM_TYPES.keys())}"
        results = _search_type(query, league, ITEM_TYPES[cat])
    else:
        for cat in DEFAULT_SEARCH_ORDER:
            results.extend(_search_type(query, league, ITEM_TYPES[cat]))
            if len(results) >= 10:
                break

    header = f"**Price Check** — League: {league}\n\n"
    return header + _format_results(results, divine_rate)


async def currency_overview(league: str = "") -> str:
    """Returns top currency exchange rates for quick reference.

    Args:
        league: Optional league name. Defaults to current temp league (auto-detected).
    """
    league = _resolve_league(league)
    lines = _fetch_dense_overview(league).get("Currency", [])

    if not lines:
        return f"No currency data found for league '{league}'."

    lines = sorted(lines, key=lambda x: x.get("chaos", 0), reverse=True)
    top = lines[:20]

    rows = [f"**Currency Overview** — League: {league}\n"]
    rows.append(f"{'Name':<30} {'Chaos Value':>12}")
    rows.append("-" * 44)
    for item in top:
        name = item.get("name", "?")
        chaos = item.get("chaos", 0)
        rows.append(f"{name:<30} {chaos:>12,.1f}")

    return "\n".join(rows)
