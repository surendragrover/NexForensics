"""
reports/html_renderers.py — live in-app HTML widgets (rendered inline in
the Gradio UI, NOT part of the PDF export):

  build_graphs_html      matplotlib risk/evidence gauges -> base64 PNG -> <img> HTML
  _inv_render_html       renders the investigator_integration.py output as HTML
  _build_network_html    a (non-interactive) network-graph HTML render

matplotlib imports are LOCAL (inside build_graphs_html, as in the
original file).

Extracted from gradio_app.py, verbatim (no behavior change).
"""

from html import escape as _esc_html
import base64
import io

from config import log


def build_graphs_html(scores: dict, history: list, report_data: dict = None) -> str:
    """
    Returns HTML string with two inline charts:
      1. Radar / bar chart of current analysis scores
      2. Risk trend line of last 10 analyses
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        from matplotlib.gridspec import GridSpec

        BG   = "#0d1117"
        CARD = "#111620"
        ACC  = "#0077ff"
        RED  = "#ef4444"
        AMB  = "#f59e0b"
        GRN  = "#22c55e"
        PUR  = "#a78bfa"
        TXT  = "#94a3b8"
        DIM  = "#1a2236"

        fig = plt.figure(figsize=(11, 4.2), facecolor=BG)
        gs  = GridSpec(1, 2, figure=fig, wspace=0.38)

        # ── Chart 1: Circular gauges — current scores ──────────────────────────
        ax1 = fig.add_subplot(gs[0])
        ax1.set_facecolor(CARD)
        fig.patch.set_facecolor(BG)
        ax1.axis("off")
        ax1.set_aspect("equal")

        metrics = [
            ("Deception",  scores.get("deception",   0), RED),
            ("Credibility",scores.get("credibility", 0), GRN),
            ("Risk",       scores.get("risk",        0), AMB),
            ("Voice",      scores.get("voice",       0), "#60a5fa"),
            ("NER",        scores.get("ner",         0), ACC),
            ("OCR",        scores.get("ocr",         0), "#f472b6"),
            ("Risk Mdl",   scores.get("pattern",     0), PUR),
        ]
        cols, gauge_r = 4, 0.36
        rows = -(-len(metrics) // cols)  # ceil
        for i, (label, val, col) in enumerate(metrics):
            row, colpos = divmod(i, cols)
            cx = 0.6 + colpos * 1.05
            cy = (rows - 1 - row) * 1.15 + 0.6
            # background ring
            ax1.add_patch(mpatches.Wedge((cx, cy), gauge_r, 0, 360,
                          width=0.11, facecolor=DIM, edgecolor="none"))
            # progress ring (starts at 12 o'clock, clockwise)
            pct = max(0, min(val, 100)) / 100
            ax1.add_patch(mpatches.Wedge((cx, cy), gauge_r, 90 - pct*360, 90,
                          width=0.11, facecolor=col, edgecolor="none"))
            ax1.text(cx, cy, f"{val:.0f}%", ha="center", va="center",
                     color="white", fontsize=9, fontweight="600")
            ax1.text(cx, cy - gauge_r - 0.16, label, ha="center", va="top",
                     color=TXT, fontsize=7.3)

        ax1.set_xlim(0, cols * 1.05)
        ax1.set_ylim(0, rows * 1.15 + 0.35)
        ax1.set_title("Current Analysis", color="white",
                      fontsize=10, fontweight="600", pad=10)

        # ── Chart 2: Risk trend line ───────────────────────────────────────────
        ax2 = fig.add_subplot(gs[1])
        ax2.set_facecolor(CARD)

        if len(history) >= 2:
            x_vals = list(range(len(history)))
            y_risk = [h["risk"] for h in history]
            y_dec  = [h["deception"] for h in history]

            ax2.fill_between(x_vals, y_risk, alpha=0.12, color=AMB)
            ax2.fill_between(x_vals, y_dec,  alpha=0.10, color=RED)
            ax2.plot(x_vals, y_risk, color=AMB, linewidth=1.8,
                     marker="o", markersize=4, label="Risk")
            ax2.plot(x_vals, y_dec,  color=RED, linewidth=1.8,
                     linestyle="--", marker="s", markersize=3.5, label="Deception")

            # Threshold line at 75
            ax2.axhline(75, color="#334155", linewidth=0.8,
                        linestyle=":", label="High-risk threshold")

            ax2.set_xlim(-0.3, max(len(history)-1, 1)+0.3)
            ax2.set_ylim(0, 105)
            ax2.set_xticks(x_vals)
            ax2.set_xticklabels(
                [h.get("case_id","")[-6:] if h.get("case_id") else f"#{i+1}"
                 for i, h in enumerate(history)],
                rotation=30, ha="right", fontsize=7.5, color=TXT
            )
            leg = ax2.legend(fontsize=7.5, facecolor=CARD,
                             edgecolor=DIM, labelcolor=TXT,
                             framealpha=0.8, loc="upper left")
        else:
            ax2.text(0.5, 0.5, "Run 2+ analyses\nto see trend",
                     ha="center", va="center", color=TXT, fontsize=9,
                     transform=ax2.transAxes)

        ax2.set_title("Risk Trend", color="white",
                      fontsize=10, fontweight="600", pad=10)
        ax2.set_ylabel("Score (%)", color=TXT, fontsize=8)
        ax2.spines[:].set_color(DIM)
        for spine in ax2.spines.values():
            spine.set_linewidth(0.5)
        ax2.tick_params(colors=TXT, labelsize=8)
        ax2.yaxis.label.set_color(TXT)
        ax2.set_facecolor(CARD)
        ax2.set_axisbelow(True)
        ax2.yaxis.grid(True, color=DIM, linewidth=0.4, linestyle="--")

        plt.tight_layout(pad=1.2)

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                    facecolor=BG, edgecolor="none")
        plt.close(fig)
        buf.seek(0)
        b64 = base64.b64encode(buf.read()).decode()

        return f"""
        <div style="text-align:center;background:{BG};padding:8px;border-radius:10px;">
            <img src="data:image/png;base64,{b64}" style="max-width:100%;border-radius:8px;" />
        </div>
        """
    except Exception as e:
        log.error(f"Graph error: {e}")
        return f"<p style='color:#64748b;font-size:12px;padding:8px;'>Graph unavailable: {e}</p>"


def _inv_render_html(value, empty_label="No data available."):
    """Renders Investigator Engine output (lists/dicts) as readable, styled
    HTML instead of a raw JSON tree — used for the 'Investigator
    Intelligence' panels so the report reads like text, not JSON."""

    def _leaf(v):
        if v is True:
            return "Yes"
        if v is False:
            return "No"
        if v is None or v == "":
            return "Unknown"
        return _esc_html(str(v))

    def _row(v, depth=0):
        pad = 14 + depth * 14
        if isinstance(v, dict):
            if not v:
                return ""
            parts = []
            for k, vv in v.items():
                label = _esc_html(str(k).replace("_", " ").strip().title())
                if isinstance(vv, (dict, list)) and vv:
                    parts.append(
                        f"<div style='margin:2px 0;padding-left:{pad}px;'>"
                        f"<span style='color:#60a5fa;font-weight:600;'>{label}:</span>"
                        f"{_row(vv, depth + 1)}</div>"
                    )
                else:
                    parts.append(
                        f"<div style='margin:2px 0;padding-left:{pad}px;'>"
                        f"<span style='color:#60a5fa;font-weight:600;'>{label}:</span> "
                        f"<span style='color:#e2e8f0;'>{_leaf(vv)}</span></div>"
                    )
            return "".join(parts)
        if isinstance(v, list):
            if not v:
                return ""
            parts = []
            for item in v:
                if isinstance(item, (dict, list)):
                    parts.append(
                        f"<div style='margin:4px 0;padding:8px;background:#0d1117;"
                        f"border-radius:6px;border-left:2px solid #1a2236;'>{_row(item, depth + 1)}</div>"
                    )
                else:
                    parts.append(f"<div style='margin:2px 0;padding-left:{pad}px;color:#e2e8f0;'>• {_leaf(item)}</div>")
            return "".join(parts)
        return f"<span style='color:#e2e8f0;'>{_leaf(v)}</span>"

    body = _row(value)
    if not body:
        return (f"<div style='background:#111620;border:0.5px solid #1a2236;"
                f"border-radius:8px;padding:12px;font-size:12px;color:#64748b;'>{empty_label}</div>")
    return (f"<div style='background:#111620;border:0.5px solid #1a2236;"
            f"border-radius:8px;padding:12px;font-size:12px;'>{body}</div>")


