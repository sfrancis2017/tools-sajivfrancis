"""Mermaid → draw.io (diagrams.net) converter.

Turns a Mermaid diagram into an editable .drawio file (mxGraph XML) so a rendered
map stops being a static image and becomes editable shapes. Deterministic, no
LLM, no side effects — safe to expose publicly.

Supported: `flowchart`/`graph` (TD/TB/BT/LR/RL) and `mindmap`. Other diagram types
(sequence, class, gantt, …) return 422 — they keep the existing SVG/copy paths.
Subgraph grouping is flattened in v1 (all nodes/edges convert; the visual group
box is dropped). Chained edges (`A --> B --> C`) and labeled edges are handled.
"""
from __future__ import annotations

import html
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

# ── node shape detection ──────────────────────────────────────────────────────
# (open, close, drawio style) — ORDER MATTERS: longest/most-specific first.
_SHAPES = [
    ("((", "))", "ellipse;whiteSpace=wrap;html=1;"),
    ("([", "])", "rounded=1;arcSize=40;whiteSpace=wrap;html=1;"),  # stadium
    ("[(", ")]", "shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;"),  # db
    ("{{", "}}", "shape=hexagon;whiteSpace=wrap;html=1;"),
    ("[[", "]]", "shape=process;whiteSpace=wrap;html=1;"),
    ("{", "}", "rhombus;whiteSpace=wrap;html=1;"),
    ("([", "])", "rounded=1;arcSize=40;whiteSpace=wrap;html=1;"),
    ("(", ")", "rounded=1;whiteSpace=wrap;html=1;"),
    ("[", "]", "rounded=0;whiteSpace=wrap;html=1;"),
]
_DEFAULT_STYLE = "rounded=0;whiteSpace=wrap;html=1;"
_EDGE_STYLE = "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;"

# edge operators (longest first so -.-> beats --)
_EDGE_OP = re.compile(r"\s*(-{2,3}>|-\.->|-\.-|={2,3}>|={2,3}|--[ox]|--)\s*(\|[^|]*\|)?\s*")
_ID = re.compile(r"^([A-Za-z0-9_]+)\s*(.*)$")
_SKIP = re.compile(r"^\s*(linkStyle\b|direction\b|%%)", re.I)


def _mm_props_to_drawio(props: str) -> str:
    """Translate Mermaid style props (fill:#x,stroke:#y,color:#z,stroke-width:2px)
    into draw.io style fragments (fillColor=#x;strokeColor=#y;...)."""
    out = []
    for part in props.split(","):
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        k, v = k.strip().lower(), v.strip()
        if k == "fill":
            out.append(f"fillColor={v};")
        elif k == "stroke":
            out.append(f"strokeColor={v};")
        elif k == "color":
            out.append(f"fontColor={v};")
        elif k == "stroke-width":
            out.append(f"strokeWidth={v.replace('px', '').strip()};")
        elif k == "stroke-dasharray":
            out.append("dashed=1;")
    return "".join(out)


def _clean_label(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]:
        s = s[1:-1]
    return s.strip()


def _parse_node(text: str, nodes: dict, node_class: dict | None = None) -> str | None:
    """Parse 'A[Label]' / 'A((x))' / 'A[Label]:::cls' / bare 'A'. Register in nodes,
    record any inline ::: class, return id."""
    text = text.strip()
    if not text:
        return None
    cm = re.search(r":::([A-Za-z0-9_]+)\s*$", text)  # inline class: A[..]:::name
    cls = None
    if cm:
        cls = cm.group(1)
        text = text[: cm.start()].strip()
    m = _ID.match(text)
    if not m:
        return None
    nid, rest = m.group(1), m.group(2).strip()
    label, style = nid, _DEFAULT_STYLE
    if rest:
        for op, cl, st in _SHAPES:
            if rest.startswith(op) and rest.endswith(cl) and len(rest) >= len(op) + len(cl):
                label = _clean_label(rest[len(op):-len(cl)])
                style = st
                break
    # last definition wins, but never downgrade a real label back to the bare id
    if nid not in nodes or label != nid:
        nodes[nid] = (label or nid, style)
    if cls and node_class is not None:
        node_class[nid] = cls
    return nid


