"""
reports/charts.py — graph/network helpers and PDF chart builders.

Two related things live here together because they share data (same
nodes/edges shape, same node-type color map, same truncate/safe-num
helpers) even though they render to different targets:

  1. Graph helpers used by BOTH the static PDF diagram and the live,
     interactive (pan/zoom/drag) HTML graph shown in the app:
       _kg_nodes_edges, _criminal_network_nodes_edges,
       _build_interactive_network_html, _VIS_NETWORK_HEAD,
       _VIS_NETWORK_INIT_JS

  2. Pure PDF chart builders (all reportlab `Drawing`/`Table` objects,
     no side effects, no DB/network access) consumed by export_report_pdf:
       _pdf_network_diagram, _pdf_crime_dna_radar,
       _pdf_evidence_provided_chart, _pdf_fraud_indicators_chart,
       _pdf_hypothesis_confidence_chart, _pdf_risk_signals_chart,
       _pdf_evidence_coverage_chart, _pdf_progress_bar

Plus two small shared utilities: _pdf_truncate_label, _safe_num.

Extracted from gradio_app.py (was ~510 lines inline, between the
vehicle-evidence analyzer and _hypothesis_display_status).
"""

_PDF_NODE_TYPE_COLORS = {
    "person": "#0f172a", "face": "#7c3aed", "vehicle": "#ea580c",
    "phone": "#0891b2", "wallet": "#ca8a04", "bank": "#16a34a",
    "financial": "#16a34a", "location": "#dc2626", "company": "#4338ca",
    "weapon": "#991b1b", "email": "#0e7490", "digital": "#0e7490",
    "default": "#64748b",
}


def _pdf_truncate_label(text, max_len=20):
    """Truncates at a word boundary instead of mid-word (e.g. 'Weapon/Tool:
    tor' -> 'Weapon/Tool: torch' when it fits, else a clean '...')."""
    text = str(text)
    if len(text) <= max_len:
        return text
    cut = text[:max_len].rsplit(" ", 1)[0]
    return (cut or text[:max_len]) + "…"


def _kg_nodes_edges(kg_raw):
    """Extracts (nodes, edges) in the common {'id','type','label'} /
    {'from','to','label','confidence_type'} shape from a raw
    knowledge_graph_raw dict — shared by both the static PDF diagram and
    the interactive browser graph so they're always built from identical
    data. confidence_type (OBSERVED/EXTRACTED/INFERRED/UNVERIFIED, from
    KnowledgeGraphEngine's own edge-confidence classification) is carried
    through so the diagram can visually distinguish an evidence-backed
    relationship from an AI-inferred one, rather than drawing every edge
    identically regardless of how well-founded it actually is."""
    nodes = [{"id": n.get("id"), "type": n.get("type"), "label": n.get("name", n.get("type", "?"))}
             for n in (kg_raw.get("nodes") or []) if n.get("id")]
    edges = [{"from": e.get("source"), "to": e.get("target"), "label": e.get("relationship"),
              "confidence_type": e.get("confidence_type", "INFERRED")}
              for e in (kg_raw.get("edges") or [])]
    return nodes, edges


def _criminal_network_nodes_edges(cn):
    """Extracts (nodes, edges) for the criminal network — known nodes plus
    inferred nodes, all radiating from the root person node — shared by
    both the static PDF diagram and the interactive browser graph."""
    nodes, edges = [], []
    root_id = None
    for i, n in enumerate(cn.get("current_nodes", []) or []):
        nid = f"known{i}"
        nodes.append({"id": nid, "type": n.get("type", "default"),
                       "label": n.get("name", n.get("type", "?"))})
        if str(n.get("type", "")).lower() == "person" or root_id is None:
            root_id = root_id or nid
    for i, n in enumerate(cn.get("inferred_nodes", []) or []):
        nid = f"inferred{i}"
        nodes.append({"id": nid, "type": n.get("type", "default"),
                       "label": n.get("name", n.get("type", "?")) + "*"})
    if root_id:
        for n in nodes:
            if n["id"] != root_id:
                edges.append({"from": root_id, "to": n["id"], "label": ""})
    return nodes, edges


