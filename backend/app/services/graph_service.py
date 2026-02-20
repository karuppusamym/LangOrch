"""Graph extraction — converts CKP workflow_graph into nodes + edges for visualization."""

from __future__ import annotations

from typing import Any

# Node type → colour hint for the frontend
NODE_COLORS: dict[str, str] = {
    "sequence": "#3B82F6",       # blue
    "logic": "#F59E0B",          # amber
    "loop": "#8B5CF6",           # violet
    "parallel": "#06B6D4",       # cyan
    "human_approval": "#EF4444", # red
    "llm_action": "#10B981",     # emerald
    "processing": "#6366F1",     # indigo
    "verification": "#F97316",   # orange
    "transform": "#EC4899",      # pink
    "subflow": "#14B8A6",        # teal
    "terminate": "#6B7280",      # gray
}


def extract_graph(workflow_graph: dict[str, Any]) -> dict[str, Any]:
    """Return ``{nodes: [...], edges: [...]}`` suitable for React Flow.

    Each node carries ``id``, ``type`` (CKP type), ``label``, ``agent``,
    ``color``, and ``position`` (auto-laid-out).

    Each edge carries ``id``, ``source``, ``target``, ``label`` (optional),
    and ``animated`` (for conditional / approval edges).
    """
    raw_nodes: dict[str, Any] = workflow_graph.get("nodes", {})
    start_node: str = workflow_graph.get("start_node", "")

    out_nodes: list[dict[str, Any]] = []
    out_edges: list[dict[str, Any]] = []
    edge_counter = 0

    def _add_edge(
        src: str,
        tgt: str | None,
        label: str = "",
        animated: bool = False,
    ) -> None:
        nonlocal edge_counter
        if not tgt or tgt not in raw_nodes:
            return
        edge_counter += 1
        out_edges.append(
            {
                "id": f"e{edge_counter}",
                "source": src,
                "target": tgt,
                "label": label,
                "animated": animated,
            }
        )

    # ── Build ordered node list starting from start_node via BFS ────────
    visited: set[str] = set()
    queue: list[str] = [start_node] if start_node else list(raw_nodes.keys())

    # Ensure every node is visited even if unreachable
    all_ids = list(raw_nodes.keys())

    bfs_order: list[str] = []
    while queue:
        nid = queue.pop(0)
        if nid in visited or nid not in raw_nodes:
            continue
        visited.add(nid)
        bfs_order.append(nid)

        node = raw_nodes[nid]
        ntype = node.get("type", "sequence")

        # Collect successor node IDs so BFS can visit them
        successors: list[str] = []
        next_node = node.get("next_node")
        if next_node:
            successors.append(next_node)

        if ntype == "logic":
            for rule in node.get("rules", []):
                rn = rule.get("next_node")
                if rn:
                    successors.append(rn)
            dn = node.get("default_next_node")
            if dn:
                successors.append(dn)

        elif ntype == "human_approval":
            for key in ("on_approve", "on_reject", "on_timeout"):
                v = node.get(key)
                if v:
                    successors.append(v)

        elif ntype == "loop":
            bn = node.get("body_node")
            if bn:
                successors.append(bn)

        elif ntype == "parallel":
            for branch in node.get("branches", []):
                sn = branch.get("start_node")
                if sn:
                    successors.append(sn)

        for s in successors:
            if s not in visited:
                queue.append(s)

    # Add any nodes that BFS didn't reach
    for nid in all_ids:
        if nid not in visited:
            bfs_order.append(nid)

    # ── Produce nodes with auto-layout positions ────────────────────────
    col_width = 280
    row_height = 120
    cols = 3  # wrap after 3 columns

    for idx, nid in enumerate(bfs_order):
        node = raw_nodes[nid]
        ntype = node.get("type", "sequence")
        # Prefer description as the card title; fall back to a humanised node-ID
        description = node.get("description") or None
        label = description or nid.replace("_", " ").title()
        agent = node.get("agent")
        step_count = len(node.get("steps", []))

        out_nodes.append(
            {
                "id": nid,
                "type": ntype,
                "data": {
                    "label": label,
                    "description": description,
                    "nodeType": ntype,
                    "agent": agent,
                    "color": NODE_COLORS.get(ntype, "#9CA3AF"),
                    "isStart": nid == start_node,
                    "stepCount": step_count,
                },
                "position": {
                    "x": (idx % cols) * col_width,
                    "y": (idx // cols) * row_height,
                },
            }
        )

    # ── Produce edges ───────────────────────────────────────────────────
    for nid in bfs_order:
        node = raw_nodes[nid]
        ntype = node.get("type", "sequence")

        # Standard next_node
        next_node = node.get("next_node")
        if next_node:
            _add_edge(nid, next_node)

        # Logic node — conditional edges
        if ntype == "logic":
            for rule in node.get("rules", []):
                rn = rule.get("next_node")
                cond = rule.get("condition", rule.get("condition_expression", ""))
                _add_edge(nid, rn, label=str(cond)[:40], animated=True)
            dn = node.get("default_next_node")
            _add_edge(nid, dn, label="default", animated=True)

        # Human approval — approve / reject / timeout edges
        elif ntype == "human_approval":
            _add_edge(nid, node.get("on_approve"), label="approve", animated=True)
            _add_edge(nid, node.get("on_reject"), label="reject", animated=True)
            _add_edge(nid, node.get("on_timeout"), label="timeout", animated=True)

        # Loop — body and exit edges
        elif ntype == "loop":
            _add_edge(nid, node.get("body_node"), label="loop body", animated=True)
            # next_node already handled above as exit edge

        # Parallel — branch edges
        elif ntype == "parallel":
            for branch in node.get("branches", []):
                bid = branch.get("branch_id", "")
                sn = branch.get("start_node")
                _add_edge(nid, sn, label=f"branch:{bid}" if bid else "", animated=True)

    # Mark end nodes (no outgoing edges except the start node)
    edge_sources = {e["source"] for e in out_edges}
    for n in out_nodes:
        is_start = n["data"].get("isStart", False)
        n["data"]["isEnd"] = n["id"] not in edge_sources and not is_start

    return {"nodes": out_nodes, "edges": out_edges}
