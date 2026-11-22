"""Renders Mermaid *flowcharts* to ReportLab drawings for PDF export (no browser/Node needed).

Supported: `mindmap` and `timeline` (converted to flowcharts) and `flowchart`/`graph` with TD/TB/LR/BT/RL, node shapes [], (), {}, (()), ([]),
[[]], {{}}, quoted labels, edges -->, ---, -.->, ==>, with |labels| or -- label -->,
and chains (A --> B --> C). Other diagram types return None and the exporter
falls back to printing the Mermaid source.
"""
from __future__ import annotations

import re
import textwrap
from collections import defaultdict

NODE_RE = re.compile(r'^\s*([A-Za-z0-9_\-]+)\s*(\(\(|\(\[|\[\[|\[\(|\{\{|\[|\(|\{|>)?\s*(.*?)\s*(\)\)|\]\)|\]\]|\)\]|\}\}|\]|\)|\})?\s*$')
EDGE_SPLIT = re.compile(r'\s*(?:--\s*([^->|]+?)\s*-->|-->\s*\|([^|]*)\||-\.->\s*\|([^|]*)\||==>\s*\|([^|]*)\||-->|-\.->|==>|---|-\.-)\s*')


def _parse_node(token: str, labels: dict[str, str]) -> list[str]:
    ids = []
    for part in token.split("&"):
        part = part.strip()
        if not part:
            continue
        m = NODE_RE.match(part)
        if not m:
            continue
        node_id, _, label, _ = m.groups()
        label = (label or "").strip().strip('"')
        if label:
            labels[node_id] = label
        labels.setdefault(node_id, node_id)
        ids.append(node_id)
    return ids


SHAPE_STRIP = re.compile(r"^[A-Za-z0-9_\-]*\s*(?:\(\(|\(\[|\[\[|\{\{|\[|\(|\{|\)\))?(.*?)(?:\)\)|\]\)|\]\]|\}\}|\]|\)|\})?$")


def _clean_label(text: str) -> str:
    text = text.strip()
    m = SHAPE_STRIP.match(text)
    label = (m.group(1) if m and m.group(1) else text).strip().strip('"')
    return label.replace('"', "'")


def mindmap_to_flowchart(code: str) -> str | None:
    """Convert an indentation-based Mermaid mindmap into an LR flowchart tree."""
    lines = [ln for ln in code.splitlines()[1:] if ln.strip() and not ln.strip().startswith(("%%", "::icon"))]
    if not lines:
        return None
    stack: list[tuple[int, str]] = []
    out = ["flowchart LR"]
    for i, ln in enumerate(lines):
        indent = len(ln) - len(ln.lstrip())
        node = f"n{i}"
        out.append(f'    {node}["{_clean_label(ln)}"]')
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if stack:
            out.append(f"    {stack[-1][1]} --> {node}")
        stack.append((indent, node))
    return "\n".join(out)


def timeline_to_flowchart(code: str) -> str | None:
    """Convert a Mermaid timeline into a left-to-right chain of 'period: event' boxes."""
    events = []
    for ln in code.splitlines()[1:]:
        ln = ln.strip()
        if not ln or ln.startswith(("title", "section", "%%")):
            continue
        if ":" in ln:
            period, _, event = ln.partition(":")
            events.append(f"{period.strip()}: {event.strip().replace(':', ' /')}")
        elif events:
            events[-1] += " / " + ln
    if not events:
        return None
    out = ["flowchart LR"] + [f'    t{i}["{e.replace(chr(34), chr(39))}"]' for i, e in enumerate(events)]
    out += [f"    t{i} --> t{i + 1}" for i in range(len(events) - 1)]
    return "\n".join(out)


def to_flowchart(code: str) -> str | None:
    first = code.strip().split("\n", 1)[0].strip()
    if first.startswith(("flowchart", "graph")):
        return code
    if first.startswith("mindmap"):
        return mindmap_to_flowchart(code)
    if first.startswith("timeline"):
        return timeline_to_flowchart(code)
    return None


def parse_flowchart(code: str):
    lines = [ln.strip() for ln in code.strip().splitlines() if ln.strip() and not ln.strip().startswith("%%")]
    if not lines:
        return None
    header = lines[0].split()
    if header[0] not in ("flowchart", "graph"):
        return None
    direction = header[1].upper() if len(header) > 1 else "TD"
    labels: dict[str, str] = {}
    edges: list[tuple[str, str, str]] = []
    order: list[str] = []
    for line in lines[1:]:
        if line.startswith(("subgraph", "end", "classDef", "class ", "style ", "linkStyle", "click ")):
            continue
        line = line.rstrip(";")
        pieces = EDGE_SPLIT.split(line)
        # EDGE_SPLIT returns [node, g1, g2, g3, g4, node, ...]
        nodes_tokens = pieces[0::5]
        label_groups = [pieces[i:i + 4] for i in range(1, len(pieces), 5)]
        prev: list[str] = []
        for idx, tok in enumerate(nodes_tokens):
            ids = _parse_node(tok, labels)
            for n in ids:
                if n not in order:
                    order.append(n)
            if prev and ids and idx - 1 < len(label_groups):
                lbl = next((g for g in label_groups[idx - 1] if g), "") or ""
                for a in prev:
                    for b in ids:
                        edges.append((a, b, lbl.strip().strip('"')))
            prev = ids or prev
    if not order:
        return None
    return direction, order, labels, edges


