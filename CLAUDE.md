# PoeMCP — Claude Code Reference

MCP server that exposes Path of Exile game data to LLM agents. Two data strategies are in play:
web scraping (poedb.tw, poewiki.net — fragile, breaks silently when the site changes) and
**parsing Path of Building Community's static game-data export** (gems, uniques, mods — much
more stable, see "Path of Building data source" below). No official API is used for game data
(GGG's Developer API is closed to new app registrations as of this writing — see "Known gotchas").

## Quick orientation

```
server.py               Entry point — FastMCP wiring, 14 tool registrations
scrapers/
  common.py             fetch_page(), Cache class, BASE_URL, HEADERS (poedb.tw scraping)
  pob_data.py            fetch_lua_file(), parse_lua_table(), parse_lua_assignments() — PathOfBuilding data
  wiki.py                fetch_wiki_page() — poewiki.net extractor
  player/                Gems (PoB), unique items (PoB), passive tree (GGG JSON), PoB build parser
  mods/                  Prefix/suffix modifier lookup by item type (PoB)
  env/                   Maps & scarabs — still poedb.tw (routed via __init__.py); maps is currently BROKEN, see gotchas
  economy/               poe.ninja pricing & currency rates + official pathofexile.com league detection
```

## Setup

```powershell
python -m venv venv
venv\Scripts\pip install -e .
```

Run server manually (for testing):
```powershell
venv\Scripts\python server.py
```

MCP config is in `.mcp.json` (gitignored — absolute paths are machine-specific).
Use `.mcp.json.example` as the template.

## Dependencies

- `mcp[cli]` — FastMCP framework
- `httpx` — HTTP client (sync and async)
- `beautifulsoup4` — HTML parsing
- Python 3.10+ required (3.13 used in venv)

Standard library: `base64`, `zlib`, `xml.etree.ElementTree`, `re`, `json`, `time`.

## Tools (14 total)

| Domain | Tools |
|--------|-------|
| Player | `search_gem`, `get_gem_detail`, `search_item`, `get_item_detail`, `search_passive`, `get_passive_detail`, `passive_tree_path`, `parse_pob` |
| Mods | `search_mods` |
| Env | `env_search`, `env_detail` |
| Economy | `price_check`, `currency_overview` |
| Universal | `fetch_wiki_page` |

Each tool function lives in its scraper module and is registered in `server.py` via `mcp.tool()`.

## Registering a new tool

1. Implement the function in the appropriate scraper module.
2. Import it in `server.py`.
3. Add `mcp.tool()(function_name)` below the relevant domain block.
4. Update `README.md` tool table.

## Data sources

| Source | URL | Used for |
|--------|-----|----------|
| **PathOfBuilding (GitHub, `dev` branch)** | `raw.githubusercontent.com/PathOfBuildingCommunity/PathOfBuilding/dev/src/Data/...` | Gems, unique items, prefix/suffix mods |
| poedb.tw | `https://poedb.tw/us` | Maps, scarabs (maps list is currently broken — page structure changed) |
| poewiki.net | `https://www.poewiki.net` | Deep mechanic explanations |
| poe.ninja | `https://poe.ninja/poe1/...` | Live pricing, currency rates |
| **pathofexile.com (official, unauthenticated)** | `www.pathofexile.com/api/leagues` | League auto-detection |
| GGG skilltree-export | GitHub raw | Passive tree node data (JSON) |

poedb.tw and the old poe.ninja/GGG-league endpoints used to cover gems/items/mods/pricing too —
they broke (site restructuring, PoE2 split) and were replaced. See git history on
`scrapers/player/items.py`, `scrapers/player/gems.py`, `scrapers/mods/item_mods.py`,
`scrapers/economy/pricing.py` for what the old scrapers looked like.

## Caching conventions

Use the `Cache` class from `scrapers/common.py`. All caches are in-memory (reset on server restart).

| Data type | TTL |
|-----------|-----|
| List pages (gems/items/maps/scarabs) | 3600 s (1 hour) |
| Mod JSON per item-type slug | 3600 s |
| Passive tree (GitHub JSON) | 3600 s |
| poe.ninja price data | 900 s (15 min) |
| League auto-detection | 3600 s |

Pattern used everywhere:
```python
_cache = Cache()
_CACHE_KEY = "all_gems"

def _get_all_gems():
    cached = _cache.get(_CACHE_KEY)
    if cached:
        return cached
    # ... fetch and parse ...
    _cache.set(_CACHE_KEY, result)
    return result
```

## Fuzzy search scoring

All `search_*` functions use the same scoring ladder:

| Score | Condition |
|-------|-----------|
| 100 | Exact name match (case-insensitive) |
| 80 | Name starts with query |
| 60 | Query substring in name |
| 50 | All query words present in name |
| 40 | Query in base type / secondary field |
| 35 | Words match across name + base type |
| 20 | Query in any string field |
| 10 | Words match across all fields |

Return top 10–20 results, sorted descending by score. Only return results with score > 0.

## Path of Building data source (gems, uniques, mods)

`scrapers/pob_data.py` fetches and parses PathOfBuilding Community's `src/Data/*.lua` files —
GGG's own game-data export, resynced by PoB maintainers every patch/league. This is why the
default branch matters:

- **Branch is `dev`, not `main`.** `git remote show origin` on the PoB repo confirms `HEAD branch: dev`.
  Using `main` 404s.
- **No pinned commit** — `POB_RAW_BASE` always points at branch HEAD. Combined with the 1-hour
  `Cache` TTL (same as everything else, see Caching conventions), this is the auto-update
  mechanism: once PoB syncs a new league's data (they do this promptly — last commit during this
  investigation was 4 days old), our gem/item/mod tools pick it up within an hour, with no code
  changes. This matters because players are season/league-centric — stale item data across a
  league launch would make the tools actively misleading.

