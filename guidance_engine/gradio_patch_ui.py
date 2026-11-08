def render_guidance_section(report_data):
    if not isinstance(report_data, dict):
        return "<div style='color:#64748b;padding:8px;'>No guidance data.</div>"
    guidance = report_data.get("guidance") or {}
    if isinstance(guidance, dict) and guidance.get("error"):
        return "<div style='color:#64748b;padding:8px;'>Guidance Engine unavailable.</div>"
    dirs = guidance.get("recommended_directions", []) if isinstance(guidance, dict) else []
    if not dirs:
        return "<div style='color:#64748b;padding:8px;'>No guidance directions.</div>"
    html = "<div style='background:#111620;border:0.5px solid #1a2236;border-radius:10px;padding:16px;'>"
    html += "<p style='font-size:10px;color:#475569;text-transform:uppercase;letter-spacing:.1em;margin-bottom:14px;'>Investigation Guidance</p>"
    for d in dirs:
        html += f"<div style='font-size:11px;color:#e2e8f0;margin-bottom:6px;'>• {d.get('title', d.get('hypothesis',''))}</div>"
    html += "</div>"
    return html