def _layers(order, edges):
    """Longest-path layering after removing back edges (found by DFS in declaration order)."""
    children = defaultdict(list)
    for a, b, _ in edges:
        if b not in children[a]:
            children[a].append(b)
    state, back = {}, set()

    def dfs(n):
        state[n] = 1
        for c in children[n]:
            if state.get(c) == 1:
                back.add((n, c))
            elif c not in state:
                dfs(c)
        state[n] = 2

    for n in order:
        if n not in state:
            dfs(n)
    dag = defaultdict(list)
    indeg = {n: 0 for n in order}
    for a in order:
        for b in children[a]:
            if (a, b) not in back:
                dag[a].append(b)
                indeg[b] += 1
    level = {n: 0 for n in order}
    queue = [n for n in order if indeg[n] == 0]
    while queue:
        n = queue.pop(0)
        for c in dag[n]:
            level[c] = max(level[c], level[n] + 1)
            indeg[c] -= 1
            if indeg[c] == 0:
                queue.append(c)
    layers = defaultdict(list)
    for n in order:
        layers[level[n]].append(n)
    return [layers[i] for i in sorted(layers)]


def flowchart_drawing(code: str, max_width: float = 460, max_height: float = 560):
    """Return a reportlab Drawing for a Mermaid flowchart, or None if unsupported."""
    converted = to_flowchart(code)
    parsed = parse_flowchart(converted) if converted else None
    if parsed is None:
        return None
    from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
    from reportlab.lib import colors

    direction, order, labels, edges = parsed
    layers = _layers(order, edges)
    horizontal = direction in ("LR", "RL")
    box_w, box_h, gap_main, gap_cross = 120, 40, 46, 18
    wrap = 20

    pos = {}
    n_layers = len(layers)
    widest = max(len(l) for l in layers)
    if horizontal:
        width = n_layers * box_w + (n_layers - 1) * gap_main
        height = widest * box_h + (widest - 1) * gap_cross
    else:
        width = widest * box_w + (widest - 1) * gap_cross
        height = n_layers * box_h + (n_layers - 1) * gap_main
    for li, layer in enumerate(layers):
        span = len(layer) * (box_h if horizontal else box_w) + (len(layer) - 1) * gap_cross
        offset = ((height if horizontal else width) - span) / 2
        for ni, node in enumerate(layer):
            cross = offset + ni * ((box_h if horizontal else box_w) + gap_cross)
            main = li * ((box_w if horizontal else box_h) + gap_main)
            if horizontal:
                x, y = main, height - cross - box_h
                if direction == "RL":
                    x = width - main - box_w
            else:
                x, y = cross, height - main - box_h
                if direction == "BT":
                    y = main
            pos[node] = (x, y)

    scale = min(1.0, max_width / max(width, 1), max_height / max(height, 1))
    d = Drawing(width * scale, height * scale)

    def S(v):
        return v * scale

    font_size = max(5.5, 8 * scale)
    for a, b, lbl in edges:
        if a not in pos or b not in pos:
            continue
        ax, ay = pos[a]
        bx, by = pos[b]
        if horizontal:
            x1, y1 = (ax + box_w, ay + box_h / 2) if bx >= ax else (ax, ay + box_h / 2)
            x2, y2 = (bx, by + box_h / 2) if bx >= ax else (bx + box_w, by + box_h / 2)
        else:
            x1, y1 = (ax + box_w / 2, ay) if by <= ay else (ax + box_w / 2, ay + box_h)
            x2, y2 = (bx + box_w / 2, by + box_h) if by <= ay else (bx + box_w / 2, by)
        d.add(Line(S(x1), S(y1), S(x2), S(y2), strokeColor=colors.HexColor("#52606D"), strokeWidth=0.8))
        # arrow head
        import math
        ang = math.atan2(y2 - y1, x2 - x1)
        size = 6
        p1 = (x2 - size * math.cos(ang - 0.4), y2 - size * math.sin(ang - 0.4))
        p2 = (x2 - size * math.cos(ang + 0.4), y2 - size * math.sin(ang + 0.4))
        d.add(Polygon([S(x2), S(y2), S(p1[0]), S(p1[1]), S(p2[0]), S(p2[1])], fillColor=colors.HexColor("#52606D"), strokeWidth=0))
        if lbl:
            d.add(String(S(x1 + (x2 - x1) * 0.3 + 3), S(y1 + (y2 - y1) * 0.3 + 3), lbl[:28], fontSize=font_size * 0.9,
                         fillColor=colors.HexColor("#8A5A00"), fontName="Helvetica-Oblique"))
    for node, (x, y) in pos.items():
        d.add(Rect(S(x), S(y), S(box_w), S(box_h), rx=S(6), ry=S(6), fillColor=colors.HexColor("#EEF3F8"),
                   strokeColor=colors.HexColor("#2F5D8A"), strokeWidth=0.8))
        lines = textwrap.wrap(labels.get(node, node), wrap)[:3] or [node]
        total = len(lines) * font_size * 1.15
        for i, text in enumerate(lines):
            ty = y + box_h / 2 + total / 2 / scale - (i + 1) * font_size * 1.15 / scale + 2
            d.add(String(S(x + box_w / 2), S(ty), text, fontSize=font_size, textAnchor="middle", fontName="Helvetica",
                         fillColor=colors.HexColor("#1F2933")))
    return d
