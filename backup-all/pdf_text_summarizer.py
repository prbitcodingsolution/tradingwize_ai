#!/usr/bin/env python3
"""
PDF Text Extraction and Summarization Tool

This module downloads stock PDFs from screener.in, extracts all text content,
and generates intelligent summaries using OpenRouter API.
"""

import os
import sys
import time
from typing import Optional, Dict, Any
import requests
from dotenv import load_dotenv

# PDF text extraction libraries
try:
    import PyPDF2
    import pdfplumber
    import fitz  # PyMuPDF
    PDF_LIBRARIES_AVAILABLE = True
except ImportError as e:
    print(f"⚠️ PDF libraries not installed: {e}")
    print("📦 Install with: pip install PyPDF2 pdfplumber PyMuPDF")
    PDF_LIBRARIES_AVAILABLE = False

# Import our PDF download function
try:
    from scrap_pdf_url import download_stock_pdf
except ImportError:
    print("❌ Error: scrap_pdf_url.py not found. Make sure it's in the same directory.")
    sys.exit(1)

# Load environment variables
load_dotenv()

class PDFTextExtractor:
    """Handles PDF text extraction using multiple methods for best results"""
    
    @staticmethod
    def extract_with_pypdf2(pdf_path: str) -> str:
        """Extract text using PyPDF2"""
        try:
            text = ""
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                for page_num in range(len(pdf_reader.pages)):
                    page = pdf_reader.pages[page_num]
                    text += page.extract_text() + "\n"
            return text.strip()
        except Exception as e:
            print(f"⚠️ PyPDF2 extraction failed: {e}")
            return ""
    
    @staticmethod
    def extract_with_pdfplumber(pdf_path: str) -> str:
        """Extract text using pdfplumber (better for tables and complex layouts)"""
        try:
            text = ""
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
            return text.strip()
        except Exception as e:
            print(f"⚠️ pdfplumber extraction failed: {e}")
            return ""
    
    @staticmethod
    def extract_with_pymupdf(pdf_path: str) -> str:
        """Extract text using PyMuPDF (good for complex PDFs)"""
        try:
            text = ""
            pdf_document = fitz.open(pdf_path)
            for page_num in range(pdf_document.page_count):
                page = pdf_document[page_num]
                text += page.get_text() + "\n"
            pdf_document.close()
            return text.strip()
        except Exception as e:
            print(f"⚠️ PyMuPDF extraction failed: {e}")
            return ""
    
    @classmethod
    def extract_text(cls, pdf_path: str) -> str:
        """
        Extract text using multiple methods and return the best result
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            str: Extracted text content
        """
        if not PDF_LIBRARIES_AVAILABLE:
            raise ImportError("PDF extraction libraries not available")
        
        print(f"📄 Extracting text from: {os.path.basename(pdf_path)}")
        
        # Try multiple extraction methods
        methods = [
            ("pdfplumber", cls.extract_with_pdfplumber),
            ("PyMuPDF", cls.extract_with_pymupdf),
            ("PyPDF2", cls.extract_with_pypdf2),
        ]
        
        best_text = ""
        best_length = 0
        
        for method_name, method_func in methods:
            try:
                print(f"🔧 Trying {method_name}...")
                text = method_func(pdf_path)
                
                if text and len(text) > best_length:
                    best_text = text
                    best_length = len(text)
                    print(f"✅ {method_name}: Extracted {len(text):,} characters")
                else:
                    print(f"⚠️ {method_name}: Extracted {len(text):,} characters")
                    
            except Exception as e:
                print(f"❌ {method_name} failed: {e}")
                continue
        
        if not best_text:
            raise ValueError("Failed to extract text using any method")
        
        print(f"🎯 Best extraction: {best_length:,} characters")
        return best_text