def _parse_flowchart(lines: list[str], direction: str):
    nodes: dict[str, tuple[str, str]] = {}
    edges: list[tuple[str, str, str]] = []
    node_class: dict[str, str] = {}       # node id -> classDef name (class / :::)
    classdefs: dict[str, str] = {}        # classDef name -> Mermaid props
    node_style: dict[str, str] = {}       # node id -> inline `style` props
    subgraphs: dict[str, dict] = {}       # sid -> {"title", "parent"}
    node_group: dict[str, str] = {}       # node id -> innermost subgraph id
    group_order: list[str] = []
    stack: list[str] = []                 # open subgraph ids
    sg_n = 0
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        sm = re.match(r"^subgraph\b\s*(.*)$", line, re.I)
        if sm:
            spec = sm.group(1).strip()
            bm = re.match(r"^([A-Za-z0-9_]+)\s*\[(.+)\]$", spec)
            if bm:
                sid, title = bm.group(1), _clean_label(bm.group(2))
            elif spec.startswith('"') and spec.endswith('"') and len(spec) >= 2:
                sg_n += 1
                sid, title = f"sg{sg_n}", _clean_label(spec)
            elif spec:
                sid, title = re.sub(r"[^A-Za-z0-9_]", "_", spec), spec
            else:
                sg_n += 1
                sid, title = f"sg{sg_n}", ""
            if sid in subgraphs:
                sg_n += 1
                sid = f"{sid}_{sg_n}"
            subgraphs[sid] = {"title": title, "parent": stack[-1] if stack else None}
            group_order.append(sid)
            stack.append(sid)
            continue
        if re.match(r"^end\b", line, re.I):
            if stack:
                stack.pop()
            continue
        if _SKIP.match(line):
            continue
        m = re.match(r"^classDef\s+([A-Za-z0-9_]+)\s+(.+?);?$", line, re.I)
        if m:
            classdefs[m.group(1)] = m.group(2)
            continue
        m = re.match(r"^class\s+([\w, ]+?)\s+([A-Za-z0-9_]+);?$", line, re.I)
        if m:
            for nid in re.split(r"[,\s]+", m.group(1).strip()):
                if nid:
                    node_class[nid] = m.group(2)
            continue
        m = re.match(r"^style\s+([A-Za-z0-9_]+)\s+(.+?);?$", line, re.I)
        if m:
            node_style[m.group(1)] = m.group(2)
            continue
        # split into node-chunks separated by edge ops, capturing each op's label
        chunks, ops, idx = [], [], 0
        for m in _EDGE_OP.finditer(line):
            chunks.append(line[idx:m.start()])
            ops.append((m.group(2) or "").strip("|"))
            idx = m.end()
        chunks.append(line[idx:])
        ids = [_parse_node(c, nodes, node_class) for c in chunks]
        for nid in ids:
            if nid and stack and nid not in node_group:
                node_group[nid] = stack[-1]
        if len(ids) >= 2:
            for i, lbl in enumerate(ops):
                a, b = ids[i], ids[i + 1]
                if a and b:
                    edges.append((a, b, lbl.strip()))
    # fold Mermaid colors (classDef + class/::: + style) into each node's style
    for nid, (label, style) in list(nodes.items()):
        extra = ""
        cls = node_class.get(nid)
        if cls and cls in classdefs:
            extra += _mm_props_to_drawio(classdefs[cls])
        if nid in node_style:
            extra += _mm_props_to_drawio(node_style[nid])
        if extra:
            nodes[nid] = (label, style + extra)

    # lane = top-level ancestor subgraph of each grouped node
    def _top(sid):
        seen = set()
        while sid and subgraphs.get(sid, {}).get("parent") and sid not in seen:
            seen.add(sid)
            sid = subgraphs[sid]["parent"]
        return sid

    lane_of = {n: _top(g) for n, g in node_group.items()}
    lanes = [s for s in group_order
             if subgraphs[s]["parent"] is None and any(v == s for v in lane_of.values())]
    if lanes:
        pos, containers, node_parent = _layout_grouped(
            nodes, edges, direction, lane_of, lanes, subgraphs)
        return nodes, edges, pos, containers, node_parent
    _, _, pos = _layout(nodes, edges, direction)
    return nodes, edges, pos, [], {}


