import httpx

from scrapers.common import HEADERS, Cache

_tree_cache: Cache[dict] = Cache()

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
    if node.get("classStartIndex") is not None:
        return "class_start"
    if node.get("isAscendancyStart"):
        return "ascend_start"
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
    if not found.get("in") and not found.get("out") and ntype not in ("class_start",):
        sections.append(
            "**Note:** no fixed tree location — this is almost certainly a Cluster Jewel notable "
            "(only exists on a Large/Medium Cluster Jewel roll, not path-able via passive_tree_path)."
        )
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


def _neighbor_ids(node: dict) -> set[str]:
    return {str(nid) for nid in (node.get("in", []) + node.get("out", []))}


def _shortest_new_node_path(tree: dict, allocated_ids: set[str], class_start_id: str, target_id: str):
    """0-1 BFS mirroring PathOfBuilding's PassiveSpec:BuildPathFromNode.

    Distance = number of NEW (currently unallocated) nodes that must be allocated to
    reach target_id, moving freely through already-allocated nodes (weight 0) and paying
    1 point per unallocated node stepped into. Respects PoB's traversal rules: can't pass
    through class-start/ascendancy-start nodes, can't cross ascendancy boundaries, can't
    path onward from a mastery node.

    Returns {"distance": int, "path": [node_id, ...]} or None if unreachable.
    """
    from collections import deque

    by_id = tree["by_id"]
    if class_start_id not in by_id:
        return None

    dist = {class_start_id: 0}
    parent: dict[str, str | None] = {class_start_id: None}
    dq = deque([class_start_id])

    while dq:
        cur_id = dq.popleft()
        cur = by_id[cur_id]
        cur_dist = dist[cur_id]
        if cur["_type"] == "mastery":
            continue  # PoB rule: paths can't continue past a mastery node

        cur_asc = cur.get("ascendancyName", "")
        for nid in _neighbor_ids(cur):
            other = by_id.get(nid)
            if not other:
                continue
            if other["_type"] in ("class_start", "ascend_start"):
                continue  # can't pass through start nodes (only start FROM them)

            other_asc = other.get("ascendancyName", "")
            if not (cur_asc == other_asc or (cur_dist == 0 and not other_asc)):
                continue  # can't cross ascendancy boundaries (except leaving the class start)

            weight = 0 if nid in allocated_ids else 1
            new_dist = cur_dist + weight
            if new_dist < dist.get(nid, 10**9):
                dist[nid] = new_dist
                parent[nid] = cur_id
                (dq.appendleft if weight == 0 else dq.append)(nid)

    if target_id not in dist:
        return None
    path = []
    node_id = target_id
    while node_id is not None:
        path.append(node_id)
        node_id = parent.get(node_id)
    path.reverse()
    return {"distance": dist[target_id], "path": path}


def passive_tree_path(build_url: str, target_node: str) -> str:
    """Find the shortest passive-tree path from a build's currently allocated nodes to a target node.

    Mirrors Path of Building's own pathing algorithm (same traversal rules: can't cut
    through class-start/ascendancy-start nodes, can't cross ascendancy boundaries, can't
    path onward from a mastery). Distance is the number of NEW points that would need to
    be spent — moving through nodes you've already allocated is free.

    Args:
        build_url: A pobb.in or pastebin.com URL for the build to path from.
        target_node: Name of the notable/keystone/passive to path to, e.g. "Cult-Leader".
    """
    from scrapers.player.pob import _decode_pob, _fetch_raw

    try:
        code = _fetch_raw(build_url)
        root = _decode_pob(code)
    except Exception as e:
        return f"Failed to load build: {e}"

    build_el = root.find("Build")
    class_name = (build_el.get("className", "") if build_el is not None else "").strip()
    if not class_name:
        return "Could not determine character class from this build."

    tree_el = root.find("Tree")
    spec = tree_el.find("Spec") if tree_el is not None else None
    nodes_str = spec.get("nodes", "") if spec is not None else ""
    allocated_ids = set(nodes_str.split(",")) if nodes_str else set()

    tree = _load_tree()
    by_id = tree["by_id"]

    class_start_id = None
    for nid, node in by_id.items():
        if node["_type"] == "class_start" and node.get("name", "").lower() == class_name.lower():
            class_start_id = nid
            break
    if not class_start_id:
        return f"Could not find a class-start node matching '{class_name}' in the passive tree."

    target_lower = target_node.strip().lower()
    target_matches = [n for n in tree["all_nodes"] if n.get("name", "").strip().lower() == target_lower]
    if not target_matches:
        return f"No passive node found with name '{target_node}'. Try search_passive to find the correct name."
    target = target_matches[0]
    target_id = target["_id"]

    if target_id in allocated_ids:
        return f"'{target['name']}' is already allocated in this build."

    if not target.get("in") and not target.get("out"):
        return (
            f"'{target['name']}' has no fixed location on the passive tree — it's not something you "
            "can path to. This is almost always a Cluster Jewel notable: it only exists on a Large/"
            "Medium Cluster Jewel roll, which generates its own small local tree when socketed into a "
            "jewel socket. Look for the jewel via search_item/price_check instead of pathing to it here."
        )

    result = _shortest_new_node_path(tree, allocated_ids, class_start_id, target_id)
    if result is None:
        return f"No valid path found from this build's tree to '{target['name']}' (may be behind an unreachable ascendancy boundary)."

    path_names = []
    for nid in result["path"]:
        node = by_id[nid]
        marker = "already allocated" if nid in allocated_ids or nid == class_start_id else "NEW"
        label = node.get("name", "").strip() or f"[unnamed {node['_type']}]"
        path_names.append(f"{label} ({node['_type']}, {marker})")

    lines = [
        f"**Path to {target['name']}:** {result['distance']} new point(s) required",
        "",
        " → ".join(f"{n.get('name', '').strip() or n['_type']}" for n in (by_id[nid] for nid in result["path"])),
        "",
        "Full path (already-allocated nodes are free to pass through):",
    ]
    for line in path_names:
        lines.append(f"- {line}")

    return "\n".join(lines)
