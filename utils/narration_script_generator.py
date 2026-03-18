"""
Slide Narration Script Generator - BILINGUAL (English + Hindi)
Converts PPT JSON slides into conversational broker-style narration scripts
for voice and AI avatar video generation
"""

import json
import os
from typing import Dict, List, Optional
from datetime import datetime
from dotenv import load_dotenv
from .model_config import get_client

load_dotenv()


class NarrationScriptGenerator:
    """
    Generate conversational narration scripts for PPT slides
    NOW WITH BILINGUAL SUPPORT (English + Hindi)
    Perfect for voice-over and AI avatar video generation
    """
    
    def __init__(self):
        self.client = get_client()
    
    def translate_narration_to_hindi(self, english_script: str) -> str:
        """
        Translate English narration script to natural Hindi
        
        Args:
            english_script: English narration text
            
        Returns:
            Hindi narration text (conversational, voice-friendly)
        """
        try:
            prompt = f"""Translate the following financial slide narration into MODERN HINGLISH (Hindi-English mix) suitable for investor presentation voiceover.

CRITICAL: Use HINGLISH - the way modern Indians actually speak! Mix common English words naturally into Hindi sentences.

HINGLISH STYLE RULES:
1. Keep common English business words in English: company, market, business, growth, revenue, profit, services, platform, customers, industry, sector, innovation, technology, digital, global, etc.
2. Keep modern terms in English: CEO, IT, portfolio, Fortune 500, financial year, etc.
3. Use Hindi for: connecting words, verbs, adjectives, and sentence structure
4. Sound natural - like a modern Indian business professional speaking

EXAMPLE HINGLISH:
❌ Pure Hindi: "हमारी कंपनी सूचना प्रौद्योगिकी सेवाओं के क्षेत्र में एक वैश्विक नेता बन गई है"
✅ Hinglish: "हमारी company information technology services के field में एक global leader बन गई है"

❌ Pure Hindi: "हमारे पास एक विविध पोर्टफोलियो है"
✅ Hinglish: "हमारे पास एक diverse portfolio है"

DO NOT TRANSLATE:
1. Stock tickers (RELIANCE.NS, TCS.NS, CUPID.NS)
2. Financial abbreviations (EBITDA, CAGR, EPS, PE, ROE, ROI)
3. Currency symbols (₹, $, Cr, crore, billion)
4. Numbers and percentages
5. Brand names (Sharks, Domino's, etc.)
6. Common English business words (company, market, business, growth, revenue, profit, services, customers, industry, platform, technology, digital, global, CEO, IT, portfolio, Fortune 500, financial year, innovation, sector, etc.)

VOICE-FRIENDLY REQUIREMENTS:
- Keep sentences short and natural
- Use commas for natural pauses
- Easy to pronounce
- Smooth transitions
- Natural speaking rhythm like modern Indians speak

English narration:
{english_script}

Return ONLY the Hinglish translation, no additional text or formatting."""

            response = self.client.chat.completions.create(
                model="openai/gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a professional translator specializing in financial content for voiceover and video narration. Translate English to MODERN HINGLISH (Hindi-English mix) - the way modern Indians actually speak in business settings. Keep common English business words in English and use Hindi for connecting words and sentence structure. Make it voice-friendly and suitable for AI avatar lip-sync."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.3,
                max_tokens=500
            )
            
            hindi_script = response.choices[0].message.content.strip()
            
            # Clean up any markdown or formatting
            hindi_script = hindi_script.replace('**', '').replace('*', '').replace('#', '')
            
            return hindi_script
            
        except Exception as e:
            print(f"   ⚠️ Hindi translation error: {e}. Using English as fallback.")
            return english_script  # Fallback to English
    
    def generate_script_for_slide(self, slide: Dict, slide_number: int, total_slides: int, 
                                  stock_name: str, stock_symbol: str) -> Dict[str, str]:
        """
        Generate conversational narration script for a single slide (BILINGUAL)
        
        Args:
            slide: Slide data (title, type, content, paragraph)
            slide_number: Current slide number (1-indexed)
            total_slides: Total number of slides
            stock_name: Company name for context
            stock_symbol: Stock ticker for context
            
        Returns:
            Dict with 'script_eng' and 'script_hindi' keys
        """
        slide_type = slide.get('type', 'bullets')
        title = slide.get('title', '')
        
        # Use English content for script generation
        content = slide.get('content_eng', slide.get('content', []))
        paragraph = slide.get('paragraph_eng', slide.get('paragraph', ''))
        
        # Build context-aware prompt based on slide type
        if slide_type == 'bullets':
            prompt = self._build_bullet_slide_prompt(title, content, slide_number, total_slides, stock_name)
        elif slide_type == 'paragraph':
            prompt = self._build_paragraph_slide_prompt(title, paragraph, slide_number, total_slides, stock_name)
        elif slide_type == 'mixed':
            prompt = self._build_mixed_slide_prompt(title, content, paragraph, slide_number, total_slides, stock_name)
        else:
            prompt = self._build_bullet_slide_prompt(title, content, slide_number, total_slides, stock_name)
        
        try:
            print(f"   🎤 Generating English narration for slide {slide_number}: {title}")
            
            response = self.client.chat.completions.create(
                model="openai/gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": """You are a confident CEO pitching your company to Sharks on Shark Tank India.
Generate compelling narration scripts that sound like a CEO presenting their business opportunity to investors.

SHARK TANK CEO PITCH STYLE:
- Speak as the CEO/leader of the company (first-person: "we", "our company")
- Open with "Hello Sharks!" or similar attention-grabber
- Introduce the company with pride and confidence
- Paint a vivid picture of the business and market opportunity
- Use specific numbers and scale to impress (stores, cities, customers)
- Highlight competitive advantages and market position
- Show passion and belief in the business
- Create excitement about the growth potential
- 60-120 words per slide (15-20 seconds when spoken)

REFERENCE EXAMPLE:
"Hello Sharks! I am the CEO of Jubilant FoodWorks Limited, the franchise master behind India's largest quick-service brands—Domino's Pizza and Dunkin' Donuts. We operate in the consumer-cyclical arena, a space that accelerates with rising disposable incomes and rapid urbanisation, and today we power more than 2,300 stores in 800 cities, feeding a hungry, on-the-go nation."

KEY ELEMENTS:
- Direct address to Sharks
- CEO identity and authority
- Company positioning and scale
- Market context and opportunity
- Impressive numbers (stores, cities, customers)
- Vivid, memorable language
- Confident, passionate delivery

VOICE-FRIENDLY REQUIREMENTS:
- No markdown, no symbols, no special characters
- Use commas for natural pauses
- Numbers should be easy to say (e.g., "2,300 stores" or "294 crore")
- Smooth transitions between points
- Natural speaking rhythm
- Em-dashes for dramatic pauses

TONE:
- Confident but not arrogant
- Passionate about the business
- Proud of achievements
- Excited about future potential
- Speaking directly to investors as equals

Return ONLY the narration script text, no formatting."""
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.8,
                max_tokens=350
            )
            
            script_eng = response.choices[0].message.content.strip()
            
            # Clean up any markdown or formatting
            script_eng = script_eng.replace('**', '').replace('*', '').replace('#', '')
            script_eng = script_eng.replace('₹', 'rupees ')
            script_eng = script_eng.replace('%', ' percent')
            script_eng = script_eng.replace('Cr', ' crore')
            
            print(f"   ✅ Generated English script: {len(script_eng.split())} words")
            
            # NOW TRANSLATE TO HINDI
            print(f"   🌐 Translating to Hindi...")
            script_hindi = self.translate_narration_to_hindi(script_eng)
            print(f"   ✅ Generated Hindi script: {len(script_hindi.split())} words")
            
            return {
                'script_eng': script_eng,
                'script_hindi': script_hindi
            }
            
        except Exception as e:
            print(f"   ❌ Error generating script for slide {slide_number}: {e}")
            # Fallback script
            fallback_eng = f"Let's look at {title}. This slide covers important information about {stock_name}."
            return {
                'script_eng': fallback_eng,
                'script_hindi': fallback_eng  # Use English as fallback
            }
    
    def _build_bullet_slide_prompt(self, title: str, content: List[str], 
                                   slide_number: int, total_slides: int, stock_name: str) -> str:
        """Build CEO-style Shark Tank pitch prompt for bullet point slides"""
        
        # Add CEO-style openings based on slide number
        if slide_number == 1:
            # First slide: Full introduction
            opening_instruction = f"""CRITICAL: This is SLIDE 1 - Start with the FULL CEO introduction:
"Hello Sharks! I am the CEO of {stock_name}, and [continue with the pitch]"

This is your OPENING pitch - introduce yourself and the company with confidence and pride.
ONLY use this full introduction on SLIDE 1."""
        else:
            # Subsequent slides: Natural conversational flow
            opening_instruction = f"""CRITICAL: This is SLIDE {slide_number} (NOT the first slide) - Start naturally and conversationally.

DO NOT use "Hello Sharks! I am the CEO of {stock_name}..." - that was ONLY for slide 1.
DO NOT start every slide with "Sharks," - use it sparingly and conversationally.

NATURAL CONVERSATIONAL OPENINGS (use variety):
✅ "Our financial performance demonstrates..."
✅ "Let me walk you through our market position..."
✅ "Now, looking at our competitive advantages..."
✅ "So Sharks, here's what makes us different..."
✅ "The numbers speak for themselves..."
✅ "What's exciting about our growth is..."
✅ "Here's the opportunity we're capturing..."

Use "Sharks" ONLY when it feels natural in conversation (like "So Sharks, now..." or "Sharks, let me show you...").
Most slides should flow naturally WITHOUT starting with "Sharks,"

Keep it conversational and engaging - like a CEO presenting to investors naturally."""
        
        bullets_text = "\n".join([f"- {item}" for item in content])
        
        return f"""Create a Shark Tank CEO pitch for this slide about {stock_name}.

SLIDE {slide_number} of {total_slides}: {title}

{opening_instruction}

Key points to present:
{bullets_text}

Generate a CEO-style pitch that:
1. Speaks as the CEO/leader (use "we", "our company", "our business")
2. {"Uses the FULL CEO introduction (this is slide 1)" if slide_number == 1 else "Starts naturally and conversationally (use 'Sharks' sparingly, only when it feels natural)"}
3. Presents each point with pride and confidence
4. Uses specific numbers and scale to impress
5. Shows passion and belief in the business
6. Paints a vivid picture of the opportunity
7. 60-120 words total
8. Sounds like a CEO pitching to Sharks on Shark Tank India

{"CORRECT EXAMPLE FOR SLIDE 1:" if slide_number == 1 else f"CORRECT EXAMPLE FOR SLIDE {slide_number} (natural, conversational):"}
{"'Hello Sharks! I am the CEO of Jubilant FoodWorks Limited, the franchise master behind India's largest quick-service brands—Domino's Pizza and Dunkin' Donuts. We operate in the consumer-cyclical arena, a space that accelerates with rising disposable incomes and rapid urbanisation, and today we power more than 2,300 stores in 800 cities, feeding a hungry, on-the-go nation.'" if slide_number == 1 else "'Our financial performance demonstrates remarkable growth and market dominance. We've achieved a 35 percent revenue increase year-over-year, driven by strategic expansion into tier-2 and tier-3 cities where competition is minimal and demand is surging. So Sharks, the numbers tell an incredible story of untapped potential.'"}

Generate CEO pitch:"""
    
    def _build_paragraph_slide_prompt(self, title: str, paragraph: str, 
                                     slide_number: int, total_slides: int, stock_name: str) -> str:
        """Build CEO-style Shark Tank pitch prompt for paragraph slides"""
        
        # Add opening instruction based on slide number
        if slide_number == 1:
            opening_instruction = f"""CRITICAL: This is SLIDE 1 - Start with the FULL CEO introduction:
"Hello Sharks! I am the CEO of {stock_name}, and [continue with the pitch]"

This is your OPENING pitch - introduce yourself and the company.
ONLY use this full introduction on SLIDE 1."""
        else:
            opening_instruction = f"""CRITICAL: This is SLIDE {slide_number} (NOT the first slide) - Start naturally and conversationally.

DO NOT use "Hello Sharks! I am the CEO of {stock_name}..." - that was ONLY for slide 1.
DO NOT start every slide with "Sharks," - use it sparingly and conversationally.

NATURAL CONVERSATIONAL OPENINGS (use variety):
✅ "Let me walk you through our executive summary..."
✅ "Our company overview reveals..."
✅ "Now, looking at the market dynamics..."
✅ "So Sharks, here's what's exciting..."
✅ "The data shows a compelling story..."
✅ "What sets us apart is..."

Use "Sharks" ONLY when it feels natural in conversation (like "So Sharks, now..." or "Sharks, let me show you...").
Most slides should flow naturally WITHOUT starting with "Sharks,"

Keep it conversational and engaging - like a CEO presenting naturally."""
        
        return f"""Convert this analysis into a CEO-style Shark Tank pitch for {stock_name}.

SLIDE {slide_number} of {total_slides}: {title}

{opening_instruction}

Content to present:
{paragraph[:500]}

Generate a CEO-style pitch that:
1. Speaks as the CEO/leader (use "we", "our", "our company")
2. {"Uses the FULL CEO introduction (this is slide 1)" if slide_number == 1 else "Starts naturally and conversationally (use 'Sharks' sparingly, only when it feels natural)"}
3. Presents the information with confidence and pride
4. Uses vivid, memorable language
5. Shows passion for the business
6. Highlights the opportunity and potential
7. 60-120 words (concise and powerful)
8. Sounds like a CEO presenting to Sharks on Shark Tank India

Generate CEO pitch:"""
    
    def _build_mixed_slide_prompt(self, title: str, content: List[str], paragraph: str,
                                  slide_number: int, total_slides: int, stock_name: str) -> str:
        """Build CEO-style Shark Tank pitch prompt for mixed slides (bullets + paragraph)"""
        
        # Add opening instruction based on slide number
        if slide_number == 1:
            opening_instruction = f"""CRITICAL: This is SLIDE 1 - Start with the FULL CEO introduction:
"Hello Sharks! I am the CEO of {stock_name}, and [continue with the pitch]"

This is your OPENING pitch - introduce yourself and the company.
ONLY use this full introduction on SLIDE 1."""
        else:
            opening_instruction = f"""CRITICAL: This is SLIDE {slide_number} (NOT the first slide) - Start naturally and conversationally.

DO NOT use "Hello Sharks! I am the CEO of {stock_name}..." - that was ONLY for slide 1.
DO NOT start every slide with "Sharks," - use it sparingly and conversationally.

NATURAL CONVERSATIONAL OPENINGS (use variety):
✅ "Our company overview demonstrates..."
✅ "Let me share our market position..."
✅ "Now, here's what makes this opportunity unique..."
✅ "So Sharks, the numbers tell an incredible story..."
✅ "Looking at our competitive landscape..."
✅ "What's remarkable about our business is..."

Use "Sharks" ONLY when it feels natural in conversation (like "So Sharks, now..." or "Sharks, let me show you...").
Most slides should flow naturally WITHOUT starting with "Sharks,"

Keep it conversational and engaging - like a CEO presenting naturally."""
        
        bullets_text = "\n".join([f"- {item}" for item in content])
        
        return f"""Create a CEO-style Shark Tank pitch combining these elements for {stock_name}.

SLIDE {slide_number} of {total_slides}: {title}

{opening_instruction}

Key points:
{bullets_text}

Additional context:
{paragraph[:300]}

Generate a unified CEO-style pitch that:
1. Speaks as the CEO/leader (use "we", "our company", "our business")
2. {"Uses the FULL CEO introduction (this is slide 1)" if slide_number == 1 else "Starts naturally and conversationally (use 'Sharks' sparingly, only when it feels natural)"}
3. Weaves all points into a compelling business story
4. Uses confident, passionate language
5. Highlights scale, achievements, and potential
6. Shows pride in the business
7. 60-120 words total
8. Sounds like a CEO presenting to Sharks on Shark Tank India

The pitch should flow as one powerful, cohesive CEO presentation.

Generate CEO pitch:"""
    
    def generate_scripts_for_ppt(self, json_path: str) -> Optional[str]:
        """
        Generate narration scripts for all slides in a PPT JSON file (BILINGUAL)
        
        Args:
            json_path: Path to PPT JSON file (e.g., "PPT_json/CUPID_NS_20260218_183407.json")
            
        Returns:
            Path to output JSON file with bilingual scripts, or None if failed
        """
        try:
            print(f"\n{'='*60}")
            print(f"🎤 Starting BILINGUAL Narration Script Generation")
            print(f"{'='*60}\n")
            
            # Load input JSON
            print(f"📂 Loading: {json_path}")
            with open(json_path, 'r', encoding='utf-8') as f:
                ppt_data = json.load(f)
            
            # Extract metadata
            metadata = ppt_data.get('metadata', {})
            stock_name = metadata.get('stock_name', 'Unknown')
            stock_symbol = metadata.get('stock_symbol', 'Unknown')
            
            print(f"✅ Loaded PPT for {stock_name} ({stock_symbol})")
            
            # Get slides
            slides = ppt_data.get('slide_structure', {}).get('slides', [])
            total_slides = len(slides)
            
            if not slides:
                print("❌ No slides found in JSON")
                return None
            
            print(f"📊 Processing {total_slides} slides (English + Hindi)...\n")
            
            # Generate scripts for each slide
            for i, slide in enumerate(slides, 1):
                scripts = self.generate_script_for_slide(
                    slide=slide,
                    slide_number=i,
                    total_slides=total_slides,
                    stock_name=stock_name,
                    stock_symbol=stock_symbol
                )
                
                # Add slide number (if not already present)
                if 'slide_number' not in slide:
                    slide['slide_number'] = i
                
                # Add bilingual script fields to slide
                slide['script_eng'] = scripts['script_eng']
                slide['script_hindi'] = scripts['script_hindi']
                
                # Keep 'script' for backward compatibility (English)
                slide['script'] = scripts['script_eng']
                
                # Add estimated duration (assuming 150 words per minute speaking rate)
                word_count_eng = len(scripts['script_eng'].split())
                word_count_hindi = len(scripts['script_hindi'].split())
                duration_seconds_eng = round((word_count_eng / 150) * 60, 1)
                duration_seconds_hindi = round((word_count_hindi / 150) * 60, 1)
                
                slide['script_duration_seconds_eng'] = duration_seconds_eng
                slide['script_duration_seconds_hindi'] = duration_seconds_hindi
                slide['script_duration_seconds'] = duration_seconds_eng  # Backward compatibility
                
                slide['script_word_count_eng'] = word_count_eng
                slide['script_word_count_hindi'] = word_count_hindi
                slide['script_word_count'] = word_count_eng  # Backward compatibility
            
            # Generate output filename and save to dedicated folder
            input_filename = os.path.basename(json_path)
            output_filename = input_filename.replace('.json', '_script.json')
            
            # Create generated_ai_scripts folder if it doesn't exist
            output_dir = 'generated_ai_scripts'
            os.makedirs(output_dir, exist_ok=True)
            
            output_path = os.path.join(output_dir, output_filename)
            
            # Update metadata to indicate bilingual support
            if 'metadata' in ppt_data:
                ppt_data['metadata']['narration_support'] = 'bilingual'
                ppt_data['metadata']['narration_languages'] = ['english', 'hindi']
            
            # Save output JSON
            print(f"\n💾 Saving bilingual scripts to: {output_path}")
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(ppt_data, f, indent=2, ensure_ascii=False)
            
            # Calculate total duration
            total_duration_eng = sum(slide.get('script_duration_seconds_eng', 0) for slide in slides)
            total_duration_hindi = sum(slide.get('script_duration_seconds_hindi', 0) for slide in slides)
            total_words_eng = sum(slide.get('script_word_count_eng', 0) for slide in slides)
            total_words_hindi = sum(slide.get('script_word_count_hindi', 0) for slide in slides)
            
            print(f"\n{'='*60}")
            print(f"✅ BILINGUAL NARRATION SCRIPT GENERATION COMPLETE!")
            print(f"{'='*60}")
            print(f"📊 Statistics:")
            print(f"   - Total slides: {total_slides}")
            print(f"   - English: {total_words_eng} words, {total_duration_eng:.1f} seconds ({total_duration_eng/60:.1f} minutes)")
            print(f"   - Hindi: {total_words_hindi} words, {total_duration_hindi:.1f} seconds ({total_duration_hindi/60:.1f} minutes)")
            print(f"   - Average per slide (English): {total_words_eng/total_slides:.0f} words, {total_duration_eng/total_slides:.1f} seconds")
            print(f"   - Average per slide (Hindi): {total_words_hindi/total_slides:.0f} words, {total_duration_hindi/total_slides:.1f} seconds")
            print(f"📁 Output: {output_path}")
            print(f"🌐 Languages: English + Hindi")
            print(f"{'='*60}\n")
            
            return output_path
            
        except FileNotFoundError:
            print(f"❌ File not found: {json_path}")
            return None
        except json.JSONDecodeError:
            print(f"❌ Invalid JSON file: {json_path}")
            return None
        except Exception as e:
            print(f"❌ Error generating scripts: {e}")
            import traceback
            traceback.print_exc()
            return None


# CLI interface for testing
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python narration_script_generator.py <path_to_ppt_json>")
        print("Example: python narration_script_generator.py PPT_json/CUPID_NS_20260218_183407.json")
        sys.exit(1)
    
    json_path = sys.argv[1]
    
    generator = NarrationScriptGenerator()
    output_path = generator.generate_scripts_for_ppt(json_path)
    
    if output_path:
        print(f"✅ Success! Scripts saved to: {output_path}")
    else:
        print(f"❌ Failed to generate scripts")
        sys.exit(1)