def _layout(nodes, edges, direction):
    """Layered (Sugiyama-style) layout that approximates Mermaid/dagre: longest-path
    layers, a few barycenter ordering passes so children sit under their parents and
    edge crossings drop, then each layer centered on a common axis."""
    horizontal = direction in ("LR", "RL")
    # 1. layers via longest path (cycle-bounded by iteration count)
    layer = {n: 0 for n in nodes}
    for _ in range(len(nodes)):
        changed = False
        for a, b, _l in edges:
            if a in layer and b in layer and layer[b] < layer[a] + 1:
                layer[b] = layer[a] + 1
                changed = True
        if not changed:
            break
    # 2. adjacency
    preds: dict[str, list[str]] = {n: [] for n in nodes}
    succs: dict[str, list[str]] = {n: [] for n in nodes}
    for a, b, _l in edges:
        if a in nodes and b in nodes:
            succs[a].append(b)
            preds[b].append(a)
    # 3. group by layer (first-appearance order seeds the ordering)
    order: dict[int, list[str]] = {}
    for n in nodes:
        order.setdefault(layer.get(n, 0), []).append(n)
    maxlv = max(order) if order else 0

    def _bary(ids, ref_index, neighbors):
        cur = {n: i for i, n in enumerate(ids)}
        def key(n):
            vals = [ref_index[x] for x in neighbors[n] if x in ref_index]
            return sum(vals) / len(vals) if vals else cur[n]  # keep stable if no link
        ids.sort(key=key)

    # 4. alternate down/up barycenter passes
    for _ in range(4):
        for lv in range(1, maxlv + 1):
            _bary(order[lv], {n: i for i, n in enumerate(order.get(lv - 1, []))}, preds)
        for lv in range(maxlv - 1, -1, -1):
            _bary(order[lv], {n: i for i, n in enumerate(order.get(lv + 1, []))}, succs)

    # 5. positions — center each layer on the widest layer's axis
    GAP_MAIN, GAP_CROSS = 150, 200
    widest = max((len(ids) for ids in order.values()), default=1)
    pos = {}
    for lv, ids in order.items():
        offset = (widest - len(ids)) * GAP_CROSS / 2.0
        for i, n in enumerate(ids):
            cross = 40 + offset + i * GAP_CROSS
            main = 40 + lv * GAP_MAIN
            pos[n] = (main, cross) if horizontal else (cross, main)
    return nodes, edges, pos


