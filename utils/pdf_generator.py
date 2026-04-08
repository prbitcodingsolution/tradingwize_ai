"""PDF Report Generator for Stock Analysis"""
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.lib.colors import HexColor
from io import BytesIO
from datetime import datetime


def generate_pdf_report(content: str, stock_symbol: str = "Stock") -> BytesIO:
    """
    Generate a formatted PDF report from the stock analysis content
    
    Args:
        content: The stock analysis text content
        stock_symbol: The stock symbol for the report title
        
    Returns:
        BytesIO: PDF file as bytes
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter,
                           rightMargin=72, leftMargin=72,
                           topMargin=72, bottomMargin=18)
    
    # Container for the 'Flowable' objects
    elements = []
    
    # Define custom styles
    styles = getSampleStyleSheet()
    
    # Title style
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=HexColor('#667eea'),
        spaceAfter=30,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    )
    
    # Subtitle style
    subtitle_style = ParagraphStyle(
        'CustomSubtitle',
        parent=styles['Normal'],
        fontSize=12,
        textColor=HexColor('#666666'),
        spaceAfter=20,
        alignment=TA_CENTER,
        fontName='Helvetica'
    )
    
    # Body style
    body_style = ParagraphStyle(
        'CustomBody',
        parent=styles['BodyText'],
        fontSize=10,
        textColor=HexColor('#333333'),
        spaceAfter=10,
        alignment=TA_LEFT,
        fontName='Helvetica',
        leading=14,
        leftIndent=0,
        rightIndent=0
    )
    
    # Header style for sections
    header_style = ParagraphStyle(
        'CustomHeader',
        parent=styles['Heading2'],
        fontSize=13,
        textColor=HexColor('#667eea'),
        spaceAfter=10,
        spaceBefore=15,
        fontName='Helvetica-Bold',
        leftIndent=0
    )
    
    # Subheader style for subsections
    subheader_style = ParagraphStyle(
        'CustomSubheader',
        parent=styles['Heading3'],
        fontSize=11,
        textColor=HexColor('#764ba2'),
        spaceAfter=8,
        spaceBefore=10,
        fontName='Helvetica-Bold',
        leftIndent=10
    )
    
    # Add professional title
    title = Paragraph(f"📊 Stock Analysis Report", title_style)
    elements.append(title)
    
    # Add subtitle with stock symbol and date
    subtitle = Paragraph(
        f"<b>{stock_symbol}</b> | Generated on {datetime.now().strftime('%B %d, %Y at %I:%M %p')}",
        subtitle_style
    )
    elements.append(subtitle)
    elements.append(Spacer(1, 0.2*inch))
    
    # Add a horizontal line separator
    from reportlab.platypus import HRFlowable
    elements.append(HRFlowable(width="100%", thickness=1, color=HexColor('#667eea'), 
                               spaceAfter=0.2*inch, spaceBefore=0.1*inch))
    
    elements.append(Spacer(1, 0.1*inch))
    
    # Process content - split into sections
    # First, split by double newlines to get paragraphs
    sections = content.split('\n\n')
    
    for section in sections:
        if not section.strip():
            continue
            
        section_text = section.strip()
        
        # Detect section type
        is_main_header = False
        is_subheader = False
        
        # Check for main section headers (with emojis or all caps with **)
        if section_text.startswith('**') and section_text.endswith('**'):
            section_text = section_text.strip('*').strip()
            is_main_header = True
        elif any(emoji in section_text[:50] for emoji in ['🦈', '📊', '💰', '📈', '🏢', '📋', '🏆', '🎯', '📰']):
            is_main_header = True
        
        # Convert markdown formatting
        # Handle bold text (**text**)
        import re
        section_text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', section_text)
        
        # Process line by line for better formatting
        lines = section_text.split('\n')
        formatted_lines = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Skip markdown table separator lines (e.g. |---|---|---|)
            if re.match(r'^\|[\s\-:|]+\|$', line):
                continue

            # Convert markdown table rows to plain text
            if line.startswith('|') and line.endswith('|'):
                cells = [c.strip() for c in line.strip('|').split('|')]
                line = ' | '.join(c for c in cells if c)

            # Check if it's a bullet point
            if line.startswith('- ') or line.startswith('• '):
                # Bullet point - add indentation
                line = '&nbsp;&nbsp;&nbsp;&nbsp;• ' + line[2:].strip()
            elif line.startswith('  - ') or line.startswith('  • '):
                # Sub-bullet point - more indentation
                line = '&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;◦ ' + line[4:].strip()
            
            formatted_lines.append(line)
        
        # Join lines with line breaks
        formatted_text = '<br/>'.join(formatted_lines)

        # Sanitize HTML for ReportLab: only allow <b>, <i>, <u>, <br/> tags
        # Remove any <br> without closing slash (ReportLab requires <br/>)
        formatted_text = formatted_text.replace('<br>', '<br/>')
        # Remove duplicate <br/>
        while '<br/><br/>' in formatted_text:
            formatted_text = formatted_text.replace('<br/><br/>', '<br/>')

        # Create paragraph with appropriate style
        if is_main_header:
            # Add a small divider line before main headers (except first one)
            if len(elements) > 3:  # Skip for title area
                elements.append(Spacer(1, 0.1*inch))
            p = Paragraph(formatted_text, header_style)
            elements.append(p)
            elements.append(Spacer(1, 0.1*inch))
        else:
            # Regular content
            p = Paragraph(formatted_text, body_style)
            elements.append(p)
            elements.append(Spacer(1, 0.08*inch))
    
    # Add footer
    elements.append(Spacer(1, 0.5*inch))
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=9,
        textColor=HexColor('#999999'),
        alignment=TA_CENTER,
        fontName='Helvetica-Oblique'
    )
    footer = Paragraph(
        "Generated by Stock Analysis AI | Powered by Pydantic AI + Gemini 2.0 Flash",
        footer_style
    )
    elements.append(footer)
    
    # Build PDF
    doc.build(elements)
    
    # Get the value of the BytesIO buffer
    buffer.seek(0)
    return buffer
