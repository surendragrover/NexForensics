def guidance_to_html(guidance_dict):
    if not guidance_dict or 'error' in guidance_dict:
        return "<div style='color:red'>Guidance Engine unavailable</div>"
    
    dirs = guidance_dict.get('recommended_directions', [])
    if not dirs:
        return "<div style='color:gray'>No guidance directions generated</div>"
    
    html = "<div style='font-family:Arial; padding:10px;'>"
    html += f"<h3>🔍 Investigation Guidance ({guidance_dict.get('total_directions', 0)} directions)</h3>"
    
    for d in dirs:
        color = {'Critical': '#dc2626', 'Very High': '#ea580c', 'High': '#ca8a04', 'Medium': '#2563eb'}.get(d['priority'], '#6b7280')
        html += f"<div style='border-left:4px solid {color}; margin:10px 0; padding:10px; background:#f8fafc;'>"
        html += f"<strong>[{d['rank']}] {d['title']}</strong> <span style='color:{color}; font-weight:bold;'>[{d['priority']}]</span><br>"
        html += f"<em>Likelihood: {d['likelihood']}% | Cost: {d['cost']} | Time: {d['time_estimate']} | Gain: +{d['expected_evidence_gain']}%</em><br>"
        html += f"<p><strong>WHY:</strong> {d['why']}</p>"
        html += f"<p>{d['description'][:200]}...</p>"
        if d['agencies_to_involve']:
            html += f"<small>🏛 Agencies: {', '.join(d['agencies_to_involve'])}</small><br>"
        if d['expected_documents']:
            html += f"<small>📄 Documents: {', '.join(d['expected_documents'])}</small>"
        html += "</div>"
    
    html += "</div>"
    return html


def guidance_to_pdf_section(guidance_dict):
    if not guidance_dict or 'error' in guidance_dict:
        return ""
    
    lines = []
    lines.append("=" * 60)
    lines.append("KNOWLEDGE-DRIVEN INVESTIGATION GUIDANCE")
    lines.append("=" * 60)
    lines.append(f"Case ID: {guidance_dict.get('case_id', 'N/A')}")
    lines.append(f"Generated: {guidance_dict.get('generated_at', 'N/A')}")
    lines.append(f"Total Directions: {guidance_dict.get('total_directions', 0)}")
    lines.append(f"Critical: {guidance_dict.get('critical_count', 0)} | High: {guidance_dict.get('high_count', 0)}")
    lines.append("-" * 60)
    
    for d in guidance_dict.get('recommended_directions', []):
        lines.append(f"\n[{d['rank']}] {d['title']} | Priority: {d['priority']}")
        lines.append(f"Likelihood: {d['likelihood']}% | Cost: {d['cost']} | Time: {d['time_estimate']}")
        lines.append(f"Expected Evidence Gain: +{d['expected_evidence_gain']}%")
        lines.append(f"Legal Difficulty: {d['legal_difficulty']}")
        lines.append(f"\nWHY: {d['why']}")
        lines.append(f"\nDescription: {d['description']}")
        if d['agencies_to_involve']:
            lines.append(f"\nAgencies: {', '.join(d['agencies_to_involve'])}")
        if d['expected_documents']:
            lines.append(f"Documents: {', '.join(d['expected_documents'])}")
        if d['failure_conditions']:
            lines.append(f"Failure Conditions: {', '.join(d['failure_conditions'])}")
        lines.append("-" * 40)
    
    return "\n".join(lines)