_VIS_NETWORK_HEAD = (
    '<script src="https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.2/'
    'standalone/umd/vis-network.min.js"></script>'
)

# Runs client-side after any event that updates a .vis-graph-container's
# HTML value (chained via `.then(fn=None, js=_VIS_NETWORK_INIT_JS)` on every
# click handler that can change these components) — gr.HTML's js_on_load
# only fires once at initial component mount, not on later value updates,
# so re-initializing the graph after fresh analysis data arrives has to
# happen this way instead.
_VIS_NETWORK_INIT_JS = """
() => {
  if (typeof vis === 'undefined') return;
  document.querySelectorAll('.vis-graph-container').forEach(function(el) {
    var nodesData = el.getAttribute('data-nodes');
    var edgesData = el.getAttribute('data-edges');
    var signature = (nodesData || '') + '|' + (edgesData || '');
    if (!nodesData || el.getAttribute('data-rendered-sig') === signature) return;
    try {
      var nodes = new vis.DataSet(JSON.parse(nodesData));
      var edges = new vis.DataSet(JSON.parse(edgesData || '[]'));
      el.innerHTML = '';
      var options = {
        physics: { stabilization: true, barnesHut: { gravitationalConstant: -4000, springLength: 130 } },
        interaction: { hover: true, tooltipDelay: 100, zoomView: true, dragView: true },
        nodes: { font: { color: '#e2e8f0', size: 13 }, borderWidth: 2 },
        edges: { font: { color: '#94a3b8', size: 10, strokeWidth: 0, align: 'middle' },
                 smooth: { type: 'continuous' }, arrows: { to: { enabled: true, scaleFactor: 0.5 } } }
      };
      new vis.Network(el, { nodes: nodes, edges: edges }, options);
      el.setAttribute('data-rendered-sig', signature);
    } catch (e) { console.error('vis-network render failed', e); }
  });
}
"""


def _build_interactive_network_html(nodes, edges, height=440, empty_label="No graph data available."):
    """Builds the HTML payload for an interactive (pan/zoom/drag/click)
    vis-network.js graph — this is what makes the graph feel like a real
    investigation tool rather than a static picture. The actual vis.Network
    object is constructed client-side by _VIS_NETWORK_INIT_JS, which must
    be chained via .then(fn=None, js=_VIS_NETWORK_INIT_JS) on whichever
    event updates this component, since gr.HTML doesn't execute <script>
    tags and js_on_load only fires once at mount."""
    import json as _json
    import html as _html_mod

    if not nodes:
        return (f"<div style='background:#0d1117;border:1px solid #1a2236;border-radius:10px;"
                f"padding:24px;text-align:center;color:#64748b;font-size:13px;'>{empty_label}</div>")

    vis_nodes = [{
        "id": n["id"],
        "label": str(n.get("label", n["id"]))[:36],
        "title": _html_mod.escape(str(n.get("label", n["id"]))),
        "color": {"background": _PDF_NODE_TYPE_COLORS.get(str(n.get("type", "")).lower(),
                                                            _PDF_NODE_TYPE_COLORS["default"]),
                   "border": "#ffffff"},
        "shape": "dot", "size": 20,
    } for n in nodes]
    vis_edges = [{
        "from": e.get("from"), "to": e.get("to"),
        "label": str(e.get("label") or "")[:22],
    } for e in edges if e.get("from") and e.get("to")]

    nodes_json = _html_mod.escape(_json.dumps(vis_nodes))
    edges_json = _html_mod.escape(_json.dumps(vis_edges))

    return (
        f"<div style='background:#0d1117;border:1px solid #1a2236;border-radius:10px;padding:8px;'>"
        f"<div class='vis-graph-container' data-nodes=\"{nodes_json}\" data-edges=\"{edges_json}\" "
        f"style='height:{height}px;width:100%;background:#0d1117;border-radius:8px;'></div>"
        f"<div style='color:#64748b;font-size:11px;padding:6px 10px;'>"
        f"Drag background to pan &nbsp;•&nbsp; Scroll to zoom &nbsp;•&nbsp; Drag a node to move it &nbsp;•&nbsp; "
        f"Hover a node for its full name</div></div>"
    )


