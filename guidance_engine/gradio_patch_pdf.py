"""
GRADIO PDF PATCH - Guidance Engine Section for PDF Report
Call this when building PDF to append guidance section
"""

def append_guidance_to_pdf(pdf_builder, guidance_dict):
    if not guidance_dict or 'error' in guidance_dict:
        return pdf_builder
    
    try:
        # Add section header
        pdf_builder.set_font("Arial", "B", 14)
        pdf_builder.set_text_color(31, 41, 55)
        pdf_builder.cell(0, 10, "KNOWLEDGE-DRIVEN INVESTIGATION GUIDANCE", ln=True)
        pdf_builder.set_font("Arial", "", 10)
        pdf_builder.set_text_color(107, 114, 128)
        pdf_builder.cell(0, 6, f"Case ID: {guidance_dict.get('case_id', 'N/A')} | Generated: {guidance_dict.get('generated_at', 'N/A')}", ln=True)
        pdf_builder.ln(2)
        
        # Summary box
        pdf_builder.set_fill_color(248, 250, 252)
        pdf_builder.set_draw_color(203, 213, 225)
        pdf_builder.cell(0, 8, f" Total Directions: {guidance_dict.get('total_directions', 0)}  |  Critical: {guidance_dict.get('critical_count', 0)}  |  High Priority: {guidance_dict.get('high_count', 0)}", ln=True, fill=True)
        pdf_builder.ln(3)
        
        # Each direction
        for d in guidance_dict.get('recommended_directions', []):
            priority_colors = {
                'Critical': (220, 38, 38),
                'Very High': (234, 88, 12),
                'High': (202, 138, 4),
                'Medium': (37, 99, 235),
                'Low': (107, 114, 128)
            }
            r, g, b = priority_colors.get(d['priority'], (107, 114, 128))
            
            # Colored left bar
            pdf_builder.set_draw_color(r, g, b)
            pdf_builder.set_line_width(1.5)
            pdf_builder.line(10, pdf_builder.get_y(), 10, pdf_builder.get_y() + 45)
            pdf_builder.set_line_width(0.2)
            
            pdf_builder.set_x(15)
            pdf_builder.set_font("Arial", "B", 11)
            pdf_builder.set_text_color(r, g, b)
            pdf_builder.cell(0, 6, f"#{d['rank']} {d['title']}  [{d['priority']}]", ln=True)
            
            pdf_builder.set_x(15)
            pdf_builder.set_font("Arial", "", 9)
            pdf_builder.set_text_color(75, 85, 99)
            pdf_builder.cell(0, 5, f"Likelihood: {d['likelihood']}%  |  Cost: {d['cost']}  |  Time: {d['time_estimate']}  |  Expected Gain: +{d['expected_evidence_gain']}%", ln=True)
            
            pdf_builder.set_x(15)
            pdf_builder.set_font("Arial", "B", 9)
            pdf_builder.set_text_color(37, 99, 235)
            pdf_builder.cell(0, 5, "WHY:", ln=True)
            
            pdf_builder.set_x(15)
            pdf_builder.set_font("Arial", "", 9)
            pdf_builder.set_text_color(55, 65, 81)
            pdf_builder.multi_cell(0, 5, d['why'])
            
            pdf_builder.set_x(15)
            pdf_builder.set_font("Arial", "", 9)
            pdf_builder.multi_cell(0, 5, d['description'])
            
            if d.get('agencies_to_involve'):
                pdf_builder.set_x(15)
                pdf_builder.set_font("Arial", "I", 8)
                pdf_builder.set_text_color(107, 114, 128)
                pdf_builder.cell(0, 4, f"Agencies: {', '.join(d['agencies_to_involve'])}", ln=True)
            
            if d.get('expected_documents'):
                pdf_builder.set_x(15)
                pdf_builder.set_font("Arial", "I", 8)
                pdf_builder.cell(0, 4, f"Documents: {', '.join(d['expected_documents'])}", ln=True)
            
            pdf_builder.ln(4)
        
        pdf_builder.set_text_color(0, 0, 0)
        return pdf_builder
        
    except Exception as e:
        pdf_builder.set_font("Arial", "I", 10)
        pdf_builder.set_text_color(220, 38, 38)
        pdf_builder.cell(0, 10, f"Guidance section error: {str(e)}", ln=True)
        pdf_builder.set_text_color(0, 0, 0)
        return pdf_builder