**Two Lua shapes, two parsers (both in `pob_data.py`):**
- `parse_lua_table(text)` — for files that are one `return { ... }` literal (`Gems.lua`,
  `ModExplicit.lua`, `ModCorrupted.lua`, `ModJewel.lua`, `ModJewelCluster.lua`, `ModFlask.lua`,
  `ModTincture.lua`). Handles nested tables, mixed array+hash tables (positional values land in
  an injected `_array` key), strings, numbers, `true`/`false`/`nil`, comments.
- `parse_lua_assignments(text, var_name)` — for files that are a sequence of
  `var_name["Key"] = { ... }` statements rather than one literal (`Skills/*.lua`). Regex-finds
  each assignment, then brace-matches to extract and parse the value.
- Long-bracket string literals (`[[ ... ]]`) — used by `Uniques/*.lua` for whole item-text
  blocks — are extracted with a dedicated regex in `scrapers/player/items.py`
  (`_ITEM_BLOCK_RE`), not the generic table parser; each block is plain PoB item-text, the same
  format `scrapers/player/pob.py` already parses from build exports.

**Files consumed:**
- `Gems.lua` (`search_gem`/`get_gem_detail` base info) + `Skills/{act_dex,act_int,act_str,glove,minion,other,spectre,sup_dex,sup_int,sup_str}.lua`
  (per-skill `description`, `levels[]` raw scaling data, `qualityStats`) — joined via
  `grantedEffectId`. **Known gap:** level-scaling output is raw PoB formula inputs (mana cost,
  damage effectiveness, crit chance), not the fully rendered tooltip text poedb used to show —
  that requires GGG's stat-description template engine, not implemented.