def _pdf_network_diagram(nodes, edges, width=480, height=280):
    """Renders a node-link network diagram (reportlab Drawing) from a list
    of {'id', 'type', 'label'} nodes and {'from', 'to', 'label',
    'confidence_type'} edges, using a simple BFS layered-tree layout
    rooted at the highest-degree node. Returns None if there's nothing to
    draw.

    This exists because a text list of 'Face -> Person, Vehicle ->
    Location' relationships is data representation, not investigation
    visualization — an investigator can read an actual diagram in 2
    seconds instead of parsing a bullet list.

    Dark theme with a soft glow ring per node (a few concentric,
    increasingly transparent circles) and edges styled by their real
    confidence_type where available — OBSERVED/EXTRACTED (evidence-backed)
    drawn solid and bright, INFERRED/UNVERIFIED (AI-suggested, not
    evidence-traceable) drawn dashed and muted — so the reader can see at
    a glance which connections are established versus which are leads.
    Edges without a confidence_type (e.g. the criminal-network diagram,
    which doesn't carry this field) fall back to a neutral solid style.
    """
    from reportlab.graphics.shapes import Drawing, Circle, Line, String, Rect
    from reportlab.lib import colors as _colors
    from collections import defaultdict, deque

    if not nodes:
        return None

    node_by_id = {n['id']: n for n in nodes}
    adj = defaultdict(list)
    for e in edges:
        if e.get('from') in node_by_id and e.get('to') in node_by_id:
            adj[e['from']].append(e['to'])
            adj[e['to']].append(e['from'])

    degree = {n['id']: len(adj[n['id']]) for n in nodes}
    root = max(degree, key=degree.get) if degree else nodes[0]['id']

    levels = {root: 0}
    order = [root]
    q = deque([root])
    visited = {root}
    while q:
        cur = q.popleft()
        for nb in adj[cur]:
            if nb not in visited:
                visited.add(nb)
                levels[nb] = levels[cur] + 1
                order.append(nb)
                q.append(nb)
    leftover_level = (max(levels.values()) + 1) if levels else 0
    for n in nodes:
        if n['id'] not in levels:
            levels[n['id']] = leftover_level

    by_level = defaultdict(list)
    for nid, lvl in levels.items():
        by_level[lvl].append(nid)
    if not by_level:
        return None

    # Reserve a strip at the bottom for the confidence-type legend.
    legend_h = 20
    plot_h = height - legend_h

    max_level = max(by_level.keys())
    level_h = plot_h / (max_level + 1.5)
    d = Drawing(width, height)

    DARK_BG = _colors.HexColor("#0b1220")
    d.add(Rect(0, 0, width, height, fillColor=DARK_BG, strokeColor=None))

    pos = {}
    for lvl, ids in by_level.items():
        n = len(ids)
        for i, nid in enumerate(ids):
            x = width * (i + 1) / (n + 1)
            y = plot_h - level_h * (lvl + 0.7) + legend_h
            pos[nid] = (x, y)

    # Edge styling by real confidence_type. OBSERVED/EXTRACTED = this
    # relationship traces back to evidence this case actually has;
    # INFERRED/UNVERIFIED = an AI-suggested lead, not (yet) a verified fact.
    _EDGE_STYLE = {
        "OBSERVED":   {"color": "#22d3ee", "dash": None,      "width": 1.6},
        "EXTRACTED":  {"color": "#facc15", "dash": None,      "width": 1.3},
        "INFERRED":   {"color": "#94a3b8", "dash": (3, 2),    "width": 1.0},
        "UNVERIFIED": {"color": "#f87171", "dash": (2, 2),    "width": 1.0},
    }
    _DEFAULT_EDGE_STYLE = {"color": "#94a3b8", "dash": None, "width": 1.0}
    _seen_conf_types = set()

    for e in edges:
        if e.get('from') in pos and e.get('to') in pos:
            x1, y1 = pos[e['from']]
            x2, y2 = pos[e['to']]
            ctype = str(e.get('confidence_type') or "").upper()
            style = _EDGE_STYLE.get(ctype, _DEFAULT_EDGE_STYLE)
            if ctype in _EDGE_STYLE:
                _seen_conf_types.add(ctype)
            ln = Line(x1, y1, x2, y2, strokeColor=_colors.HexColor(style["color"]),
                      strokeWidth=style["width"])
            if style["dash"]:
                ln.strokeDashArray = style["dash"]
            d.add(ln)
            if e.get('label'):
                mx, my = (x1 + x2) / 2, (y1 + y2) / 2
                d.add(String(mx, my + 2, str(e['label'])[:14], fontSize=6.5,
                              fillColor=_colors.HexColor("#94a3b8"), textAnchor="middle"))

    def _lighten_if_too_dark(hex_color, min_luminance=110):
        """Some entries in the shared _PDF_NODE_TYPE_COLORS map (e.g.
        "person": "#0f172a") read fine on the OLD white PDF background and
        in the interactive HTML graph, but are nearly invisible against
        THIS diagram's new dark background. Lift just those specific
        colors' brightness for this rendering only — the shared dict
        itself, and every other consumer of it, is untouched."""
        rgb = _colors.HexColor(hex_color)
        r, g, b = rgb.red * 255, rgb.green * 255, rgb.blue * 255
        luminance = 0.299 * r + 0.587 * g + 0.114 * b
        if luminance >= min_luminance:
            return hex_color
        factor = min_luminance / max(luminance, 1)
        r, g, b = (min(255, int(c * factor)) for c in (r, g, b))
        return f"#{r:02x}{g:02x}{b:02x}"

    r = 14
    for nid, (x, y) in pos.items():
        node = node_by_id[nid]
        color_hex = _lighten_if_too_dark(_PDF_NODE_TYPE_COLORS.get(
            str(node.get('type', '')).lower(), _PDF_NODE_TYPE_COLORS["default"]))
        color = _colors.HexColor(color_hex)
        # Soft "glow": a few progressively larger, more transparent rings
        # behind the solid node circle — reportlab has no true blur/glow
        # filter, so this approximates one with plain alpha-blended shapes.
        for ring_r, ring_alpha in ((r + 9, 0.10), (r + 5, 0.18), (r + 2, 0.30)):
            d.add(Circle(x, y, ring_r, fillColor=color, strokeColor=None,
                          fillOpacity=ring_alpha))
        d.add(Circle(x, y, r, fillColor=color, strokeColor=_colors.HexColor("#e2e8f0"), strokeWidth=1.2))
        d.add(String(x, y - r - 10, _pdf_truncate_label(node.get('label', nid), 30), fontSize=7,
                      fillColor=_colors.HexColor("#e2e8f0"), textAnchor="middle"))
        d.add(String(x, y - 3, str(node.get('type', ''))[:10], fontSize=6,
                      fillColor=_colors.HexColor("#0b1220"), textAnchor="middle"))

    # Legend: only list confidence types actually present in this graph's
    # edges, so a graph with no INFERRED edges (say) doesn't show a
    # misleading "this graph has inferred links" key.
    if _seen_conf_types:
        lx = 8
        for ctype in ("OBSERVED", "EXTRACTED", "INFERRED", "UNVERIFIED"):
            if ctype not in _seen_conf_types:
                continue
            style = _EDGE_STYLE[ctype]
            ln = Line(lx, legend_h / 2, lx + 16, legend_h / 2,
                      strokeColor=_colors.HexColor(style["color"]), strokeWidth=style["width"])
            if style["dash"]:
                ln.strokeDashArray = style["dash"]
            d.add(ln)
            d.add(String(lx + 20, legend_h / 2 - 2.5, ctype.title(), fontSize=6.5,
                          fillColor=_colors.HexColor("#e2e8f0")))
            lx += 20 + len(ctype) * 4.2 + 14

    return d


