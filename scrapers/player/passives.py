import httpx

from scrapers.common import HEADERS, Cache

_tree_cache = Cache()

TREE_URL = "https://raw.githubusercontent.com/grindinggear/skilltree-export/master/data.json"


def _load_tree() -> dict:
    cached = _tree_cache.get()
    if cached is not None:
        return cached

    resp = httpx.get(TREE_URL, headers=HEADERS, follow_redirects=True, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    nodes_by_id: dict[str, dict] = {}
    all_nodes: list[dict] = []

    for nid, node in data["nodes"].items():
        node["_id"] = nid
        node["_type"] = _classify_node(node)
        nodes_by_id[nid] = node
        all_nodes.append(node)

    result = {"all_nodes": all_nodes, "by_id": nodes_by_id}
    _tree_cache.set(result)
    return result


def _classify_node(node: dict) -> str:
    if node.get("isKeystone"):
        return "keystone"
    if node.get("isMastery"):
        return "mastery"
    if node.get("isJewelSocket"):
        return "jewel_socket"
    if node.get("isNotable"):
        return "notable"
    if node.get("ascendancyName"):
        return "ascendancy"
    return "small"


def _stats_text(node: dict) -> str:
    parts = []
    for s in node.get("stats", []):
        parts.append(s)
    for me in node.get("masteryEffects", []):
        for s in me.get("stats", []):
            parts.append(s)
    return " ".join(parts).lower()


def _fuzzy_score(query: str, node: dict) -> int:
    q = query.lower()
    name = node.get("name", "").lower().strip()

    if name == q:
        return 100
    if name.startswith(q):
        return 80
    if q in name:
        return 60

    stats = _stats_text(node)
    if q in stats:
        return 30

    # Multi-word: all words present in name+stats
    words = q.split()
    if len(words) > 1:
        combined = name + " " + stats
        if all(w in combined for w in words):
            return 15

    return 0


def search_passive(query: str, type: str = "") -> str:
    """Search for Path of Exile passive skill tree nodes by name or stat keyword.

    Searches across keystones, notables, masteries, and ascendancy passives.
    Small passives and jewel sockets are excluded unless directly matched by name.

    Args:
        query: Search keyword to match against node names and stats.
        type: Optional filter: "keystone", "notable", "mastery", or "ascendancy". If empty, searches all.
    """
    tree = _load_tree()
    type_filter = type.strip().lower()

    scored = []
    for node in tree["all_nodes"]:
        ntype = node["_type"]

        # Apply type filter
        if type_filter:
            if type_filter != ntype:
                continue
        else:
            # Without filter, skip small passives and jewel sockets
            # unless they score highly (exact/startswith name match)
            pass

        score = _fuzzy_score(query, node)
        if score == 0:
            continue

        # Without type filter, require high score for small/jewel nodes
        if not type_filter and ntype in ("small", "jewel_socket") and score < 60:
            continue

        scored.append((score, node))

    scored.sort(key=lambda x: (-x[0], x[1].get("name", "")))

    if not scored:
        msg = f"No passive nodes found matching '{query}'"
        if type_filter:
            msg += f" (type: {type_filter})"
        return msg + "."

    lines = [f"Found {len(scored)} passive(s) matching '{query}':\n"]
    for score, node in scored[:20]:
        ntype = node["_type"]
        name = node.get("name", "").strip()
        label = f"[{ntype}]"
        if node.get("ascendancyName"):
            label = f"[{node['ascendancyName']}]"

        stats = node.get("stats", [])
        stat_preview = "; ".join(stats)
        if len(stat_preview) > 120:
            stat_preview = stat_preview[:117] + "..."

        lines.append(f"- **{name}** {label}")
        if stat_preview:
            lines.append(f"  {stat_preview}")
        lines.append("")

    if len(scored) > 20:
        lines.append(f"... and {len(scored) - 20} more results.")

    return "\n".join(lines)


def get_passive_detail(name: str) -> str:
    """Get detailed information about a specific passive skill tree node.

    Returns full stats, connections, ascendancy info, mastery effects, and flavor text.

    Args:
        name: The passive node name, e.g. "Iron Reflexes" or "Divine Shield".
    """
    tree = _load_tree()
    q = name.strip().lower()

    # Exact then case-insensitive lookup
    found = None
    for node in tree["all_nodes"]:
        node_name = node.get("name", "").strip()
        if node_name == name.strip():
            found = node
            break
        if node_name.lower() == q and found is None:
            found = node

    if not found:
        return f"No passive node found with name '{name}'. Try search_passive to find it."

    sections = []
    node_name = found.get("name", "").strip()
    ntype = found["_type"]

    # Header
    sections.append(f"# {node_name}")
    sections.append(f"**Type:** {ntype}")
    if found.get("ascendancyName"):
        sections.append(f"**Ascendancy:** {found['ascendancyName']}")
    sections.append("")

    # Stats
    stats = found.get("stats", [])
    if stats:
        sections.append("**Stats:**")
        for s in stats:
            sections.append(f"- {s}")
        sections.append("")

    # Mastery effects
    mastery_effects = found.get("masteryEffects", [])
    if mastery_effects:
        sections.append("**Mastery Effects (choose one):**")
        for i, me in enumerate(mastery_effects, 1):
            me_stats = "; ".join(me.get("stats", []))
            sections.append(f"  {i}. {me_stats}")
        sections.append("")

    # Reminder text
    reminders = found.get("reminderText", [])
    if reminders:
        for r in reminders:
            sections.append(f"*{r}*")
        sections.append("")

    # Flavor text
    flavors = found.get("flavourText", [])
    if flavors:
        sections.append(f"*\"{' '.join(flavors)}\"*")
        sections.append("")

    # Connections (resolve IDs to names)
    out_ids = found.get("out", [])
    in_ids = found.get("in", [])
    connections = set(out_ids + in_ids)
    if connections:
        conn_names = []
        for cid in sorted(connections):
            cnode = tree["by_id"].get(str(cid))
            if cnode:
                cname = cnode.get("name", "").strip()
                ctype = cnode["_type"]
                if cname:
                    conn_names.append(f"{cname} ({ctype})")
        if conn_names:
            sections.append("**Connected to:**")
            for cn in conn_names:
                sections.append(f"- {cn}")
            sections.append("")

    return "\n".join(sections)