- `Uniques/{amulet,axe,belt,body,boots,bow,claw,dagger,fishing,flask,gloves,graft,helmet,jewel,mace,quiver,ring,shield,staff,sword,tincture,wand}.lua`
  + `Uniques/Special/{New,race}.lua` for `search_item`/`get_item_detail`. Each item text block may
  list multiple `Variant:` lines (historical nerf/buff versions); mods tagged `{variant:N,...}`
  are filtered to whichever variant index is *last* in the list (assumed to be "Current").
  **Skipped:** `Uniques/Special/{Generated,WatchersEye,BoundByDestiny}.lua` — these are
  procedural mod-pool tables (e.g. Watcher's Eye aura mods), a different Lua shape entirely; not parsed.
- `ModExplicit.lua` + `ModCorrupted.lua` (weapons/armour/jewellery/quivers), `ModJewel.lua`
  (regular + abyss jewels), `ModJewelCluster.lua`, `ModFlask.lua`, `ModTincture.lua` for
  `search_mods`. Each mod entry's `weightKey`/`weightVal` arrays are GGG's real drop-weight table
  (which item base tags a mod can roll on) — see "Item-type tag mapping" below.

## HTML selectors by source

### poedb.tw — maps (`/us/Maps`) — BROKEN, needs a new approach
- Old selector: table under h5 containing "Maps List" — this section no longer exists on the page.
- The page now only has: Unique Maps (as `div.d-flex.border-top.rounded`, same pattern as
  gems/scarabs), Atlas Tree Modifiers, Map Device Recipes, Map Corruption, Anoint Blight Map, Map
  Costs. The plain tiered map list (Strand Map etc.) isn't in the static HTML anymore — likely
  moved to client-side rendering. Individual map detail pages (`/us/Strand_Map`) still work.
- Not yet fixed — `scrapers/env/maps.py` still uses the stale selector and returns no results.

### poedb.tw — map detail (`/us/{Map_Name}`)
- First table: area attributes (Level, Vaal Area, Atlas Linked)
- Connected maps: `Atlas Linked` row → `tds[1].find_all("a")`

### poedb.tw — scarabs (`/us/Scarab`)
- Entries: `div.d-flex.border-top.rounded`
- Properties (Stack Size, Limit): `div.property`
- Effect text: `div.explicitMod`

### poewiki.net
- Content root: `div.mw-parser-output`
- Sections: `h2` / `h3` headings with sibling `p`, `ul`, `ol`, `table`
- Strip `.tooltip` elements before extracting text
- Em-dashes (`—` U+2014) in poedb.tw content → replace with `-` for consistency

## poe.ninja integration

poe.ninja restructured its site around the PoE1/PoE2 split (mid-2026). The old per-type
endpoints (`/api/data/currencyoverview`, `/api/data/itemoverview`) 404 unconditionally now — do
not resurrect them.

**League detection** — no longer scrapes poe.ninja's homepage (it now serves an obfuscated JSON
blob with placeholder-looking league names, e.g. `League Starting SOON (PL81411)` — those `(PL#)`
suffixes are private-league IDs, not noise to work around). Instead calls the **official,
unauthenticated** `https://www.pathofexile.com/api/leagues?type=main&realm=pc` (note: this is
different from `api.pathofexile.com/leagues`, which the old code correctly identified as
Cloudflare-blocked — the `www.pathofexile.com/api/...` host is not blocked and needs no OAuth).
Filters out `Standard`/`Hardcore`, IDs matching `\(PL\d+\)$` (private leagues), and leagues with
`NoParties`/`HardMode` rules; prefers the softcore variant. Falls back to `"Standard"` on failure.

**Bulk data endpoint:** `https://poe.ninja/poe1/api/economy/current/dense/overviews?league={league}&language=en`
— one request returns **everything** (`currencyOverviews` + `itemOverviews`, every category from
`Currency` to `UniqueWeapon` to `SkillGem`), replacing what used to be ~15 separate per-type
requests. Line shape is flat: `{name, variant?, chaos, graph}` — no `divineValue`,
`listingCount`, `links`, or `gemLevel`/`gemQuality` fields anymore (poe.ninja folds link
count/corruption/gem level into the free-text `variant` field now); `graph` is a 7-point daily
%-change array, not a `{totalChange}` object. Divine value is derived client-side from the
`Divine Orb` chaos price in the same response.