def _pdf_crime_dna_radar(dna, width=280, height=230):
    """Renders Crime DNA as a radar/spider chart (7 dimensions at once) —
    industry-standard for this kind of multi-dimensional profile, and much
    faster to read than seven separate bars."""
    from reportlab.graphics.charts.spider import SpiderChart
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib import colors as _colors

    dims = ['Planning', 'Technical', 'Violence', 'Escape', 'Op.Security', 'Execution', 'Team']
    keys = ['planning', 'technical', 'violence', 'escape', 'op_security', 'execution', 'team']
    values = [dna.get(k, 0) for k in keys]
    if not any(isinstance(v, (int, float)) and v for v in values):
        return None
    # "Planning 8/10" beats "Planning" — readable without decoding the
    # chart geometry first.
    labels = [f"{name} {val}/10" for name, val in zip(dims, values)]

    d = Drawing(width, height)
    chart = SpiderChart()
    chart.x = 45
    chart.y = 35
    chart.width = width - 90
    chart.height = height - 70
    chart.data = [values]
    chart.labels = labels
    chart.strands[0].strokeColor = _colors.HexColor("#dc2626")
    chart.strands[0].fillColor = _colors.Color(0.86, 0.15, 0.15, alpha=0.25)
    chart.strands[0].strokeWidth = 1.5
    chart.spokes.strokeColor = _colors.HexColor("#cbd5e1")
    chart.spokeLabels.fontName = "Times-Roman"
    chart.spokeLabels.fontSize = 8
    chart.spokeLabels.fillColor = _colors.HexColor("#334155")
    d.add(chart)
    return d


