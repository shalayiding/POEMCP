# PoeMCP

An MCP server that gives any LLM access to Path of Exile game data — gems, unique items, passive tree nodes, item modifiers, maps, scarabs, live pricing, and Path of Building build parsing.

Data is fetched at runtime from [poedb.tw](https://poedb.tw), [poe.ninja](https://poe.ninja), and [poewiki.net](https://www.poewiki.net). No API key required.

## Installation

### Requirements

- Python 3.10+
- [Claude Desktop](https://claude.ai/download) or Claude Code (CLI)
- Internet access (all data is fetched at runtime)

### Steps

```bash
git clone https://github.com/shalayiding/POEMCP.git
cd PoeMCP
pip install -e .
```

## MCP Configuration

Add the following to your Claude config, replacing the path with the directory where you cloned the repo. For a step-by-step visual walkthrough, see [examples.md](examples.md).

### Claude Desktop

File location:

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

**macOS / Linux:**

```json
{
  "mcpServers": {
    "poemcp": {
      "command": "python",
      "args": ["/path/to/PoeMCP/server.py"]
    }
  }
}
```

**Windows:**

```json
{
  "mcpServers": {
    "poemcp": {
      "command": "python",
      "args": ["C:\\path\\to\\PoeMCP\\server.py"]
    }
  }
}
```

### Claude Code (CLI)

Add to your project's `.mcp.json`. See `mcp.json.example` for the template.

> **Note:** Use the full absolute path to `server.py`.

---

## MCP Tools Reference

### `search_gem`

Search for Path of Exile gems by name or description keyword.

|                |                                                                                                                       |
| -------------- | --------------------------------------------------------------------------------------------------------------------- |
| **Parameters** | `query: str` — keyword to match against gem names and descriptions                                                    |
| **Returns**    | List of matching gems with name, type (active/support), tags, and short description. Fuzzy matched, up to 20 results. |

---

### `get_gem_detail`

Get detailed information about a specific gem.

|                |                                                                                                                                      |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| **Parameters** | `gem_name: str` — e.g. `"Fireball"` or `"Leap Slam"`                                                                                 |
| **Returns**    | Full gem stats: tags, mana cost, cast time, quality bonuses, and a per-level table showing damage, radius, and other scaling values. |

---

### `search_item`

Search for Path of Exile unique items by name, base type, or mod keyword.

|                |                                                                                          |
| -------------- | ---------------------------------------------------------------------------------------- |
| **Parameters** | `query: str` — supports fuzzy matching; partial names, base types, and mod text all work |
| **Returns**    | List of matching unique items with name, base type, and key mods. Up to 10 results.      |
| **Examples**   | `"headhunter"`, `"leather belt"`, `"culling strike"`, `"life leech dagger"`              |

---

### `get_item_detail`

Get detailed information about a specific unique item.

|                |                                                                                                                                                                                                    |
| -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Parameters** | `item_name: str` — e.g. `"Headhunter"` or `"Lifesprig"`                                                                                                                                            |
| **Returns**    | Full item data: base type, implicits, all explicit mods with value ranges, flavour text, acquisition methods (div cards, vendor recipes, drop sources), and links to poedb and the Community Wiki. |

---

### `search_passive`

Search for passive skill tree nodes by name or stat keyword.

|                |                                                                                                                                                        |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Parameters** | `query: str` — keyword to match against node names and stats                                                                                           |
|                | `type: str` _(optional)_ — filter by `"keystone"`, `"notable"`, `"mastery"`, or `"ascendancy"`                                                         |
| **Returns**    | List of matching nodes with name, type, and stat preview. Excludes small passives and jewel sockets unless directly matched by name. Up to 20 results. |

---

### `get_passive_detail`

Get full information about a specific passive skill tree node.

|                |                                                                                                                                |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| **Parameters** | `name: str` — e.g. `"Iron Reflexes"` or `"Divine Shield"`                                                                      |
| **Returns**    | Full node stats, mastery effects (if applicable), reminder text, flavour text, ascendancy name, and a list of connected nodes. |

---

### `search_mods`

Search for item modifiers (prefixes and suffixes) available on a given item type.

|                |                                                                                                                                                                                     |
| -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Parameters** | `item_type: str` — item type to look up. Examples: `"helmets str"`, `"daggers"`, `"amulets"`, `"boots dex"`, `"body armours str int"`, `"cobalt jewel"`                             |
|                | `query: str` _(optional)_ — keyword to filter modifiers, e.g. `"life"`, `"fire resistance"`, `"attack speed"`                                                                       |
| **Returns**    | Grouped list of prefixes and suffixes that can roll on that item type, with mod name, tier, item level requirement, and value ranges. Also includes corrupted implicits if present. |

---

### `env_search`

Search for maps and scarabs by name or keyword.

|                |                                                                           |
| -------------- | ------------------------------------------------------------------------- |
| **Parameters** | `query: str` — keyword to match against names and descriptions            |
|                | `category: str` _(optional)_ — `"maps"` or `"scarabs"` to narrow results  |
| **Returns**    | List of matching maps (with tier and boss) or scarabs (with effect text). |

---

### `env_detail`

Get detailed information about a specific map or scarab.

|                |                                                                                                                                          |
| -------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| **Parameters** | `name: str` — e.g. `"Strand Map"` or `"Breach Scarab"`                                                                                   |
| **Returns**    | **Maps:** tiers, boss name, tileset, area level, vaal area, connected maps, and wiki link. **Scarabs:** full effect text and stack size. |

---

### `price_check`

Search poe.ninja for the current price of an item or currency.

|                |                                                                                                                                       |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| **Parameters** | `query: str` — item name to search                                                                                                    |
|                | `league: str` _(optional)_ — league name. Defaults to current temp league (auto-detected).                                            |
|                | `category: str` _(optional)_ — hint to narrow search: `"currency"`, `"unique"`, `"gem"`, `"divcard"`, `"map"`, etc.                   |
| **Returns**    | Item name, price in chaos orbs and divine orbs, number of active listings, and the league queried. Results are cached for 15 minutes. |

---

### `currency_overview`

Get the top currency exchange rates from poe.ninja.

|                |                                                                                                                                          |
| -------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| **Parameters** | `league: str` _(optional)_ — defaults to current temp league                                                                             |
| **Returns**    | Top 20 currency items ranked by chaos value, showing chaos equivalent and divine equivalent for each. Results are cached for 15 minutes. |

---

### `fetch_wiki_page`

Fetch and extract readable content from a poewiki.net page.

|                |                                                                                                                                                                                                     |
| -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Parameters** | `wiki_url: str` — full poewiki.net URL, e.g. `"https://www.poewiki.net/wiki/Headhunter"`                                                                                                            |
| **Returns**    | Cleaned page content with navigation and noise stripped, preserving the main article text, mechanics sections, and acquisition info. Useful for deep dives on mechanics not covered by other tools. |

---

### `parse_pob`

Parse a Path of Building export code or share URL into a full build summary.

|                |                                                                                                                                   |
| -------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| **Parameters** | `code_or_url: str` — accepts a raw PoB base64 export code, a pobb.in URL, or a Pastebin URL                                       |
| **Returns**    | Full build summary including:                                                                                                     |
|                | • Class, ascendancy, level                                                                                                        |
|                | • Build notes (author's written guide, color codes stripped)                                                                      |
|                | • Progression stages — each gear/skill/tree loadout with stage title and node count, so you can follow a build guide step by step |
|                | • Bandit choice and Pantheon gods                                                                                                 |
|                | • Key stats (Life, ES, Armour, Evasion, DPS, Hit Chance, etc.)                                                                    |
|                | • All skill links grouped by slot                                                                                                 |
|                | • Every equipped item with full mod list (implicits + explicits, crafted mods labelled)                                           |
|                | • Allocated keystones and notable passives from the passive tree                                                                  |

**Supported URL formats:**

```
https://pobb.in/xxxxxxxx
https://pobb.in/u/username/xxxxxxxx
https://pastebin.com/xxxxxxxx
```

---

## Disclaimer

This is an unofficial fan project, not affiliated with or endorsed by Grinding Gear Games. Game content (item names, skill names, passive nodes, etc.) is the intellectual property of Grinding Gear Games. Data is fetched at runtime from poedb.tw, poe.ninja, and poewiki.net — this tool is for personal, non-commercial use only.