## PoB (Path of Building) parser — `scrapers/player/pob.py`

**Input formats accepted:**
- `https://pobb.in/{id}` or `https://pobb.in/u/{user}/{id}` (fetches `/raw` endpoint)
- `https://pastebin.com/{id}` (fetches `pastebin.com/raw/{id}`)

**Raw pasted export codes are deliberately NOT accepted** — they're several thousand
characters long and reliably get truncated/corrupted when pasted through chat input
(confirmed empirically: a corrupted paste decompresses ~3KB of genuinely valid PoB XML
before hitting a mid-stream zlib error — the decode pipeline itself is correct, verified
byte-for-byte against PoB's own `Common.lua`/`ImportTab.lua` decode logic; the failure is
transit corruption of the pasted string, not a format mismatch). URLs don't have this
problem since the server fetches the code directly — no copy-paste involved. `parse_pob`
rejects non-URL input with a message pointing the user to pobb.in/Pastebin instead.

**Decode pipeline:**
```
base64 URL-safe decode (with padding correction)
  → zlib decompress
    → XML parse (ElementTree)
```

**Key XML elements:**
- `<Build>`: `className`, `ascendClassName`, `level`, `bandit`, `<PlayerStat>` children
- `<Skills>` / `<Skill>` / `<Gem>`: active gems, levels, quality, main skill
- `<Items>` / `<Item>`: item text blocks (Rarity line, name, base type, mods)
- `<ItemSet>`, `<TreeSpec>`, `<SkillSet>`: progression stages via `{N}` index tags
- `<Tree>`: passive node IDs (keystones, notables, node count)
- `<Notes>`: build notes (strip PoB color codes: `{color}...{/color}`)

**PlayerStat coverage and Build Warnings:** PoB writes ~100 computed `<PlayerStat>` values
into every export (it already ran its own calc engine when the user hit Export) — `pob.py`
reads a curated subset into `_KEY_STATS`/`_RESIST_STATS`/`_DEFENSE_STATS`/`_CHARGE_STATS`/
`_EHP_STATS`/`_SUSTAIN_STATS`/`_DPS_BREAKDOWN_STATS`. `_build_warnings()` flags issues
(uncapped resistances, negative chaos res, weakest damage type relative to the others, no
chance-based mitigation layer, degen exceeding regen, unmet attribute requirements) using
these real numbers — no formulas are reimplemented. **Known false positive:** items that
change how a resistance works (e.g. Doryani's Prototype: "Armour also applies to Lightning
Damage taken", "Lightning Resistance does not affect Lightning Damage taken") aren't
special-cased, so the uncapped-resistance warning can fire on a stat that's actually
irrelevant in-game for that specific build. **Known crash class already fixed once:** PoB
reports `inf` for a `MaximumHitTaken` a build is fully immune to (e.g. Chaos Inoculation →
infinite chaos hit pool) — plain `int()` formatting raises `OverflowError` on that; use
`_fmt_stat_int()` for any new PlayerStat display code, not a bare `int(val)`.

**`passive_tree_path(build_url, target_node)`** (`scrapers/player/passives.py`) reimplements
PoB's own tree-pathing algorithm (`PassiveSpec:BuildPathFromNode`, 0-1 BFS: free through
already-allocated nodes, +1 per new node, can't cut through class-start/ascendancy-start
nodes, can't cross ascendancy boundaries, can't path onward from a mastery) against the same
GGG skilltree-export JSON `passives.py` already loads. Detects nodes with no `in`/`out` graph
data (Cluster Jewel-only notables — they have no fixed tree location) and returns a message
pointing at `search_item`/`price_check` instead of a misleading "no path found".

## Item-type tag mapping (`search_mods`)