def _safe_num(val, default=0):
    """Module-level safe numeric coercion for the chart helpers below —
    tolerates None/strings/'N/A' gracefully instead of raising."""
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _pdf_evidence_provided_chart(evidence_provided, width=340, height=150):
    """Bar chart showing which evidence TYPES were submitted for this case
    (1) vs not (0) — added per user request to explain more report facts
    via graphs. Evidence gaps are one of the most-repeated facts across
    every report reviewed so far; a chart makes the gap pattern instantly
    scannable instead of reading a list of Yes/No lines."""
    if not evidence_provided:
        return None
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.lib import colors as _colors

    labels = {"photo": "Photo", "voice": "Voice", "document": "Document",
              "network": "Network", "financial": "Financial", "vehicle": "Vehicle",
              "digital": "Digital", "cctv_video": "CCTV"}
    names = [labels.get(k, k.title()) for k in evidence_provided.keys()]
    values = [1 if v else 0 for v in evidence_provided.values()]

    d = Drawing(width, height)
    chart = VerticalBarChart()
    chart.x = 35
    chart.y = 35
    chart.width = width - 55
    chart.height = height - 60
    chart.data = [values]
    chart.categoryAxis.categoryNames = names
    chart.categoryAxis.labels.fontName = "Times-Roman"
    chart.categoryAxis.labels.fontSize = 7
    chart.categoryAxis.labels.fillColor = _colors.HexColor("#334155")
    chart.categoryAxis.labels.angle = 25
    chart.categoryAxis.labels.dy = -10
    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueMax = 1
    chart.valueAxis.valueStep = 1
    chart.valueAxis.labels.fontName = "Times-Roman"
    chart.valueAxis.labels.fontSize = 7
    chart.bars[0].fillColor = _colors.HexColor("#22c55e")
    # Color missing (0) bars red, submitted (1) bars green — a flat single
    # color wouldn't show the gap pattern as clearly.
    for i, v in enumerate(values):
        chart.bars[i].fillColor = _colors.HexColor("#22c55e") if v else _colors.HexColor("#ef4444")
    chart.barWidth = 10
    d.add(chart)
    d.add(String(width / 2, height - 12, "Evidence Submitted (green) vs Missing (red)",
                  fontName="Times-Bold", fontSize=8.5, fillColor=_colors.HexColor("#334155"),
                  textAnchor="middle"))
    return d


