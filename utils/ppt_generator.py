"""
Automated PPT Generator for Stock Analysis
Fetches data from database and generates professional PowerPoint presentations
NOW WITH BILINGUAL SUPPORT (English + Hindi)
GENERATES SEPARATE PPT FILES FOR EACH LANGUAGE
"""

import os
import json
from typing import Dict, List, Any, Optional, Union
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN
from pptx.dml.color import RGBColor
from datetime import datetime
import sys
import platform
import subprocess

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database_utility.database import StockDatabase
from dotenv import load_dotenv
import openai

load_dotenv()


class  StockPPTGenerator:
    """Generate professional PowerPoint presentations from stock analysis data with bilingual support"""
    
    def __init__(self):
        """Initialize PPT generator with OpenRouter LLM"""
        self.openrouter_api_key = os.getenv('OPENROUTER_API_KEY')
        self.openrouter_base_url = os.getenv('OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1')
        
        # Configure OpenAI client to use OpenRouter
        self.client = openai.OpenAI(
            api_key=self.openrouter_api_key,
            base_url=self.openrouter_base_url
        )
        
        self.db = StockDatabase()
    
    def translate_to_hindi(self, text_or_list: Union[str, List[str]]) -> Union[str, List[str]]:
        """
        Translate English text to Hindi using LLM.
        For lists: translates each item individually to avoid delimiter/mismatch issues.
        For strings: translates the full text as one block.
        """
        _sys_msg = (
            "You are a professional Hindi translator specializing in financial content. "
            "Translate English to PURE MODERN HINDI using Devanagari script. "
            "DO NOT create Hinglish (mixing English words in Hindi sentences). "
            "Translate ALL common words to Hindi. "
            "Only keep stock tickers (TCS.NS), financial abbreviations (EBITDA, CAGR, EPS, PE, ROE, ROCE), "
            "currency symbols (₹, $, Cr), numbers, and proper names in English. "
            "Return ONLY the Hindi translation, nothing else."
        )

        _translation_rules = """Translate to PURE MODERN HINDI (Devanagari script) for an investor presentation.

TRANSLATE these words to Hindi:
company→कंपनी, market→बाजार, business→व्यवसाय, growth→वृद्धि, revenue→राजस्व, profit→लाभ,
services→सेवाएं, customers→ग्राहक, industry→उद्योग, technology→प्रौद्योगिकी, global→वैश्विक,
leading→अग्रणी, provider→प्रदाता, consulting→परामर्श, strong/robust→मजबूत, financial→वित्तीय,
performance→प्रदर्शन, positive→सकारात्मक, outlook→दृष्टिकोण, investment→निवेश, investor→निवेशक,
opportunity→अवसर, dividend→लाभांश, stability→स्थिरता, potential→क्षमता, future→भविष्य

KEEP in English: stock tickers, EBITDA/CAGR/EPS/PE/ROE/ROCE, ₹/$/Cr, numbers, proper names, IT/AI/CEO

"""

        try:
            # Handle list input — translate each item individually
            if isinstance(text_or_list, list):
                if not text_or_list:
                    return []

                # Filter out None/empty items, track indices
                hindi_results = list(text_or_list)  # start with English copy
                for i, item in enumerate(text_or_list):
                    if not item or not str(item).strip():
                        continue
                    try:
                        response = self.client.chat.completions.create(
                            model="openai/gpt-oss-120b",
                            messages=[
                                {"role": "system", "content": _sys_msg},
                                {"role": "user", "content": _translation_rules + f"Translate this:\n{item}"}
                            ],
                            temperature=0.3,
                            max_tokens=500
                        )
                        result = response.choices[0].message.content
                        if result and result.strip():
                            hindi_results[i] = result.strip()
                    except Exception as item_err:
                        print(f"⚠️ Translation failed for item {i}: {item_err}")
                        # Keep English for this item

                return hindi_results

            # Handle string input
            else:
                if not text_or_list or not str(text_or_list).strip():
                    return ""

                response = self.client.chat.completions.create(
                    model="openai/gpt-oss-120b",
                    messages=[
                        {"role": "system", "content": _sys_msg},
                        {"role": "user", "content": _translation_rules + f"Translate this:\n{text_or_list}"}
                    ],
                    temperature=0.3,
                    max_tokens=1500
                )
                result = response.choices[0].message.content
                return result.strip() if result else text_or_list

        except Exception as e:
            print(f"⚠️ Translation error: {e}. Using English as fallback.")
            return text_or_list  # Fallback to English
    
    def fetch_stock_data(self, stock_symbol: str) -> Optional[Dict[str, Any]]:
        """
        Fetch latest stock data from database
        
        Args:
            stock_symbol: Stock ticker symbol (e.g., 'RELIANCE.NS')
        
        Returns:
            Dict with stock data or None if not found
        """
        try:
            if not self.db.connect():
                print("❌ Failed to connect to database")
                return None
            
            # Get latest analysis
            data = self.db.get_latest_analysis(stock_symbol)
            
            if not data:
                print(f"❌ No data found for {stock_symbol}")
                return None
            
            # Structure the data for LLM
            structured_data = {
                "stock_name": data['stock_name'],
                "stock_symbol": data['stock_symbol'],
                "fundamentals": data['analyzed_response'],
                "sentiment": {
                    "current_market_sentiment": data.get('market_senti', 'Not available'),
                    "current_sentiment_status": data.get('current_market_senti_status', 'neutral'),
                    "future_outlook": data.get('future_senti', 'Not available'),
                    "future_sentiment_status": data.get('future_senti_status', 'neutral')
                },
                "tech_analysis": data.get('tech_analysis', {}),
                "selection": data.get('selection', False),
                "analyzed_at": str(data.get('analyzed_at', ''))
            }
            
            self.db.disconnect()
            return structured_data
            
        except Exception as e:
            print(f"❌ Error fetching stock data: {e}")
            if self.db.conn:
                self.db.disconnect()
            return None
    
    def generate_slide_structure(self, stock_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Use LLM to generate PPT slide structure with comprehensive ENGLISH content
        Then translate to Hindi for bilingual support
        
        Args:
            stock_data: Structured stock data from database
        
        Returns:
            Dict with slide structure including both English and Hindi content
        """
        try:
            print("🤖 Generating comprehensive slide structure using LLM (English)...")
            
            # Safely extract sentiment data with None handling
            current_sentiment = stock_data['sentiment'].get('current_market_sentiment')
            future_outlook = stock_data['sentiment'].get('future_outlook')
            current_sentiment_status = stock_data['sentiment'].get('current_sentiment_status', 'neutral')
            future_sentiment_status = stock_data['sentiment'].get('future_sentiment_status', 'neutral')
            
            # Format sentiment data safely
            if current_sentiment and current_sentiment != 'Not available':
                market_sentiment_text = current_sentiment[:2000]
            else:
                market_sentiment_text = 'Sentiment data not available - stock needs to be analyzed in Analytics section'
            
            if future_outlook and future_outlook != 'Not available':
                future_outlook_text = future_outlook[:2000]
            else:
                future_outlook_text = 'Future outlook not available - stock needs to be analyzed in Analytics section'
            
            # Create enhanced prompt for LLM (ENGLISH ONLY - we'll translate after)
            prompt = f"""You are a senior financial analyst creating a comprehensive, professional stock analysis presentation for investors.

Based on the following detailed stock data, generate a rich PPT structure with 10-12 slides that includes BOTH bullet points AND paragraph-style content.

Stock Data:
Stock Name: {stock_data['stock_name']}
Stock Symbol: {stock_data['stock_symbol']}
Selection Status: {'SELECTED' if stock_data['selection'] else 'NOT SELECTED'}
Current Sentiment: {current_sentiment_status}
Future Outlook: {future_sentiment_status}

Fundamental Analysis:
{stock_data['fundamentals'][:3000]}

Market Sentiment:
{market_sentiment_text}

Future Outlook:
{future_outlook_text}

Technical Metrics:
{json.dumps(stock_data['tech_analysis'], indent=2)}

Generate a JSON structure with the following format:
{{
  "slides": [
    {{
      "title": "Slide Title",
      "type": "bullets" or "paragraph" or "mixed",
      "content": ["Point 1", "Point 2", ...] for bullets,
      "paragraph": "Full paragraph text..." for paragraph slides,
      "summary": "Brief summary of the slide" (optional)
    }}
  ]
}}

CRITICAL REQUIREMENTS:

1. Create 10-12 comprehensive slides:
   - Slide 1: Title slide (bullets) - Company name, symbol, date
   - Slide 2: Executive Summary (paragraph) - 150-200 word overview of the company and investment thesis
   - Slide 3: Company Overview (mixed) - 2-3 bullets + 100-word paragraph about business model
   - Slide 4: Financial Performance (bullets) - 6-8 detailed financial metrics with actual numbers
   - Slide 5: Financial Analysis (paragraph) - 150-200 word analysis of financial health and trends
   - Slide 6: Technical Analysis (bullets) - 5-7 key technical indicators with values
   - Slide 7: Market Position & Competitive Landscape (mixed) - 3-4 bullets + 100-word paragraph
   - Slide 8: Current Market Sentiment (bullets) - 5-6 sentiment indicators and insights
   - Slide 9: Future Outlook & Growth Drivers (paragraph) - 150-200 word analysis of future prospects
   - Slide 10: Investment Recommendation (mixed) - 3-4 key points + 100-word recommendation
   - Slide 11: Risk Factors (bullets) - 6-8 specific risks with details
   - Slide 12: Conclusion & Next Steps (paragraph) - 100-150 word summary and action items

2. Content Guidelines:
   - For BULLET slides: 5-8 detailed points (not just 3-5)
   - For PARAGRAPH slides: 100-200 words of flowing narrative
   - For MIXED slides: 3-4 bullets + 80-120 word paragraph
   - Include ALL specific numbers, percentages, and metrics from the data
   - Use professional, investor-friendly language
   - Make content actionable and insightful

3. Paragraph Content Should:
   - Tell a story about the company/analysis
   - Connect different data points
   - Provide context and interpretation
   - Be engaging and easy to read
   - Include specific examples and numbers

4. Bullet Points Should:
   - Be specific and data-driven
   - Include actual numbers and metrics
   - Be concise but informative (10-20 words each)
   - Provide actionable insights

5. Extract and use:
   - All financial metrics (revenue, profit, margins, PE ratio, etc.)
   - All technical indicators (price, market cap, 52-week high/low, etc.)
   - Sentiment scores and analysis
   - Growth trends and forecasts
   - Competitive advantages
   - Risk factors

Return ONLY the JSON structure, no additional text or markdown."""

            # Call LLM with higher token limit for comprehensive content
            response = self.client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=[
                    {"role": "system", "content": "You are a senior financial analyst expert at creating comprehensive, professional stock analysis presentations with rich content. Generate detailed slides with both bullet points and paragraph-style content. Return only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=4000,  # Increased for more comprehensive content
                timeout=45.0
            )
            
            # Extract and parse response
            llm_output = response.choices[0].message.content.strip()
            
            # Remove markdown code blocks if present
            if llm_output.startswith("```json"):
                llm_output = llm_output[7:]
            if llm_output.startswith("```"):
                llm_output = llm_output[3:]
            if llm_output.endswith("```"):
                llm_output = llm_output[:-3]
            
            llm_output = llm_output.strip()
            
            # Parse JSON
            slide_structure = json.loads(llm_output)
            
            print(f"✅ Generated {len(slide_structure.get('slides', []))} comprehensive slides (English)")
            
            # NOW TRANSLATE TO HINDI
            print("🌐 Translating content to Hindi...")
            
            for i, slide in enumerate(slide_structure.get('slides', []), 1):
                slide_type = slide.get('type', 'bullets')
                
                # Handle None content by converting to empty list
                content = slide.get('content', [])
                if content is None:
                    content = []
                    slide['content'] = []
                
                # Translate based on slide type
                if slide_type == 'bullets':
                    # Translate bullet points
                    if content:
                        print(f"   Translating slide {i}: {slide.get('title', 'Untitled')} ({len(content)} bullets)")
                        hindi_content = self.translate_to_hindi(content)
                        slide['content_eng'] = content
                        slide['content_hindi'] = hindi_content
                        # Keep 'content' for backward compatibility
                        slide['content'] = content
                    else:
                        slide['content_eng'] = []
                        slide['content_hindi'] = []
                
                elif slide_type == 'paragraph':
                    # Translate paragraph
                    paragraph = slide.get('paragraph', '')
                    if paragraph:
                        print(f"   Translating slide {i}: {slide.get('title', 'Untitled')} (paragraph)")
                        hindi_paragraph = self.translate_to_hindi(paragraph)
                        slide['paragraph_eng'] = paragraph
                        slide['paragraph_hindi'] = hindi_paragraph
                        # Keep 'paragraph' for backward compatibility
                        slide['paragraph'] = paragraph
                    else:
                        slide['paragraph_eng'] = ''
                        slide['paragraph_hindi'] = ''
                
                elif slide_type == 'mixed':
                    # Translate both bullets and paragraph
                    if content:
                        print(f"   Translating slide {i}: {slide.get('title', 'Untitled')} (mixed: {len(content)} bullets + paragraph)")
                        hindi_content = self.translate_to_hindi(content)
                        slide['content_eng'] = content
                        slide['content_hindi'] = hindi_content
                        slide['content'] = content
                    else:
                        slide['content_eng'] = []
                        slide['content_hindi'] = []
                    
                    paragraph = slide.get('paragraph', '')
                    if paragraph:
                        hindi_paragraph = self.translate_to_hindi(paragraph)
                        slide['paragraph_eng'] = paragraph
                        slide['paragraph_hindi'] = hindi_paragraph
                        slide['paragraph'] = paragraph
                    else:
                        slide['paragraph_eng'] = ''
                        slide['paragraph_hindi'] = ''
            
            print(f"✅ Translation complete! All slides now have English + Hindi content")
            
            # Log slide types
            for i, slide in enumerate(slide_structure.get('slides', []), 1):
                slide_type = slide.get('type', 'bullets')
                content_count = len(slide.get('content_eng', []))
                has_paragraph = 'paragraph_eng' in slide and slide.get('paragraph_eng')
                print(f"   Slide {i}: {slide.get('title', 'Untitled')} ({slide_type}) - {content_count} points" + 
                      (f" + paragraph ({len(slide.get('paragraph_eng', ''))} chars)" if has_paragraph else "") +
                      " [EN + HI]")
            
            # Save JSON to PPT_json folder
            try:
                import os
                from datetime import datetime
                
                # Create PPT_json folder if it doesn't exist
                json_folder = "PPT_json"
                if not os.path.exists(json_folder):
                    os.makedirs(json_folder)
                    print(f"📁 Created folder: {json_folder}")
                
                # Generate filename with stock symbol and timestamp
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                stock_symbol_clean = stock_data['stock_symbol'].replace('.', '_')
                json_filename = f"{stock_symbol_clean}_{timestamp}.json"
                json_filepath = os.path.join(json_folder, json_filename)
                
                # Save the complete structure with metadata
                json_data = {
                    "metadata": {
                        "stock_name": stock_data['stock_name'],
                        "stock_symbol": stock_data['stock_symbol'],
                        "generated_at": datetime.now().isoformat(),
                        "selection_status": stock_data['selection'],
                        "current_sentiment": current_sentiment_status,
                        "future_sentiment": future_sentiment_status,
                        "language_support": "bilingual",  # NEW: Indicate bilingual support
                        "languages": ["english", "hindi"]  # NEW: List supported languages
                    },
                    "slide_structure": slide_structure
                }
                
                with open(json_filepath, 'w', encoding='utf-8') as f:
                    json.dump(json_data, f, indent=2, ensure_ascii=False)
                
                print(f"💾 Saved bilingual PPT JSON to: {json_filepath}")
                
            except Exception as save_error:
                print(f"⚠️ Failed to save JSON file: {save_error}")
                # Continue even if save fails
            
            return slide_structure
            
        except json.JSONDecodeError as e:
            print(f"❌ Failed to parse LLM response as JSON: {e}")
            print(f"LLM Output: {llm_output[:500]}...")
            return self._get_fallback_structure(stock_data)
        except Exception as e:
            print(f"❌ Error generating slide structure: {e}")
            import traceback
            traceback.print_exc()
            return self._get_fallback_structure(stock_data)
    
    def _get_fallback_structure(self, stock_data: Dict[str, Any]) -> Dict[str, Any]:
        """Fallback slide structure if LLM fails - with bilingual support"""
        # Safely get sentiment status
        current_status = stock_data['sentiment'].get('current_sentiment_status', 'neutral')
        future_status = stock_data['sentiment'].get('future_sentiment_status', 'neutral')
        
        return {
            "slides": [
                {
                    "title": f"{stock_data['stock_name']} Stock Analysis",
                    "type": "bullets",
                    "content": [
                        f"Symbol: {stock_data['stock_symbol']}",
                        f"Analysis Date: {stock_data.get('analyzed_at', 'N/A')}",
                        "Comprehensive Investment Analysis"
                    ],
                    "content_eng": [
                        f"Symbol: {stock_data['stock_symbol']}",
                        f"Analysis Date: {stock_data.get('analyzed_at', 'N/A')}",
                        "Comprehensive Investment Analysis"
                    ],
                    "content_hindi": [
                        f"Symbol: {stock_data['stock_symbol']}",
                        f"विश्लेषण तिथि: {stock_data.get('analyzed_at', 'N/A')}",
                        "व्यापक निवेश विश्लेषण"
                    ]
                },
                {
                    "title": "Company Overview",
                    "type": "bullets",
                    "content": [
                        f"Company: {stock_data['stock_name']}",
                        f"Ticker: {stock_data['stock_symbol']}",
                        "Detailed fundamental analysis available"
                    ],
                    "content_eng": [
                        f"Company: {stock_data['stock_name']}",
                        f"Ticker: {stock_data['stock_symbol']}",
                        "Detailed fundamental analysis available"
                    ],
                    "content_hindi": [
                        f"कंपनी: {stock_data['stock_name']}",
                        f"Ticker: {stock_data['stock_symbol']}",
                        "विस्तृत मौलिक विश्लेषण उपलब्ध है"
                    ]
                },
                {
                    "title": "Market Sentiment",
                    "type": "bullets",
                    "content": [
                        f"Current Sentiment: {current_status.upper() if current_status else 'NEUTRAL'}",
                        f"Future Outlook: {future_status.upper() if future_status else 'NEUTRAL'}",
                        "Based on comprehensive market analysis"
                    ],
                    "content_eng": [
                        f"Current Sentiment: {current_status.upper() if current_status else 'NEUTRAL'}",
                        f"Future Outlook: {future_status.upper() if future_status else 'NEUTRAL'}",
                        "Based on comprehensive market analysis"
                    ],
                    "content_hindi": [
                        f"वर्तमान भावना: {current_status.upper() if current_status else 'NEUTRAL'}",
                        f"भविष्य का दृष्टिकोण: {future_status.upper() if future_status else 'NEUTRAL'}",
                        "व्यापक बाजार विश्लेषण पर आधारित"
                    ]
                },
                {
                    "title": "Investment Recommendation",
                    "type": "bullets",
                    "content": [
                        f"Selection Status: {'SELECTED' if stock_data['selection'] else 'NOT SELECTED'}",
                        "Review detailed analysis for complete insights",
                        "Consult with financial advisor before investing"
                    ],
                    "content_eng": [
                        f"Selection Status: {'SELECTED' if stock_data['selection'] else 'NOT SELECTED'}",
                        "Review detailed analysis for complete insights",
                        "Consult with financial advisor before investing"
                    ],
                    "content_hindi": [
                        f"चयन स्थिति: {'चयनित' if stock_data['selection'] else 'चयनित नहीं'}",
                        "पूर्ण जानकारी के लिए विस्तृत विश्लेषण देखें",
                        "निवेश से पहले वित्तीय सलाहकार से परामर्श करें"
                    ]
                }
            ]
        }
    
    def create_presentation(self, slide_structure: Dict[str, Any], stock_data: Dict[str, Any], 
                          output_path: str, language: str = "english") -> bool:
        """
        Create PowerPoint presentation from slide structure in specified language
        
        Args:
            slide_structure: Slide structure from LLM
            stock_data: Original stock data
            output_path: Path to save the PPT file
            language: "english" or "hindi"
        
        Returns:
            bool: True if successful
        """
        try:
            print(f"📊 Creating PowerPoint presentation ({language.upper()})...")
            
            # Create presentation
            prs = Presentation()
            
            # Set slide size to widescreen (16:9)
            prs.slide_width = Inches(13.333)
            prs.slide_height = Inches(7.5)
            
            # Process each slide
            for idx, slide_data in enumerate(slide_structure.get('slides', [])):
                slide_type = slide_data.get('type', 'bullets')
                
                if idx == 0:
                    # Title slide
                    self._create_title_slide(prs, slide_data, stock_data, language)
                elif slide_type == 'paragraph':
                    # Paragraph slide
                    self._create_paragraph_slide(prs, slide_data, language)
                elif slide_type == 'mixed':
                    # Mixed slide (bullets + paragraph)
                    self._create_mixed_slide(prs, slide_data, language)
                else:
                    # Standard bullet point slide
                    self._create_content_slide(prs, slide_data, language)
            
            # Save presentation
            prs.save(output_path)
            print(f"✅ {language.upper()} presentation saved: {output_path}")
            return True
            
        except Exception as e:
            print(f"❌ Error creating {language} presentation: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _create_paragraph_slide(self, prs: Presentation, slide_data: Dict[str, Any], language: str = "english"):
        """Create slide with paragraph content in specified language
        
        Args:
            prs: Presentation object
            slide_data: Slide data with content_eng and content_hindi
            language: "english" or "hindi"
        """
        slide_layout = prs.slide_layouts[6]  # Blank layout
        slide = prs.slides.add_slide(slide_layout)
        
        # Add title
        title_box = slide.shapes.add_textbox(
            Inches(0.5), Inches(0.5), Inches(12.333), Inches(0.8)
        )
        title_frame = title_box.text_frame
        title_frame.text = slide_data['title']
        title_para = title_frame.paragraphs[0]
        title_para.font.size = Pt(32)
        title_para.font.bold = True
        title_para.font.color.rgb = RGBColor(0, 51, 102)
        
        # Select content based on language
        if language == "hindi":
            paragraph_text = slide_data.get('paragraph_hindi', slide_data.get('paragraph', ''))
        else:  # english
            paragraph_text = slide_data.get('paragraph_eng', slide_data.get('paragraph', ''))
        
        # Add paragraph content
        if paragraph_text:
            content_box = slide.shapes.add_textbox(
                Inches(0.8), Inches(1.8), Inches(11.733), Inches(5.0)
            )
            content_frame = content_box.text_frame
            content_frame.word_wrap = True
            content_frame.text = paragraph_text
            
            # Format paragraph
            for paragraph in content_frame.paragraphs:
                paragraph.font.size = Pt(16)
                paragraph.line_spacing = 1.5
                paragraph.space_after = Pt(12)
                paragraph.alignment = PP_ALIGN.LEFT
    
    def _create_mixed_slide(self, prs: Presentation, slide_data: Dict[str, Any], language: str = "english"):
        """Create slide with both bullets and paragraph in specified language
        
        Args:
            prs: Presentation object
            slide_data: Slide data with content_eng/content_hindi and paragraph_eng/paragraph_hindi
            language: "english" or "hindi"
        """
        slide_layout = prs.slide_layouts[6]  # Blank layout
        slide = prs.slides.add_slide(slide_layout)
        
        # Add title
        title_box = slide.shapes.add_textbox(
            Inches(0.5), Inches(0.5), Inches(12.333), Inches(0.8)
        )
        title_frame = title_box.text_frame
        title_frame.text = slide_data['title']
        title_para = title_frame.paragraphs[0]
        title_para.font.size = Pt(32)
        title_para.font.bold = True
        title_para.font.color.rgb = RGBColor(0, 51, 102)
        
        # Select content based on language
        if language == "hindi":
            content_to_show = slide_data.get('content_hindi', slide_data.get('content', []))
            paragraph_text = slide_data.get('paragraph_hindi', slide_data.get('paragraph', ''))
        else:  # english
            content_to_show = slide_data.get('content_eng', slide_data.get('content', []))
            paragraph_text = slide_data.get('paragraph_eng', slide_data.get('paragraph', ''))
        
        # Add bullet points (top half)
        bullet_box = slide.shapes.add_textbox(
            Inches(0.8), Inches(1.5), Inches(11.733), Inches(2.5)
        )
        bullet_frame = bullet_box.text_frame
        bullet_frame.word_wrap = True
        
        for i, point in enumerate(content_to_show):
            if i == 0:
                p = bullet_frame.paragraphs[0]
            else:
                p = bullet_frame.add_paragraph()
            
            p.text = point
            p.level = 0
            p.font.size = Pt(16)
            p.space_before = Pt(6)
            p.space_after = Pt(6)
        
        # Add paragraph (bottom half)
        if paragraph_text:
            para_box = slide.shapes.add_textbox(
                Inches(0.8), Inches(4.3), Inches(11.733), Inches(2.7)
            )
            para_frame = para_box.text_frame
            para_frame.word_wrap = True
            para_frame.text = paragraph_text
            
            # Format paragraph
            for paragraph in para_frame.paragraphs:
                paragraph.font.size = Pt(14)
                paragraph.line_spacing = 1.4
                paragraph.space_after = Pt(8)
                paragraph.alignment = PP_ALIGN.LEFT
    
    def _create_title_slide(self, prs: Presentation, slide_data: Dict[str, Any], stock_data: Dict[str, Any], language: str = "english"):
        """Create title slide with custom styling in specified language
        
        Args:
            prs: Presentation object
            slide_data: Slide data
            stock_data: Stock information
            language: "english" or "hindi"
        """
        slide_layout = prs.slide_layouts[6]  # Blank layout
        slide = prs.slides.add_slide(slide_layout)
        
        # Add background color
        background = slide.background
        fill = background.fill
        fill.solid()
        fill.fore_color.rgb = RGBColor(0, 51, 102)  # Dark blue
        
        # Add title
        title_box = slide.shapes.add_textbox(
            Inches(0.5), Inches(2.5), Inches(12.333), Inches(1.5)
        )
        title_frame = title_box.text_frame
        title_frame.text = stock_data.get('stock_name', slide_data['title'])
        title_para = title_frame.paragraphs[0]
        title_para.alignment = PP_ALIGN.CENTER
        title_para.font.size = Pt(44)
        title_para.font.bold = True
        title_para.font.color.rgb = RGBColor(255, 255, 255)

        # Add subtitle
        subtitle_text = f"{stock_data['stock_symbol']} | {datetime.now().strftime('%B %d, %Y')}"
        subtitle_box = slide.shapes.add_textbox(
            Inches(0.5), Inches(4.2), Inches(12.333), Inches(0.8)
        )
        subtitle_frame = subtitle_box.text_frame
        subtitle_frame.text = subtitle_text
        subtitle_para = subtitle_frame.paragraphs[0]
        subtitle_para.alignment = PP_ALIGN.CENTER
        subtitle_para.font.size = Pt(24)
        subtitle_para.font.color.rgb = RGBColor(200, 200, 200)
    
    def _create_content_slide(self, prs: Presentation, slide_data: Dict[str, Any], language: str = "english"):
        """Create content slide with title and bullet points in specified language
        
        Args:
            prs: Presentation object
            slide_data: Slide data with content_eng and content_hindi
            language: "english" or "hindi"
        """
        slide_layout = prs.slide_layouts[6]  # Blank layout for more control
        slide = prs.slides.add_slide(slide_layout)
        
        # Add title
        title_box = slide.shapes.add_textbox(
            Inches(0.5), Inches(0.5), Inches(12.333), Inches(0.8)
        )
        title_frame = title_box.text_frame
        title_frame.text = slide_data['title']
        title_para = title_frame.paragraphs[0]
        title_para.font.size = Pt(32)
        title_para.font.bold = True
        title_para.font.color.rgb = RGBColor(0, 51, 102)
        
        # Select content based on language
        if language == "hindi":
            content_to_show = slide_data.get('content_hindi', slide_data.get('content', []))
        else:  # english
            content_to_show = slide_data.get('content_eng', slide_data.get('content', []))
        
        # Add content with more space for bullets
        content_box = slide.shapes.add_textbox(
            Inches(0.8), Inches(1.5), Inches(11.733), Inches(5.5)
        )
        text_frame = content_box.text_frame
        text_frame.word_wrap = True
        
        # Add bullet points
        for i, point in enumerate(content_to_show):
            if i == 0:
                p = text_frame.paragraphs[0]
            else:
                p = text_frame.add_paragraph()
            
            p.text = point
            p.level = 0
            p.font.size = Pt(16)
            p.space_before = Pt(8)
            p.space_after = Pt(8)
            p.line_spacing = 1.2
    
    def convert_ppt_to_pdf(self, ppt_path: str) -> Optional[str]:
        """
        Convert PowerPoint to PDF
        
        Args:
            ppt_path: Path to the PPT file
        
        Returns:
            str: Path to generated PDF file or None if failed
        """
        try:
            print(f"📄 Converting PPT to PDF...")
            
            # Generate PDF path (same name, different extension)
            pdf_path = ppt_path.replace('.pptx', '.pdf')
            
            # Detect platform and use appropriate conversion method
            system = platform.system()
            
            if system == "Windows":
                # Windows: Use comtypes to convert via PowerPoint COM
                try:
                    import comtypes.client
                    import pythoncom
                    
                    print("🪟 Using Windows PowerPoint COM for conversion...")
                    
                    # Initialize COM for this thread
                    pythoncom.CoInitialize()
                    
                    try:
                        # Initialize PowerPoint
                        powerpoint = comtypes.client.CreateObject("Powerpoint.Application")
                        powerpoint.Visible = 1
                        
                        # Open presentation
                        abs_ppt_path = os.path.abspath(ppt_path)
                        abs_pdf_path = os.path.abspath(pdf_path)
                        
                        presentation = powerpoint.Presentations.Open(abs_ppt_path, WithWindow=False)
                        
                        # Save as PDF (format type 32 = PDF)
                        presentation.SaveAs(abs_pdf_path, 32)
                        
                        # Close presentation and PowerPoint
                        presentation.Close()
                        powerpoint.Quit()
                        
                        print(f"✅ PDF created: {pdf_path}")
                        return pdf_path
                    
                    finally:
                        # Always uninitialize COM
                        pythoncom.CoUninitialize()
                    
                except ImportError as ie:
                    if 'comtypes' in str(ie):
                        print("⚠️ comtypes not installed. Install with: pip install comtypes")
                    elif 'pythoncom' in str(ie):
                        print("⚠️ pywin32 not installed. Install with: pip install pywin32")
                    else:
                        print(f"⚠️ Import error: {ie}")
                    print("⚠️ Skipping PDF conversion")
                    return None
                except Exception as e:
                    print(f"⚠️ Windows COM conversion failed: {e}")
                    print(f"⚠️ Error type: {type(e).__name__}")
                    return None
            
            elif system == "Linux":
                # Linux: Use LibreOffice
                try:
                    print("🐧 Using LibreOffice for conversion...")
                    
                    # Check if LibreOffice is installed
                    result = subprocess.run(
                        ["libreoffice", "--version"],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    
                    if result.returncode != 0:
                        print("⚠️ LibreOffice not found. Install with: sudo apt-get install libreoffice")
                        return None
                    
                    # Convert using LibreOffice headless mode
                    output_dir = os.path.dirname(os.path.abspath(ppt_path))
                    abs_ppt_path = os.path.abspath(ppt_path)
                    
                    result = subprocess.run(
                        [
                            "libreoffice",
                            "--headless",
                            "--convert-to", "pdf",
                            "--outdir", output_dir,
                            abs_ppt_path
                        ],
                        capture_output=True,
                        text=True,
                        timeout=60
                    )
                    
                    if result.returncode == 0 and os.path.exists(pdf_path):
                        print(f"✅ PDF created: {pdf_path}")
                        return pdf_path
                    else:
                        print(f"⚠️ LibreOffice conversion failed: {result.stderr}")
                        return None
                        
                except FileNotFoundError:
                    print("⚠️ LibreOffice not found. Install with: sudo apt-get install libreoffice")
                    return None
                except subprocess.TimeoutExpired:
                    print("⚠️ LibreOffice conversion timed out")
                    return None
                except Exception as e:
                    print(f"⚠️ Linux conversion failed: {e}")
                    return None
            
            elif system == "Darwin":
                # macOS: Use LibreOffice or Keynote
                print("🍎 macOS detected - PDF conversion not implemented yet")
                print("⚠️ Please install LibreOffice for PDF conversion")
                return None
            
            else:
                print(f"⚠️ Unsupported platform: {system}")
                return None
                
        except Exception as e:
            print(f"❌ Error converting PPT to PDF: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def generate_ppt(self, stock_symbol: str, output_dir: str = "downloads") -> Optional[Dict[str, str]]:
        """
        Main method to generate BILINGUAL PPT for a stock (separate English and Hindi files)
        
        Args:
            stock_symbol: Stock ticker symbol
            output_dir: Directory to save the PPT
        
        Returns:
            dict: {
                'ppt_path_en': str, 
                'ppt_path_hi': str,
                'pdf_path_en': str or None,
                'pdf_path_hi': str or None
            } or None if failed
        """
        try:
            print(f"\n{'='*60}")
            print(f"🚀 Starting BILINGUAL PPT generation for {stock_symbol}")
            print(f"{'='*60}\n")
            
            # Step 1: Fetch data from database
            print("📊 Step 1: Fetching stock data from database...")
            stock_data = self.fetch_stock_data(stock_symbol)
            if not stock_data:
                return None
            print(f"✅ Data fetched for {stock_data['stock_name']}")
            
            # Step 2: Generate slide structure using LLM (with bilingual content)
            print("\n🤖 Step 2: Generating bilingual slide structure...")
            slide_structure = self.generate_slide_structure(stock_data)
            if not slide_structure or 'slides' not in slide_structure:
                print("❌ Failed to generate slide structure")
                return None
            
            # Step 3: Create TWO PowerPoint presentations (English and Hindi)
            print("\n📊 Step 3: Creating PowerPoint presentations (English + Hindi)...")
            
            # Create output directory if it doesn't exist
            os.makedirs(output_dir, exist_ok=True)
            
            # Generate filenames with language suffix
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_filename = f"{stock_data['stock_name'].replace(' ', '_')}_{stock_symbol.replace('.', '_')}_{timestamp}"
            
            english_filename = f"{base_filename}_EN.pptx"
            hindi_filename = f"{base_filename}_HI.pptx"
            
            english_path = os.path.join(output_dir, english_filename)
            hindi_path = os.path.join(output_dir, hindi_filename)
            
            # Create English presentation
            print("\n   🇬🇧 Creating English presentation...")
            success_en = self.create_presentation(slide_structure, stock_data, english_path, language="english")
            
            if not success_en:
                print("❌ Failed to create English presentation")
                return None
            
            print(f"   ✅ English PPT created: {english_path}")
            
            # Create Hindi presentation
            print("\n   🇮🇳 Creating Hindi presentation...")
            success_hi = self.create_presentation(slide_structure, stock_data, hindi_path, language="hindi")
            
            if not success_hi:
                print("❌ Failed to create Hindi presentation")
                return None
            
            print(f"   ✅ Hindi PPT created: {hindi_path}")
            
            # Step 4: Convert both to PDF
            print("\n📄 Step 4: Converting to PDF...")
            
            print("   🇬🇧 Converting English PPT to PDF...")
            pdf_path_en = self.convert_ppt_to_pdf(english_path)
            if pdf_path_en:
                print(f"   ✅ English PDF created: {pdf_path_en}")
            else:
                print("   ⚠️ English PDF conversion skipped or failed")
            
            print("   🇮🇳 Converting Hindi PPT to PDF...")
            pdf_path_hi = self.convert_ppt_to_pdf(hindi_path)
            if pdf_path_hi:
                print(f"   ✅ Hindi PDF created: {pdf_path_hi}")
            else:
                print("   ⚠️ Hindi PDF conversion skipped or failed")
            
            print(f"\n{'='*60}")
            print(f"✅ BILINGUAL GENERATION COMPLETE!")
            print(f"📁 English PPT: {english_path}")
            print(f"📁 Hindi PPT: {hindi_path}")
            if pdf_path_en:
                print(f"📁 English PDF: {pdf_path_en}")
            if pdf_path_hi:
                print(f"📁 Hindi PDF: {pdf_path_hi}")
            print(f"{'='*60}\n")
            
            return {
                'ppt_path_en': english_path,
                'ppt_path_hi': hindi_path,
                'pdf_path_en': pdf_path_en,
                'pdf_path_hi': pdf_path_hi
            }
                
        except Exception as e:
            print(f"❌ Error in PPT generation: {e}")
            import traceback
            traceback.print_exc()
            return None


# Example usage
if __name__ == "__main__":
    generator = StockPPTGenerator()
    
    # Test with a stock symbol
    test_symbol = "RELIANCE.NS"
    output_file = generator.generate_ppt(test_symbol)
    
    if output_file:
        print(f"✅ Success! PPT generated: {output_file}")
    else:
        print("❌ Failed to generate PPT")