def _build_network_html(network_matches, network_summary, financial_flags, vehicle_flags):
    """Builds HTML for the new Network & Financial Intelligence panel."""
    if not network_matches and not financial_flags and not vehicle_flags:
        return (
            "<div style='background:#111620;border:0.5px solid #1a2236;"
            "border-radius:10px;padding:16px;margin-top:4px;'>"
            "<p style='font-size:10px;color:#475569;text-transform:uppercase;"
            "letter-spacing:.1em;margin-bottom:14px;'>Network & Financial Intelligence</p>"
            "<p style='font-size:12px;color:#64748b;'>No network or financial data provided.</p>"
            "</div>"
        )

    html = (
        "<div style='background:#111620;border:0.5px solid #1a2236;"
        "border-radius:10px;padding:16px;margin-top:4px;'>"
        "<p style='font-size:10px;color:#475569;text-transform:uppercase;"
        "letter-spacing:.1em;margin-bottom:14px;'>Network & Financial Intelligence</p>"
    )

    # Network matches
    if network_matches:
        html += (
            "<div style='margin-bottom:12px;'>"
            "<p style='font-size:11px;color:#60a5fa;font-weight:600;margin-bottom:6px;'>"
            "🔗 Associate Database Matches</p>"
        )
        for m in network_matches[:8]:
            # BUG FIX (reviewer feedback — "Datasoft" residual noise): a
            # PARTIAL-strength dataset hit (fuzzy name/word overlap, no
            # case evidence directly linking the entity to this case) used
            # to render exactly like a real "network association" — same
            # section, same visual weight as a STRONG match. Per reviewer's
            # exact suggested framing, label PARTIAL hits explicitly as a
            # semantic/database lead rather than an established network
            # association, so a reader can't mistake dataset word-overlap
            # for an evidenced link to this case.
            if m["strength"] == "strong":
                strength_col = "#22c55e"
                _kind_label = "NETWORK MATCH"
            else:
                strength_col = "#f59e0b"
                _kind_label = "SEMANTIC/DATABASE LEAD — no evidentiary case link established"
            html += (
                f"<div style='font-size:11px;color:#e2e8f0;margin-bottom:4px;"
                f"padding:6px 8px;background:#0d1117;border-radius:6px;'>"
                f"<span style='color:{strength_col};font-weight:600;'>[{_kind_label}]</span> "
                f"{m['query']} &rarr; <b>{m['name']}</b> "
                f"<span style='color:#64748b;'>({m['dataset']})</span><br/>"
                f"<span style='font-size:10px;color:#475569;'>{m['data'][:100]}...</span>"
                f"</div>"
            )
        html += f"<p style='font-size:10px;color:#475569;margin-top:4px;'>{network_summary}</p></div>"

    # Financial flags
    if financial_flags:
        html += (
            "<div style='margin-bottom:12px;border-top:0.5px solid #1a2236;padding-top:10px;'>"
            "<p style='font-size:11px;color:#f59e0b;font-weight:600;margin-bottom:6px;'>"
            "💰 Financial Red Flags</p>"
        )
        for flag in financial_flags:
            html += f"<div style='font-size:11px;color:#f87171;margin-bottom:3px;'>⚠ {flag}</div>"
        html += "</div>"

    # Vehicle flags
    if vehicle_flags:
        html += (
            "<div style='border-top:0.5px solid #1a2236;padding-top:10px;'>"
            "<p style='font-size:11px;color:#a78bfa;font-weight:600;margin-bottom:6px;'>"
            "🚗 Vehicle / Asset References</p>"
        )
        for flag in vehicle_flags:
            html += f"<div style='font-size:11px;color:#e2e8f0;margin-bottom:3px;'>• {flag}</div>"
        html += "</div>"

    html += "</div>"
    return html