def _pdf_fraud_indicators_chart(indicators, width=340, height=150):
    """Bar chart of the Fraud & Crime Indicators table (Document Forgery,
    Identity Fraud, Financial Anomaly, Criminal Pattern Match) — added per
    user request to explain more report facts via graphs, so these four
    numbers are visually comparable instead of only read row-by-row in a
    table."""
    if not indicators:
        return None
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.lib import colors as _colors

    names = [n for n, v in indicators]
    values = [_safe_num(v) for n, v in indicators]
    if not any(values):
        return None

    d = Drawing(width, height)
    chart = VerticalBarChart()
    chart.x = 35
    chart.y = 40
    chart.width = width - 55
    chart.height = height - 65
    chart.data = [values]
    chart.categoryAxis.categoryNames = names
    chart.categoryAxis.labels.fontName = "Times-Roman"
    chart.categoryAxis.labels.fontSize = 7
    chart.categoryAxis.labels.fillColor = _colors.HexColor("#334155")
    chart.categoryAxis.labels.angle = 20
    chart.categoryAxis.labels.dy = -10
    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueMax = 100
    chart.valueAxis.valueStep = 25
    chart.valueAxis.labels.fontName = "Times-Roman"
    chart.valueAxis.labels.fontSize = 7
    chart.bars[0].fillColor = _colors.HexColor("#f87171")
    chart.barWidth = 12
    d.add(chart)
    d.add(String(width / 2, height - 12, "Fraud & Crime Indicators (%)",
                  fontName="Times-Bold", fontSize=8.5, fillColor=_colors.HexColor("#334155"),
                  textAnchor="middle"))
    return d


def _pdf_hypothesis_confidence_chart(hypotheses, width=380, height=170):
    """Horizontal bar chart comparing every hypothesis's confidence side by
    side — added per user request for more visual/graph coverage in the
    report beyond the Crime DNA radar and network diagram. Makes it
    visually obvious at a glance which hypothesis is strongest and by how
    much, without reading a wall of percentages."""
    if not hypotheses:
        return None
    from reportlab.graphics.charts.barcharts import HorizontalBarChart
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.lib import colors as _colors

    items = hypotheses[:6]
    values = [_safe_num(h.get("confidence", 0)) for h in items]
    names = [str(h.get("hypothesis") or h.get("name") or "Hypothesis")[:38] for h in items]
    if not any(values):
        return None

    d = Drawing(width, height)
    chart = HorizontalBarChart()
    chart.x = 140
    chart.y = 20
    chart.width = width - 165
    chart.height = height - 40
    chart.data = [values]
    chart.categoryAxis.categoryNames = names
    chart.categoryAxis.labels.fontName = "Times-Roman"
    chart.categoryAxis.labels.fontSize = 7.5
    chart.categoryAxis.labels.fillColor = _colors.HexColor("#334155")
    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueMax = 100
    chart.valueAxis.valueStep = 25
    chart.valueAxis.labels.fontName = "Times-Roman"
    chart.valueAxis.labels.fontSize = 7
    chart.bars[0].fillColor = _colors.HexColor("#8b5cf6")
    chart.barWidth = 8
    d.add(chart)
    d.add(String(width / 2, height - 12, "Hypothesis Confidence Comparison (%)",
                  fontName="Times-Bold", fontSize=9, fillColor=_colors.HexColor("#334155"),
                  textAnchor="middle"))
    return d