def _layout_grouped(nodes, edges, direction, lane_of, lanes, subgraphs):
    """Lane layout: each top-level subgraph becomes a contiguous lane (so the
    container boxes don't overlap), ungrouped nodes trail in a free lane. Returns
    (pos, containers, node_parent). Layers (the flow axis) are shared across lanes
    so the flow lines up; lanes are offset along the cross axis."""
    horizontal = direction in ("LR", "RL")
    layer = {n: 0 for n in nodes}
    for _ in range(len(nodes)):
        changed = False
        for a, b, _l in edges:
            if a in layer and b in layer and layer[b] < layer[a] + 1:
                layer[b] = layer[a] + 1
                changed = True
        if not changed:
            break
    FREE = "__free__"
    lane_nodes = {ln: [] for ln in lanes + [FREE]}
    for n in nodes:
        lane_nodes.setdefault(lane_of.get(n, FREE), []).append(n)
    GAP_MAIN, GAP_CROSS, LANE_GAP, PAD, TITLE, NW, NH = 150, 200, 70, 26, 32, 160, 50
    pos, containers, node_parent = {}, [], {}
    cross_cursor = 40
    for ln in lanes + [FREE]:
        members = lane_nodes.get(ln) or []
        if not members:
            continue
        by_layer: dict[int, list[str]] = {}
        for n in members:
            by_layer.setdefault(layer.get(n, 0), []).append(n)
        lane_cols = max((len(v) for v in by_layer.values()), default=1)
        for lv, ns in by_layer.items():
            for i, n in enumerate(ns):
                cross = cross_cursor + i * GAP_CROSS
                main = 40 + lv * GAP_MAIN
                pos[n] = (main, cross) if horizontal else (cross, main)
        if ln != FREE:
            xs = [pos[n][0] for n in members]
            ys = [pos[n][1] for n in members]
            x0, y0 = min(xs) - PAD, min(ys) - PAD - TITLE
            x1, y1 = max(xs) + NW + PAD, max(ys) + NH + PAD
            containers.append({"id": f"c_{ln}", "title": subgraphs[ln]["title"] or ln,
                               "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0})
            for n in members:
                node_parent[n] = f"c_{ln}"
        cross_cursor += lane_cols * GAP_CROSS + LANE_GAP
    return pos, containers, node_parent


def _parse_mindmap(lines: list[str]):
    nodes: dict[str, tuple[str, str]] = {}
    edges: list[tuple[str, str, str]] = []
    pos = {}
    stack: list[tuple[int, str]] = []  # (depth, id)
    counter = 0
    for raw in lines:
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        depth = indent // 2
        text = raw.strip()
        # root((Label)) / (Label) / [Label] / bare
        mm = re.match(r"^[A-Za-z0-9_]*\(\((.+)\)\)$", text) or re.match(r"^[A-Za-z0-9_]*\((.+)\)$", text)
        if mm:
            label = mm.group(1)
        else:
            label = re.sub(r"^[A-Za-z0-9_]*[\[\(](.+?)[\]\)]$", r"\1", text)
        label = _clean_label(label)
        nid = f"m{counter}"
        nodes[nid] = (label, "rounded=1;whiteSpace=wrap;html=1;")
        pos[nid] = (40 + depth * 210, 40 + counter * 56)
        while stack and stack[-1][0] >= depth:
            stack.pop()
        if stack:
            edges.append((stack[-1][1], nid, ""))
        stack.append((depth, nid))
        counter += 1
    return nodes, edges, pos


def _to_mxfile(nodes, edges, pos, containers=None, node_parent=None) -> str:
    containers = containers or []
    node_parent = node_parent or {}
    cbyid = {c["id"]: c for c in containers}
    cells = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']
    # lane containers first (so child cells can reference them as parent)
    _CSTYLE = ("rounded=0;whiteSpace=wrap;html=1;fillColor=none;strokeColor=#9e9e9e;"
               "verticalAlign=top;fontStyle=1;container=1;collapsible=0;dashed=1;")
    for c in containers:
        cells.append(
            f'<mxCell id="{c["id"]}" value="{html.escape(c["title"], quote=True)}" '
            f'style="{_CSTYLE}" vertex="1" parent="1">'
            f'<mxGeometry x="{c["x"]:.0f}" y="{c["y"]:.0f}" '
            f'width="{c["w"]:.0f}" height="{c["h"]:.0f}" as="geometry"/></mxCell>'
        )
    for nid, (label, style) in nodes.items():
        x, y = pos.get(nid, (40, 40))
        w, h = (80, 80) if "ellipse" in style else (160, 50)
        parent = node_parent.get(nid)
        if parent in cbyid:  # geometry is relative to the container origin
            gx, gy, pref = x - cbyid[parent]["x"], y - cbyid[parent]["y"], parent
        else:
            gx, gy, pref = x, y, "1"
        cells.append(
            f'<mxCell id="n_{nid}" value="{html.escape(label, quote=True)}" '
            f'style="{style}" vertex="1" parent="{pref}">'
            f'<mxGeometry x="{gx:.0f}" y="{gy:.0f}" width="{w}" height="{h}" as="geometry"/></mxCell>'
        )
    for i, (a, b, lbl) in enumerate(edges):
        cells.append(
            f'<mxCell id="e{i}" value="{html.escape(lbl, quote=True)}" '
            f'style="{_EDGE_STYLE}" edge="1" parent="1" source="n_{a}" target="n_{b}">'
            f'<mxGeometry relative="1" as="geometry"/></mxCell>'
        )
    body = "".join(cells)
    return (
        '<mxfile host="app.diagrams.net">'
        '<diagram name="Diagram" id="d1">'
        '<mxGraphModel dx="900" dy="650" grid="1" gridSize="10" guides="1" '
        'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
        'pageWidth="850" pageHeight="1100" math="0" shadow="0">'
        f"<root>{body}</root>"
        "</mxGraphModel></diagram></mxfile>"
    )


def mermaid_to_drawio(src: str) -> str:
    """Convert Mermaid source to a .drawio (mxGraph XML) string. Raises ValueError
    for unsupported diagram types or empty input."""
    lines = src.strip().splitlines()
    if not lines:
        raise ValueError("empty diagram")
    head = lines[0].strip().lower()
    containers, node_parent = [], {}
    if head.startswith("mindmap"):
        nodes, edges, pos = _parse_mindmap(lines[1:])
    elif head.startswith(("flowchart", "graph")):
        m = re.search(r"\b(TD|TB|BT|LR|RL)\b", lines[0], re.I)
        nodes, edges, pos, containers, node_parent = _parse_flowchart(
            lines[1:], (m.group(1).upper() if m else "TD"))
    else:
        kind = head.split()[0] if head else "unknown"
        raise ValueError(f"draw.io export supports flowchart/graph and mindmap; got '{kind}'")
    if not nodes:
        raise ValueError("no nodes found to convert")
    return _to_mxfile(nodes, edges, pos, containers, node_parent)


class ConvertRequest(BaseModel):
    mermaid: str
    filename: str = "diagram"


@router.post("/drawio")
def to_drawio(req: ConvertRequest):
    try:
        xml = mermaid_to_drawio(req.mermaid)
    except ValueError as e:
        raise HTTPException(422, str(e))
    slug = re.sub(r"[^a-z0-9-]+", "-", req.filename.lower()).strip("-") or "diagram"
    return {"filename": f"{slug}.drawio", "drawio": xml}