class OpenRouterSummarizer:
    """Handles text summarization using OpenRouter API with token tracking"""
    
    def __init__(self):
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY not found in environment variables")
        
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/your-repo",  # Optional
            "X-Title": "PDF Summarizer"  # Optional
        }
        
        # Token tracking
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost = 0.0
        self.api_calls = []
    
    def get_token_stats(self) -> Dict[str, Any]:
        """
        Get comprehensive token usage statistics
        
        Returns:
            dict: Token usage stats including costs
        """
        return {
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
            "total_cost_usd": self.total_cost,
            "api_calls_count": len(self.api_calls),
            "api_calls": self.api_calls
        }
    
    def print_token_stats(self):
        """Print formatted token usage statistics"""
        stats = self.get_token_stats()
        print(f"\n{'='*60}")
        print(f"📊 TOKEN USAGE STATISTICS")
        print(f"{'='*60}")
        print(f"Total API Calls: {stats['api_calls_count']}")
        print(f"Input Tokens:    {stats['total_input_tokens']:,}")
        print(f"Output Tokens:   {stats['total_output_tokens']:,}")
        print(f"Total Tokens:    {stats['total_tokens']:,}")
        print(f"Estimated Cost:  ${stats['total_cost_usd']:.4f} USD")
        print(f"{'='*60}")
        
        if stats['api_calls']:
            print(f"\n📋 Individual API Calls:")
            for i, call in enumerate(stats['api_calls'], 1):
                print(f"  Call {i}: {call['input_tokens']:,} in + {call['output_tokens']:,} out = ${call['cost']:.4f}")
    
    def calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """
        Calculate cost based on model pricing
        
        Pricing per 1M tokens (as of 2024):
        - gpt-3.5-turbo: $0.50 input / $1.50 output
        - gpt-4: $30 input / $60 output
        - gpt-4-turbo: $10 input / $30 output
        - claude-3-sonnet: $3 input / $15 output
        - claude-3-opus: $15 input / $75 output
        """
        pricing = {
            "openai/gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
            "openai/gpt-4": {"input": 30.00, "output": 60.00},
            "openai/gpt-4-turbo": {"input": 10.00, "output": 30.00},
            "anthropic/claude-3-sonnet": {"input": 3.00, "output": 15.00},
            "anthropic/claude-3-opus": {"input": 15.00, "output": 75.00},
            "anthropic/claude-3-haiku": {"input": 0.25, "output": 1.25},
            "openai/gpt-oss-120b": {"input": 1.00, "output": 1.00},
        }
        
        # Get pricing for model (default to gpt-3.5-turbo if not found)
        model_pricing = pricing.get(model, pricing["openai/gpt-3.5-turbo"])
        
        # Calculate cost (pricing is per 1M tokens)
        input_cost = (input_tokens / 1_000_000) * model_pricing["input"]
        output_cost = (output_tokens / 1_000_000) * model_pricing["output"]
        
        return input_cost + output_cost
    
    def _clean_meta_commentary(self, text: str) -> str:
        """
        Remove meta-commentary and debugging text from LLM output
        
        Args:
            text: Raw LLM output
            
        Returns:
            str: Cleaned text without meta-commentary
        """
        import re
        
        # Remove common meta-commentary patterns
        meta_patterns = [
            r'^(Here is|Here\'s|Based on|According to|The following is|This is|I have analyzed|I have created|I will provide|Let me provide).*?summary[:\.]?\s*',
            r'^(Executive Summary|Summary|Analysis)[:\.]?\s*',
            r'^\*\*Executive Summary\*\*[:\.]?\s*',
            r'^\*\*Summary\*\*[:\.]?\s*',
        ]
        
        cleaned = text
        for pattern in meta_patterns:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE | re.MULTILINE)
        
        # Remove any leading/trailing whitespace
        cleaned = cleaned.strip()
        
        return cleaned
    
    def summarize_text(self, text: str, stock_name: str, target_words: int = 550) -> str:
        """
        Summarize text using OpenRouter API
        
        Args:
            text: Text content to summarize
            stock_name: Name of the stock for context
            target_words: Target word count for summary (default: 550)
            
        Returns:
            str: Summarized text
        """
        print(f"🤖 Summarizing text using OpenRouter API...")
        print(f"📊 Input text: {len(text):,} characters")
        
        # Truncate text if too long (most models have token limits)
        max_chars = 50000  # Increased to allow more content
        if len(text) > max_chars:
            print(f"⚠️ Text too long ({len(text):,} chars), truncating to {max_chars:,} chars")
            text = text[:max_chars] + "\n\n[Text truncated due to length...]"
        
        system_prompt = f"""You are a financial analyst expert specializing in quarterly and annual report analysis. 

Your task is to analyze the provided financial document for {stock_name} and create a comprehensive, professional summary.

CRITICAL: Output ONLY the financial summary. Do NOT include any meta-commentary, explanations about your process, or statements like "here is the summary" or "based on the analysis". Start directly with the content.

REQUIREMENTS:
1. Write exactly {target_words} words (500-600 words range)
2. Focus on the most important financial metrics, business performance, and key insights
3. Structure the summary with clear sections covering:
   - Financial Performance (revenue, profit, margins, growth)
   - Business Highlights (key achievements, new initiatives, market position)
   - Financial Health (cash flow, debt, liquidity, ratios)
   - Future Outlook (guidance, plans, risks, opportunities)
4. Use professional financial language appropriate for investors
5. Include specific numbers and percentages where available
6. Highlight both positive developments and concerns/risks
7. Make it actionable for investment decision-making

STYLE:
- Professional and analytical tone
- Clear, concise sentences
- Use bullet points sparingly, prefer flowing paragraphs
- Include context for financial metrics (year-over-year comparisons, industry benchmarks)
- Avoid jargon that general investors wouldn't understand
- NO meta-commentary or process explanations"""

        user_prompt = f"""Analyze this financial document for {stock_name} and provide a comprehensive summary.

DOCUMENT CONTENT:
{text}

Generate a professional {target_words}-word summary focusing on financial performance, business highlights, financial health, and future outlook."""

        payload = {
            "model": "openai/gpt-3.5-turbo",  # Try a simpler, faster model
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.3,  # Lower temperature for more consistent, factual output
            "max_tokens": 2000,  # Increased to ensure complete summaries without cutoff
            "top_p": 0.9
        }
        
        try:
            print("🔄 Sending request to OpenRouter...")
            response = requests.post(
                self.base_url,
                headers=self.headers,
                json=payload,
                timeout=90  # Increased timeout
            )
            
            print(f"📊 API Response Status: {response.status_code}")
            response.raise_for_status()
            data = response.json()
            
            # Extract token usage from response
            usage = data.get('usage', {})
            input_tokens = usage.get('prompt_tokens', 0)
            output_tokens = usage.get('completion_tokens', 0)
            total_tokens = usage.get('total_tokens', input_tokens + output_tokens)
            
            # Calculate cost
            model = payload.get('model', 'openai/gpt-3.5-turbo')
            cost = self.calculate_cost(model, input_tokens, output_tokens)
            
            # Track tokens
            self.total_input_tokens += input_tokens
            self.total_output_tokens += output_tokens
            self.total_cost += cost
            
            # Log this API call
            self.api_calls.append({
                "type": "individual_summary",
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "cost": cost,
                "stock_name": stock_name
            })
            
            # Print token info
            print(f"📊 Tokens Used: {input_tokens:,} input + {output_tokens:,} output = {total_tokens:,} total")
            print(f"💰 Cost: ${cost:.4f} USD")
            
            if 'choices' in data and len(data['choices']) > 0:
                summary = data['choices'][0]['message']['content'].strip()
                
                # Clean up any meta-commentary that might have slipped through
                summary = self._clean_meta_commentary(summary)
                
                word_count = len(summary.split())
                print(f"✅ Summary generated: {word_count} words")
                return summary
            else:
                print(f"❌ No choices in API response: {data}")
                raise ValueError("No summary generated in API response")
                
        except requests.exceptions.Timeout:
            print("❌ API request timed out")
            raise ValueError("API request timed out - try again later")
        except requests.exceptions.RequestException as e:
            print(f"❌ API request failed: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response text: {e.response.text}")
            raise
        except Exception as e:
            print(f"❌ Summarization failed: {e}")
            raise