`ITEM_TYPES` in `scrapers/mods/item_mods.py` maps ~65 friendly item-type names to
`(data_files, weightKey_tags)`. A mod is eligible for a type if its `weightKey` array intersects
the mapped tags (e.g. `"gloves str"` → `["gloves", "str_armour"]`) — this is a simplification of
GGG's real weighted-sum mechanic (union match, not the true weighted-by-tag drop odds), good
enough for "can this mod roll here" but not for precise roll-probability. Regular jewels
(Crimson/Viridian/Cobalt/Prismatic) all map to the single `jewel` tag — colour doesn't split the
mod pool in-game, only which tree area they're meant to socket into. Accepts exact category name,
underscore/space variants, attribute aliases (`strength` → `str`), and fuzzy partial match.
Not covered: Timeless Jewels (no random mod pool), the "Trinkets" poedb used to list (unclear PoE1
equivalent), and precise 1H/2H weapon splitting (both share one base weightKey tag, e.g. `sword`
covers one-hand, two-hand, and thrusting swords alike).

## Adding a new data source

1. Prefer a structured, versioned export over HTML scraping if one exists (see: PathOfBuilding
   for gems/items/mods, GGG skilltree-export for passives). It breaks far less often than parsing
   a live site's HTML, and — if it's kept in sync with the game like PoB's data — updates
   automatically every league for free. Only fall back to scraping `poedb.tw`/`poewiki.net` HTML
   when no such export exists (currently: maps, scarabs, wiki mechanics).
2. Create a scraper module in the appropriate domain subfolder.
3. HTML: use `fetch_page(url)` from `scrapers/common.py`. PoB Lua data: use `fetch_lua_file()` +
   `parse_lua_table()`/`parse_lua_assignments()` from `scrapers/pob_data.py`.
4. Use `Cache` (or the same TTL-tuple-in-dict pattern) for in-memory caching — never pin a fetched
   file/commit; always read from the source's live HEAD so the 1-hour TTL doubles as auto-update.
5. For async tools (e.g., economy domain), use `httpx.AsyncClient`.
6. Return plain text / markdown strings — MCP delivers them directly to the LLM.
7. Add the tool to `server.py`.

## Known gotchas

- `.mcp.json` uses absolute paths — never commit it (already in `.gitignore`).
- `poedb.tw` uses em-dashes (`—`) in numeric ranges; normalize to `-`.
- GGG's Developer API (`www.pathofexile.com/developer/docs`) is **closed to new app
  registrations** ("We are currently unable to process new applications") — do not design
  features around it unless the project already has a registered `client_id`/`secret` (check
  `/my-account/applications`). This blocks any OAuth-gated data (account stashes, characters,
  currency exchange) until GGG reopens registration.
  - `api.pathofexile.com/leagues` is Cloudflare-blocked regardless; `www.pathofexile.com/api/leagues`
    (no OAuth, no registration) is the one actually in use — see poe.ninja integration above.
  - For a logged-in user's own character/stash/passive-tree data specifically, there's a
    non-OAuth path that doesn't need app registration: the legacy `POESESSID` session-cookie
    endpoints (`{realm}/character-window/get-characters|get-items|get-passive-skills`), the same
    mechanism Path of Building Community's character importer uses today
    (`src/Classes/ImportTab.lua`). If the target account hasn't hidden its characters (a privacy
    toggle, off by default... i.e. most accounts are public), `get-characters` needs no cookie at
    all. Not implemented in this repo yet — no `search_mods`-style tool wraps it.
- Mod text in poedb.tw `str` field (still used for maps/scarabs) is HTML — strip tags with `re.sub(r"<[^>]+>", "", text)`.
- The pobb.in raw URL is `/{id}` → `/raw` (not `/raw/{id}`).
- PathOfBuilding's default branch is `dev`, not `main` — `raw.githubusercontent.com/.../main/...` 404s.

## No formal test suite

Manual tests live in `toolDoc/`. When adding a tool, smoke-test it by running the server and calling the tool through Claude or a direct MCP client before committing.