def _pdf_risk_signals_chart(metrics, width=380, height=190):
    """Vertical bar chart comparing the AI Verdict's independent signals
    (Crime Severity / Operational Risk / Immediate Threat / Evidence
    Confidence / Hypothesis Confidence / Risk Score) side by side. These
    are read as plain text elsewhere in the report and can look like they
    contradict each other (e.g. Risk Score 88% next to Operational Risk
    Medium) — a bar chart makes it visually clear these are different
    scales/signals being compared, not one number disagreeing with
    itself."""
    if not metrics:
        return None
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.lib import colors as _colors

    names = [str(n)[:14] for n, v in metrics]
    values = [_safe_num(v) for n, v in metrics]
    if not any(values):
        return None

    d = Drawing(width, height)
    chart = VerticalBarChart()
    chart.x = 40
    chart.y = 45
    chart.width = width - 60
    chart.height = height - 75
    chart.data = [values]
    chart.categoryAxis.categoryNames = names
    chart.categoryAxis.labels.fontName = "Times-Roman"
    chart.categoryAxis.labels.fontSize = 7
    chart.categoryAxis.labels.fillColor = _colors.HexColor("#334155")
    chart.categoryAxis.labels.angle = 20
    chart.categoryAxis.labels.dy = -12
    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueMax = 100
    chart.valueAxis.valueStep = 25
    chart.valueAxis.labels.fontName = "Times-Roman"
    chart.valueAxis.labels.fontSize = 7
    chart.bars[0].fillColor = _colors.HexColor("#f59e0b")
    chart.barWidth = 10
    d.add(chart)
    d.add(String(width / 2, height - 15, "Independent Signals Comparison — different scales, not one score",
                  fontName="Times-Bold", fontSize=8.5, fillColor=_colors.HexColor("#334155"),
                  textAnchor="middle"))
    return d


def _pdf_evidence_coverage_chart(coverage_pct, weighted_pct, width=300, height=140):
    """Small 2-bar chart comparing Evidence-Type Coverage (simple count)
    against Weighted Evidence Completeness (per-module weighted) — these
    two numbers have repeatedly been confused for the same metric when
    shown as plain text (e.g. 12% vs 30%); a side-by-side bar makes the
    two different measurements visually obvious."""
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.lib import colors as _colors

    coverage_pct = _safe_num(coverage_pct)
    weighted_pct = _safe_num(weighted_pct)

    d = Drawing(width, height)
    chart = VerticalBarChart()
    chart.x = 50
    chart.y = 30
    chart.width = width - 70
    chart.height = height - 55
    chart.data = [[coverage_pct, weighted_pct]]
    chart.categoryAxis.categoryNames = ["Evidence-Type\nCoverage", "Weighted\nCompleteness"]
    chart.categoryAxis.labels.fontName = "Times-Roman"
    chart.categoryAxis.labels.fontSize = 7.5
    chart.categoryAxis.labels.fillColor = _colors.HexColor("#334155")
    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueMax = 100
    chart.valueAxis.valueStep = 25
    chart.valueAxis.labels.fontName = "Times-Roman"
    chart.valueAxis.labels.fontSize = 7
    chart.bars[0].fillColor = _colors.HexColor("#0ea5e9")
    chart.barWidth = 30
    d.add(chart)
    d.add(String(width / 2, height - 12, "Two Different Completeness Metrics",
                  fontName="Times-Bold", fontSize=8.5, fillColor=_colors.HexColor("#334155"),
                  textAnchor="middle"))
    return d


def _pdf_progress_bar(pct, total_width=200, height=9, fill_color="#16a34a", track_color="#e2e8f0"):
    """Returns a small reportlab Table rendered as a horizontal progress
    bar — used for Investigation Progress, Evidence Strength Matrix, etc.
    Avoids unicode block characters (■), which render inconsistently
    across PDF viewers/fonts."""
    from reportlab.platypus import Table, TableStyle
    from reportlab.lib import colors as _colors
    try:
        pct = max(0, min(100, float(pct)))
    except (TypeError, ValueError):
        pct = 0
    filled = round(total_width * pct / 100)
    remaining = max(1, total_width - filled)
    cols = [filled, remaining] if filled > 0 else [1, remaining]
    bg = [_colors.HexColor(fill_color), _colors.HexColor(track_color)] if filled > 0 else \
         [_colors.HexColor(track_color), _colors.HexColor(track_color)]
    bar = Table([["", ""]], colWidths=cols, rowHeights=[height])
    bar.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), bg[0]),
        ("BACKGROUND", (1, 0), (1, 0), bg[1]),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return bar