class PDFSummarizerPipeline:
    """Main pipeline that orchestrates PDF download, text extraction, and summarization"""
    
    def __init__(self):
        self.text_extractor = PDFTextExtractor()
        self.summarizer = OpenRouterSummarizer()
    
    def process_multiple_pdfs(self, stock_name: str, num_pdfs: int = 4, save_dir: str = "pdf_summaries") -> Dict[str, Any]:
        """
        Process multiple PDFs: Generate individual summaries and a main consolidated summary
        WITH CACHING: Checks if summary already exists before processing
        
        Args:
            stock_name: Stock symbol (e.g., "CUPID", "RELIANCE")
            num_pdfs: Number of PDFs to process (default: 4)
            save_dir: Directory to save results
            
        Returns:
            dict: Results including all summaries, file paths, and metadata
        """
        print(f"\n{'='*60}")
        print(f"🚀 Processing {num_pdfs} PDFs for {stock_name}")
        print('='*60)
        
        # Create save directory
        os.makedirs(save_dir, exist_ok=True)
        
        # ===== CACHING LOGIC: Check if summary already exists =====
        print(f"\n🔍 Checking for existing summary in {save_dir}...")
        
        # Look for existing summary files for this stock
        import glob
        pattern = os.path.join(save_dir, f"{stock_name}_complete_summary_*.txt")
        existing_files = glob.glob(pattern)
        
        if existing_files:
            # Sort by timestamp (newest first)
            existing_files.sort(reverse=True)
            latest_file = existing_files[0]
            
            print(f"✅ Found existing summary: {os.path.basename(latest_file)}")
            print(f"📂 Loading cached summary...")
            
            try:
                # Read the existing summary file
                with open(latest_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Extract the main summary from the file
                # The main summary is after "MAIN CONSOLIDATED SUMMARY"
                if "MAIN CONSOLIDATED SUMMARY" in content:
                    main_summary_start = content.find("MAIN CONSOLIDATED SUMMARY")
                    # Skip the header lines
                    main_summary_start = content.find("---", main_summary_start) + 4
                    main_summary = content[main_summary_start:].strip()
                else:
                    # Fallback: use entire content after the header
                    main_summary = content
                
                # Extract individual summaries if available
                individual_summaries = []
                pdf_sections = content.split("PDF ")
                for section in pdf_sections[1:]:  # Skip first split (header)
                    if ":" in section and "---" in section:
                        try:
                            # Extract PDF number and name
                            first_line = section.split('\n')[0]
                            pdf_num = int(first_line.split(':')[0].strip())
                            
                            # Extract summary text (between --- markers)
                            summary_start = section.find("---") + 4
                            summary_end = section.find("===")
                            if summary_end == -1:
                                summary_end = section.find("MAIN CONSOLIDATED")
                            if summary_end == -1:
                                summary_end = len(section)
                            
                            summary_text = section[summary_start:summary_end].strip()
                            
                            if summary_text and len(summary_text) > 100:
                                individual_summaries.append({
                                    "pdf_number": pdf_num,
                                    "summary": summary_text,
                                    "word_count": len(summary_text.split()),
                                    "cached": True
                                })
                        except:
                            continue
                
                # Create result from cached data
                result = {
                    "stock_name": stock_name,
                    "success": True,
                    "pdf_paths": [],  # Not available from cache
                    "individual_summaries": individual_summaries,
                    "main_summary": main_summary,
                    "main_summary_path": os.path.abspath(latest_file),
                    "processing_time": 0,
                    "error": None,
                    "cached": True,
                    "cache_file": latest_file
                }
                
                print(f"✅ Using cached summary!")
                print(f"📊 Main Summary: {len(main_summary.split())} words")
                print(f"📊 Individual Summaries: {len(individual_summaries)}")
                print(f"⚡ Skipped PDF download and processing (saved time!)")
                
                return result
                
            except Exception as e:
                print(f"⚠️ Error reading cached summary: {e}")
                print(f"📥 Will generate new summary...")
        else:
            print(f"❌ No existing summary found")
            print(f"📥 Will download PDFs and generate new summary...")
        
        # ===== NO CACHE: Proceed with full processing =====
        start_time = time.time()
        result = {
            "stock_name": stock_name,
            "success": False,
            "pdf_paths": [],
            "individual_summaries": [],
            "main_summary": None,
            "main_summary_path": None,
            "processing_time": 0,
            "error": None,
            "cached": False
        }
        
        try:
            # Step 1: Download all PDFs
            print(f"\n📥 Step 1: Downloading {num_pdfs} PDFs...")
            pdf_paths = download_stock_pdf(stock_name, num_pdfs=num_pdfs)
            
            if not pdf_paths or len(pdf_paths) == 0:
                raise ValueError("Failed to download PDFs")
            
            result["pdf_paths"] = pdf_paths
            print(f"✅ Downloaded {len(pdf_paths)} PDFs")
            
            # Step 2: Process each PDF individually
            individual_summaries = []
            
            for i, pdf_path in enumerate(pdf_paths, 1):
                print(f"\n{'='*60}")
                print(f"📄 Processing PDF {i}/{len(pdf_paths)}: {os.path.basename(pdf_path)}")
                print('='*60)
                
                try:
                    # Extract text
                    print(f"\n📄 Extracting text from PDF {i}...")
                    text_content = self.text_extractor.extract_text(pdf_path)
                    
                    if not text_content or len(text_content) < 100:
                        print(f"⚠️ Insufficient text in PDF {i}, skipping...")
                        continue
                    
                    print(f"✅ Text extracted: {len(text_content):,} characters")
                    
                    # Generate summary
                    print(f"\n🤖 Generating summary for PDF {i}...")
                    summary = self.summarizer.summarize_text(text_content, stock_name, target_words=550)
                    
                    if summary:
                        individual_summaries.append({
                            "pdf_number": i,
                            "pdf_path": pdf_path,
                            "pdf_name": os.path.basename(pdf_path),
                            "summary": summary,
                            "word_count": len(summary.split()),
                            "text_length": len(text_content)
                        })
                        print(f"✅ Summary {i} generated: {len(summary.split())} words")
                    
                except Exception as e:
                    print(f"❌ Failed to process PDF {i}: {e}")
                    continue
            
            if not individual_summaries:
                raise ValueError("Failed to generate any summaries")
            
            result["individual_summaries"] = individual_summaries
            print(f"\n✅ Generated {len(individual_summaries)} individual summaries")
            
            # Step 3: Generate main consolidated summary
            print(f"\n{'='*60}")
            print(f"🎯 Generating Main Consolidated Summary")
            print('='*60)
            
            main_summary = self.generate_main_summary(stock_name, individual_summaries)
            result["main_summary"] = main_summary
            
            # Step 4: Save all summaries to file
            timestamp = int(time.time())
            output_filename = f"{stock_name}_complete_summary_{timestamp}.txt"
            output_path = os.path.join(save_dir, output_filename)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(f"COMPREHENSIVE FINANCIAL ANALYSIS: {stock_name}\n")
                f.write(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Number of PDFs Analyzed: {len(individual_summaries)}\n")
                
                # Add token usage statistics
                token_stats = self.summarizer.get_token_stats()
                f.write(f"\n{'='*80}\n")
                f.write(f"TOKEN USAGE & COST ANALYSIS\n")
                f.write(f"{'='*80}\n")
                f.write(f"Total API Calls: {token_stats['api_calls_count']}\n")
                f.write(f"Input Tokens: {token_stats['total_input_tokens']:,}\n")
                f.write(f"Output Tokens: {token_stats['total_output_tokens']:,}\n")
                f.write(f"Total Tokens: {token_stats['total_tokens']:,}\n")
                f.write(f"Cost (GPT-3.5-turbo): ${token_stats['total_cost_usd']:.4f} USD\n")
                
                # Add cost estimates for other models
                f.write(f"\nCost Estimates for Other Models:\n")
                total_input = token_stats['total_input_tokens']
                total_output = token_stats['total_output_tokens']
                
                models_pricing = {
                    "GPT-4": (30.00, 60.00),
                    "GPT-4-Turbo": (10.00, 30.00),
                    "Claude-3-Sonnet": (3.00, 15.00),
                    "Claude-3-Opus": (15.00, 75.00),
                    "Claude-3-Haiku": (0.25, 1.25),
                }
                
                for model_name, (input_price, output_price) in models_pricing.items():
                    cost = (total_input / 1_000_000 * input_price) + (total_output / 1_000_000 * output_price)
                    f.write(f"  - {model_name}: ${cost:.4f} USD\n")
                
                f.write(f"\n{'='*80}\n\n")
                
                # Write individual summaries
                for summary_data in individual_summaries:
                    f.write(f"PDF {summary_data['pdf_number']}: {summary_data['pdf_name']}\n")
                    f.write(f"Word Count: {summary_data['word_count']} words\n")
                    f.write(f"{'-'*80}\n")
                    f.write(summary_data['summary'])
                    f.write(f"\n\n{'='*80}\n\n")
                
                # Write main summary
                f.write(f"MAIN CONSOLIDATED SUMMARY\n")
                f.write(f"Word Count: {len(main_summary.split())} words\n")
                f.write(f"{'-'*80}\n")
                f.write(main_summary)
            
            result["main_summary_path"] = os.path.abspath(output_path)
            result["success"] = True
            
            processing_time = time.time() - start_time
            result["processing_time"] = processing_time
            
            # Add token stats to result
            token_stats = self.summarizer.get_token_stats()
            result["token_stats"] = token_stats
            
            print(f"\n✅ COMPLETE PIPELINE FINISHED!")
            print(f"📊 Individual Summaries: {len(individual_summaries)}")
            print(f"📊 Main Summary: {len(main_summary.split())} words")
            print(f"💾 Saved to: {output_path}")
            print(f"⏱️ Total time: {processing_time:.2f} seconds")
            
            # Print comprehensive token statistics
            self.summarizer.print_token_stats()
            
            return result
            
        except Exception as e:
            result["error"] = str(e)
            result["processing_time"] = time.time() - start_time
            print(f"\n❌ PIPELINE FAILED: {e}")
            return result
    
    def generate_main_summary(self, stock_name: str, individual_summaries: list) -> str:
        """
        Generate a main consolidated summary from individual PDF summaries
        
        Args:
            stock_name: Stock symbol
            individual_summaries: List of individual summary dictionaries
            
        Returns:
            str: Main consolidated summary (900-1000 words)
        """
        print(f"🤖 Generating main consolidated summary from {len(individual_summaries)} summaries...")
        
        # Combine all individual summaries
        combined_text = ""
        for i, summary_data in enumerate(individual_summaries, 1):
            combined_text += f"\n\n=== QUARTERLY REPORT {i} ===\n"
            combined_text += summary_data['summary']
        
        system_prompt = f"""You are a senior financial analyst creating an executive summary for {stock_name}.

You have been provided with {len(individual_summaries)} individual quarterly report summaries. Your task is to synthesize these into ONE comprehensive executive summary.

CRITICAL: Output ONLY the executive summary. Do NOT include:
- Meta-commentary about the analysis process
- Statements like "here is the summary" or "based on the analysis"
- Explanations about what you're doing
- Any text that isn't part of the actual summary content
Start directly with the executive summary content.

REQUIREMENTS:
1. Write exactly 900-1000 words
2. Provide a holistic view of the company's performance across all quarters
3. Structure the summary with these sections:
   - Executive Overview (overall performance trend)
   - Financial Performance Analysis (revenue trends, profitability, margins across quarters)
   - Business Development & Strategy (key initiatives, market position, competitive advantages)
   - Financial Health & Stability (cash flow trends, debt management, liquidity)
   - Future Outlook & Investment Perspective (growth trajectory, risks, opportunities)

4. Focus on TRENDS and PATTERNS across the quarters, not just individual quarter details
5. Highlight year-over-year growth, quarter-over-quarter changes, and momentum
6. Include specific metrics and percentages where relevant
7. Provide actionable insights for investment decision-making
8. Balance positive developments with risks and concerns

STYLE:
- Professional, executive-level tone
- Clear narrative flow connecting all quarters
- Use comparative analysis (e.g., "improving trend", "declining margins")
- Avoid repetition - synthesize common themes
- Make it comprehensive yet concise
- NO meta-commentary or process explanations"""

        user_prompt = f"""Analyze the following {len(individual_summaries)} quarterly report summaries for {stock_name} and create a comprehensive 900-1000 word executive summary.

{combined_text}

Generate a professional executive summary that captures the overall performance, trends, and investment outlook across all quarters."""

        payload = {
            "model": "openai/gpt-3.5-turbo",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 3000,  # Increased to ensure complete executive summary without cutoff
            "top_p": 0.9
        }
        
        try:
            print("🔄 Sending request to OpenRouter for main summary...")
            response = requests.post(
                self.summarizer.base_url,
                headers=self.summarizer.headers,
                json=payload,
                timeout=120
            )
            
            print(f"📊 API Response Status: {response.status_code}")
            response.raise_for_status()
            data = response.json()
            
            # Extract token usage from response
            usage = data.get('usage', {})
            input_tokens = usage.get('prompt_tokens', 0)
            output_tokens = usage.get('completion_tokens', 0)
            total_tokens = usage.get('total_tokens', input_tokens + output_tokens)
            
            # Calculate cost
            model = payload.get('model', 'openai/gpt-3.5-turbo')
            cost = self.summarizer.calculate_cost(model, input_tokens, output_tokens)
            
            # Track tokens
            self.summarizer.total_input_tokens += input_tokens
            self.summarizer.total_output_tokens += output_tokens
            self.summarizer.total_cost += cost
            
            # Log this API call
            self.summarizer.api_calls.append({
                "type": "main_summary",
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "cost": cost,
                "stock_name": stock_name
            })
            
            # Print token info
            print(f"📊 Tokens Used: {input_tokens:,} input + {output_tokens:,} output = {total_tokens:,} total")
            print(f"💰 Cost: ${cost:.4f} USD")
            
            if 'choices' in data and len(data['choices']) > 0:
                main_summary = data['choices'][0]['message']['content'].strip()
                
                # Clean up any meta-commentary that might have slipped through
                main_summary = self.summarizer._clean_meta_commentary(main_summary)
                
                word_count = len(main_summary.split())
                print(f"✅ Main summary generated: {word_count} words")
                return main_summary
            else:
                raise ValueError("No main summary generated in API response")
                
        except Exception as e:
            print(f"❌ Main summary generation failed: {e}")
            raise
    
    def process_stock_pdf(self, stock_name: str, save_dir: str = "pdf_summaries") -> Dict[str, Any]:
        """
        Complete pipeline: Download PDF, extract text, and generate summary
        
        Args:
            stock_name: Stock symbol (e.g., "CUPID", "RELIANCE")
            save_dir: Directory to save results
            
        Returns:
            dict: Results including summary, file paths, and metadata
        """
        print(f"\n{'='*60}")
        print(f"🚀 Processing {stock_name} PDF Summary Pipeline")
        print('='*60)
        
        # Create save directory
        os.makedirs(save_dir, exist_ok=True)
        
        start_time = time.time()
        result = {
            "stock_name": stock_name,
            "success": False,
            "pdf_path": None,
            "text_length": 0,
            "summary": None,
            "summary_path": None,
            "processing_time": 0,
            "error": None
        }
        
        try:
            # Step 1: Download PDF
            print("\n📥 Step 1: Downloading PDF...")
            pdf_path = download_stock_pdf(stock_name)
            
            if not pdf_path:
                raise ValueError("Failed to download PDF")
            
            result["pdf_path"] = pdf_path
            print(f"✅ PDF downloaded: {os.path.basename(pdf_path)}")
            
            # Step 2: Extract text
            print("\n📄 Step 2: Extracting text from PDF...")
            text_content = self.text_extractor.extract_text(pdf_path)
            
            if not text_content or len(text_content) < 100:
                raise ValueError("Insufficient text extracted from PDF")
            
            result["text_length"] = len(text_content)
            print(f"✅ Text extracted: {len(text_content):,} characters")
            
            # Step 3: Generate summary
            print("\n🤖 Step 3: Generating AI summary...")
            summary = self.summarizer.summarize_text(text_content, stock_name)
            
            if not summary:
                raise ValueError("Failed to generate summary")
            
            result["summary"] = summary
            
            # Step 4: Save summary to file
            summary_filename = f"{stock_name}_summary_{int(time.time())}.txt"
            summary_path = os.path.join(save_dir, summary_filename)
            
            with open(summary_path, 'w', encoding='utf-8') as f:
                f.write(f"FINANCIAL SUMMARY: {stock_name}\n")
                f.write(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Source PDF: {os.path.basename(pdf_path)}\n")
                f.write(f"Text Length: {len(text_content):,} characters\n")
                f.write(f"Summary Length: {len(summary.split())} words\n")
                f.write("\n" + "="*80 + "\n\n")
                f.write(summary)
            
            result["summary_path"] = os.path.abspath(summary_path)
            result["success"] = True
            
            processing_time = time.time() - start_time
            result["processing_time"] = processing_time
            
            print(f"\n✅ PIPELINE COMPLETED SUCCESSFULLY!")
            print(f"📊 Summary: {len(summary.split())} words")
            print(f"💾 Saved to: {summary_path}")
            print(f"⏱️ Total time: {processing_time:.2f} seconds")
            
            return result
            
        except Exception as e:
            result["error"] = str(e)
            result["processing_time"] = time.time() - start_time
            print(f"\n❌ PIPELINE FAILED: {e}")
            return result

def main():
    """Example usage of the PDF summarization pipeline"""
    
    print("📄 PDF Text Summarization Pipeline - Multiple PDFs")
    print("=" * 60)
    
    # Check if PDF libraries are available
    if not PDF_LIBRARIES_AVAILABLE:
        print("\n❌ Required PDF libraries not installed!")
        print("📦 Please install with:")
        print("   pip install PyPDF2 pdfplumber PyMuPDF")
        return
    
    # Check if OpenRouter API key is available
    if not os.getenv("OPENROUTER_API_KEY"):
        print("\n❌ OPENROUTER_API_KEY not found in environment variables!")
        print("🔑 Please add your OpenRouter API key to .env file:")
        print("   OPENROUTER_API_KEY=your_api_key_here")
        return
    
    # Initialize pipeline
    pipeline = PDFSummarizerPipeline()
    
    # Test with a stock - process 4 PDFs
    test_stock = "CUPID"
    
    print(f"\n🎯 Processing {test_stock} - Downloading and summarizing 4 quarterly PDFs")
    print("=" * 60)
    
    result = pipeline.process_multiple_pdfs(test_stock, num_pdfs=4)
    
    if result["success"]:
        print(f"\n🎉 SUCCESS for {test_stock}!")
        print(f"\n📊 RESULTS:")
        print(f"  - PDFs Processed: {len(result['individual_summaries'])}")
        print(f"  - Output File: {result['main_summary_path']}")
        print(f"  - Processing Time: {result['processing_time']:.2f}s")
        
        print(f"\n📋 Individual Summaries:")
        for summary_data in result['individual_summaries']:
            print(f"  PDF {summary_data['pdf_number']}: {summary_data['word_count']} words - {summary_data['pdf_name']}")
        
        print(f"\n📋 Main Summary: {len(result['main_summary'].split())} words")
        
        # Display token statistics
        if 'token_stats' in result:
            stats = result['token_stats']
            print(f"\n💰 COST ANALYSIS:")
            print(f"  - Total Tokens: {stats['total_tokens']:,}")
            print(f"  - Input Tokens: {stats['total_input_tokens']:,}")
            print(f"  - Output Tokens: {stats['total_output_tokens']:,}")
            print(f"  - Total Cost (GPT-3.5-turbo): ${stats['total_cost_usd']:.4f}")
            
            # Show cost estimates for other models
            print(f"\n💡 Cost Estimates for Other Models:")
            total_input = stats['total_input_tokens']
            total_output = stats['total_output_tokens']
            
            models_pricing = {
                "GPT-4": (30.00, 60.00),
                "GPT-4-Turbo": (10.00, 30.00),
                "Claude-3-Sonnet": (3.00, 15.00),
                "Claude-3-Opus": (15.00, 75.00),
                "Claude-3-Haiku": (0.25, 1.25),
            }
            
            for model_name, (input_price, output_price) in models_pricing.items():
                cost = (total_input / 1_000_000 * input_price) + (total_output / 1_000_000 * output_price)
                print(f"  - {model_name}: ${cost:.4f}")
        
        # Display preview of main summary
        if result["main_summary"]:
            preview = result["main_summary"][:300] + "..." if len(result["main_summary"]) > 300 else result["main_summary"]
            print(f"\n📖 Main Summary Preview:\n{preview}")
    else:
        print(f"\n❌ FAILED for {test_stock}: {result['error']}")
    
    print("\n🏁 Pipeline testing complete!")

if __name__ == "__main__":
    main()