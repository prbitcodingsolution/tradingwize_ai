"""
Stock News Analyzer Tool
Searches for stock news using Tavily API from specific domains,
extracts content, and provides sentiment analysis with LLM.
"""

import os
import requests
import time
from typing import Dict, List, Optional, Tuple
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from datetime import datetime
import json
from .model_config import get_client
from api_logger import api_logger

load_dotenv()

# Specific domains for stock news search
STOCK_NEWS_DOMAINS = [
    "simplywall.st",
    "financialexpress.com",
    "economictimes.indiatimes.com",
    "kotakneo.com",
    "reuters.com",
    "investing.com",
    "forecaster.biz",
    "tipranks.com",
    "morningstar.in",
    "stockanalysis.com",
    "koyfin.com",
    "in.tradingview.com", 
]


class StockNewsAnalyzer:
    """Analyzes stock news using Tavily search and LLM-based sentiment analysis"""
    
    def __init__(self):
        self.tavily_api_key = os.getenv("TAVILY_API_KEY")
        self.client = get_client()
        
    def search_stock_news(
        self, 
        stock_name: str, 
        max_results: int = 10
    ) -> Tuple[List[Dict], str]:
        """
        Search for stock news using Tavily API with specific domains
        
        Args:
            stock_name: Name or ticker of the stock
            max_results: Maximum number of results to return
            
        Returns:
            Tuple of (results_list, answer_string)
        """
        start_time = time.time()
        
        try:
            # Construct search query for future outlook
            query = f"{stock_name} stock future forecast analyst outlook price target 2026"
            
            url = "https://api.tavily.com/search"
            headers = {"Content-Type": "application/json; charset=utf-8"}
            
            payload = {
                "api_key": self.tavily_api_key,
                "query": query,
                "search_depth": "advanced",
                "max_results": max_results,
                "include_answer": True,
                "include_domains": STOCK_NEWS_DOMAINS
            }
            
            request_size = len(json.dumps(payload).encode('utf-8'))
            
            print(f"🔍 Searching Tavily for: {query}")
            print(f"📍 Domains: {', '.join(STOCK_NEWS_DOMAINS[:3])}...")
            
            response = requests.post(url, json=payload, headers=headers, timeout=20)
            response.encoding = 'utf-8'
            
            response_size = len(response.content)
            
            if response.status_code == 200:
                data = response.json()
                results = data.get('results', [])
                answer = data.get('answer', '')
                
                # Clean answer
                if answer:
                    answer = answer.encode('ascii', 'ignore').decode('ascii')
                
                # Log successful request
                api_logger.log_request(
                    api_name='tavily',
                    endpoint='/search',
                    method='POST',
                    response_status=response.status_code,
                    response_time=time.time() - start_time,
                    request_size=request_size,
                    response_size=response_size
                )
                
                print(f"✅ Found {len(results)} articles")
                return results, answer
            else:
                error = f"HTTP {response.status_code}: {response.text[:200]}"
                raise Exception(error)
                
        except Exception as e:
            api_logger.log_request(
                api_name='tavily',
                endpoint='/search',
                method='POST',
                response_status=getattr(response, 'status_code', None),
                response_time=time.time() - start_time,
                error=str(e)
            )
            print(f"❌ Tavily search error: {e}")
            return [], ''
    
    def extract_article_content(self, url: str) -> Optional[str]:
        """
        Extract main article text from a URL using BeautifulSoup
        
        Args:
            url: URL of the article
            
        Returns:
            Extracted text content or None if failed
        """
        try:
            print(f"📄 Extracting content from: {url[:50]}...")
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Remove script and style elements
            for script in soup(["script", "style", "nav", "footer", "header"]):
                script.decompose()
            
            # Try to find main content
            main_content = None
            
            # Common article content selectors
            selectors = [
                'article',
                '.article-content',
                '.story-content',
                '.post-content',
                '#article-body',
                '.entry-content',
                'main'
            ]
            
            for selector in selectors:
                main_content = soup.select_one(selector)
                if main_content:
                    break
            
            # Fallback to body if no main content found
            if not main_content:
                main_content = soup.find('body')
            
            if main_content:
                # Extract text
                text = main_content.get_text(separator='\n', strip=True)
                
                # Clean up excessive whitespace
                lines = [line.strip() for line in text.split('\n') if line.strip()]
                text = '\n'.join(lines)
                
                # Limit to reasonable length for LLM processing (first 10000 chars)
                # Increased to capture more complete articles for accurate sentiment
                if len(text) > 10000:
                    text = text[:10000] + "..."
                
                print(f"✅ Extracted {len(text)} characters")
                return text
            
            return None
            
        except Exception as e:
            print(f"❌ Error extracting content from {url}: {e}")
            return None
    
    def analyze_with_llm(
        self, 
        stock_name: str,
        articles_data: List[Dict],
        extracted_contents: List[str]
    ) -> Dict:
        """
        Analyze articles using LLM to extract insights and sentiment
        
        IMPORTANT: Sentiment is analyzed FIRST on raw extracted text,
        then summary is generated. This ensures sentiment reflects the
        actual content, not a neutralized summary.
        
        Args:
            stock_name: Name of the stock
            articles_data: List of article metadata from Tavily
            extracted_contents: List of extracted article contents
            
        Returns:
            Dictionary with analysis results
        """
        try:
            print(f"🤖 Analyzing {len(articles_data)} articles with LLM...")
            
            # STEP 1: Analyze sentiment directly on raw extracted text
            print(f"📊 Step 1: Analyzing sentiment on raw extracted text...")
            sentiment_score = self._analyze_sentiment_on_raw_text(
                stock_name, 
                articles_data, 
                extracted_contents
            )
            
            # STEP 2: Generate comprehensive summary using all extracted text
            print(f"📝 Step 2: Generating comprehensive summary...")
            analysis_text = self._generate_comprehensive_summary(
                stock_name,
                articles_data,
                extracted_contents,
                sentiment_score
            )
            
            result = {
                "stock_name": stock_name,
                "analysis": analysis_text,
                "sentiment_score": sentiment_score,
                "articles_analyzed": len(articles_data),
                "timestamp": datetime.now().isoformat()
            }
            
            print(f"✅ Analysis complete. Sentiment: {sentiment_score}/100")
            return result
            
        except Exception as e:
            print(f"❌ LLM analysis error: {e}")
            
            # Return a basic analysis based on article titles
            basic_analysis = self._generate_basic_analysis(stock_name, articles_data)
            
            return {
                "stock_name": stock_name,
                "analysis": basic_analysis,
                "sentiment_score": 50,
                "articles_analyzed": len(articles_data),
                "timestamp": datetime.now().isoformat(),
                "error": f"LLM analysis failed: {str(e)}"
            }
    
    def _analyze_sentiment_on_raw_text(
        self,
        stock_name: str,
        articles_data: List[Dict],
        extracted_contents: List[str]
    ) -> int:
        """
        Analyze sentiment directly on raw extracted text (ALL content)
        This happens BEFORE summarization to capture true sentiment
        
        Returns:
            Sentiment score (0-100)
        """
        try:
            # Prepare ALL extracted content for sentiment analysis
            sentiment_context = f"Stock: {stock_name}\n\n"
            sentiment_context += "RAW ARTICLE CONTENT (Complete Extracted Text):\n\n"
            
            for i, (article, content) in enumerate(zip(articles_data, extracted_contents), 1):
                sentiment_context += f"--- Article {i} ---\n"
                sentiment_context += f"Title: {article.get('title', 'N/A')}\n"
                sentiment_context += f"Source: {article.get('url', 'N/A')}\n"
                # Use ALL extracted content for sentiment (no truncation)
                if content:
                    sentiment_context += f"Full Content:\n{content}\n\n"
                else:
                    sentiment_context += f"Content: Not available\n\n"
            
            # Create sentiment-focused prompt
            sentiment_prompt = f"""You are analyzing sentiment for {stock_name} stock based on the COMPLETE RAW ARTICLE CONTENT provided below.

CRITICAL INSTRUCTIONS:
1. Analyze sentiment on the RAW CONTENT provided, NOT on any summary
2. Consider the ENTIRE content of each article, not just headlines
3. Look for positive indicators: growth, targets, optimism, opportunities
4. Look for negative indicators: risks, concerns, warnings, challenges
5. Balance both positive and negative aspects found in the content

Based on the complete raw article content below, provide ONLY a sentiment score from 0-100:
- 0-29: Very Negative (major concerns, significant risks)
- 30-44: Negative (more concerns than positives)
- 45-54: Neutral (balanced or mixed signals)
- 55-69: Positive (more positives than concerns)
- 70-100: Very Positive (strong optimism, minimal concerns)

RAW ARTICLE CONTENT:
{sentiment_context}

Respond with ONLY the numerical sentiment score (0-100) and a brief one-line justification.
Format: "Score: XX - [brief reason]"
"""

            # Try models for sentiment analysis
            models_to_try = [
                "openai/gpt-oss-120b",  # Free model (primary)
                "google/gemini-2.0-flash-exp:free",
                "meta-llama/llama-3.1-8b-instruct",
                "openai/gpt-4o-mini",
            ]
            
            for model in models_to_try:
                try:
                    print(f"  🔄 Trying model for sentiment: {model}")
                    
                    response = self.client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": "You are a financial sentiment analyst. Analyze the raw content and provide accurate sentiment scores."},
                            {"role": "user", "content": sentiment_prompt}
                        ],
                        temperature=0.2,  # Lower temperature for more consistent scoring
                        max_tokens=100  # Short response needed
                    )
                    
                    sentiment_response = response.choices[0].message.content
                    print(f"  ✅ Sentiment analysis: {sentiment_response[:100]}")
                    
                    # Extract score
                    score = self._extract_sentiment_score(sentiment_response)
                    return score
                    
                except Exception as e:
                    print(f"  ⚠️ Model {model} failed for sentiment: {str(e)[:100]}")
                    continue
            
            # Fallback to neutral if all models fail
            print("  ⚠️ All models failed for sentiment, using neutral score")
            return 50
            
        except Exception as e:
            print(f"  ❌ Sentiment analysis error: {e}")
            return 50
    
    def _generate_comprehensive_summary(
        self,
        stock_name: str,
        articles_data: List[Dict],
        extracted_contents: List[str],
        sentiment_score: int
    ) -> str:
        """
        Generate comprehensive summary using ALL extracted text
        Sentiment score is already calculated, so summary can be neutral
        
        Returns:
            Detailed analysis text
        """
        try:
            # Prepare ALL extracted content for summary
            summary_context = f"Stock: {stock_name}\n"
            summary_context += f"Pre-calculated Sentiment Score: {sentiment_score}/100\n\n"
            summary_context += "COMPLETE ARTICLE CONTENT:\n\n"
            
            for i, (article, content) in enumerate(zip(articles_data, extracted_contents), 1):
                summary_context += f"--- Article {i} ---\n"
                summary_context += f"Title: {article.get('title', 'N/A')}\n"
                summary_context += f"Source: {article.get('url', 'N/A')}\n"
                # Use ALL extracted content for summary (no truncation)
                if content:
                    summary_context += f"Content:\n{content}\n\n"
                else:
                    summary_context += f"Content: Not available\n\n"
            
            # Create comprehensive summary prompt
            summary_prompt = f"""Analyze the following complete articles about {stock_name} stock and provide a comprehensive analysis.

NOTE: Sentiment score has already been calculated as {sentiment_score}/100 based on the raw content. Your job is to provide detailed analysis.

Please provide:

1. **Future Outlook Summary**: Summarize the overall future expectations for this stock based on ALL article content
2. **Analyst Price Targets**: Extract any mentioned price targets or forecasts from the articles
3. **Growth Projections**: Identify growth rate predictions or revenue forecasts mentioned
4. **Key Catalysts**: List upcoming events, product launches, or factors that could impact the stock
5. **Risk Factors**: Identify mentioned risks or concerns from the article content
6. **Confidence Level**: Rate your confidence in this analysis (Low/Medium/High)

COMPLETE ARTICLE CONTENT:
{summary_context}

Provide your analysis in a structured format with clear sections. Use ALL the content provided above."""

            # Try models for summary generation
            models_to_try = [
                "openai/gpt-oss-120b", 
                "google/gemini-2.0-flash-exp:free",
                "meta-llama/llama-3.1-8b-instruct",
                "openai/gpt-4o-mini",
            ]
            print(f"  📊 Generating summary with {len(models_to_try)} fallback models...")
            
            for model in models_to_try:
                try:
                    print(f"  🔄 Trying model for summary: {model}")
                    
                    response = self.client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": "You are a financial analyst expert specializing in stock market analysis. Provide comprehensive analysis based on complete article content."},
                            {"role": "user", "content": summary_prompt}
                        ],
                        temperature=0.3,
                        max_tokens=3000
                    )
                    
                    analysis_text = response.choices[0].message.content
                    print(f"  ✅ Summary generated successfully")
                    return analysis_text
                    
                except Exception as e:
                    print(f"  ⚠️ Model {model} failed for summary: {str(e)[:100]}")
                    continue
            
            # Fallback summary
            return f"Analysis for {stock_name} based on {len(articles_data)} articles. Sentiment score: {sentiment_score}/100. Detailed analysis unavailable."
            
        except Exception as e:
            print(f"  ❌ Summary generation error: {e}")
            return f"Error generating summary: {str(e)}"
    
    def _extract_sentiment_score(self, analysis_text: str) -> int:
        """Extract sentiment score from analysis text"""
        import re
        
        # Look for sentiment score patterns
        patterns = [
            r'sentiment score[:\s]+(\d+)',
            r'score[:\s]+(\d+)/100',
            r'sentiment[:\s]+(\d+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, analysis_text.lower())
            if match:
                score = int(match.group(1))
                return max(0, min(100, score))  # Clamp between 0-100
        
        # Default to neutral if not found
        return 50
    
    def _generate_basic_analysis(self, stock_name: str, articles_data: List[Dict]) -> str:
        """Generate basic analysis from article titles when LLM fails"""
        
        analysis = f"**Basic Analysis for {stock_name}**\n\n"
        analysis += "Note: This is a simplified analysis based on article titles only, as detailed LLM analysis was unavailable.\n\n"
        
        analysis += "**Recent News Articles:**\n\n"
        
        for i, article in enumerate(articles_data[:5], 1):
            title = article.get('title', 'Untitled')
            source = article.get('url', '').split('/')[2] if article.get('url') else 'Unknown'
            analysis += f"{i}. {title}\n"
            analysis += f"   Source: {source}\n\n"
        
        analysis += "\n**Recommendation:**\n"
        analysis += "For detailed analysis, please review the source articles directly or try refreshing the analysis.\n"
        
        return analysis
    
    def get_comprehensive_analysis(
        self, 
        stock_name: str,
        max_articles: int = 10,
        extract_content: bool = True
    ) -> Dict:
        """
        Complete workflow: Search, extract, and analyze stock news
        
        Args:
            stock_name: Name or ticker of the stock
            max_articles: Maximum number of articles to analyze
            extract_content: Whether to extract full article content
            
        Returns:
            Complete analysis dictionary
        """
        print(f"\n{'='*60}")
        print(f"🚀 Starting comprehensive analysis for: {stock_name}")
        print(f"{'='*60}\n")
        
        # Step 1: Search for news
        articles, tavily_answer = self.search_stock_news(stock_name, max_articles)
        
        if not articles:
            return {
                "error": "No articles found",
                "stock_name": stock_name,
                "timestamp": datetime.now().isoformat()
            }
        
        # Step 2: Extract content from top articles
        extracted_contents = []
        
        if extract_content:
            print(f"\n📥 Extracting content from {len(articles)} articles...")
            for article in articles[:max_articles]:
                url = article.get('url')
                if url:
                    content = self.extract_article_content(url)
                    extracted_contents.append(content or article.get('content', ''))
                else:
                    extracted_contents.append(article.get('content', ''))
        else:
            # Use Tavily's content snippets
            extracted_contents = [article.get('content', '') for article in articles]
        
        # Step 3: Analyze with LLM
        analysis_result = self.analyze_with_llm(stock_name, articles, extracted_contents)
        
        # Step 4: Compile final result
        result = {
            **analysis_result,
            "tavily_summary": tavily_answer,
            "articles": [
                {
                    "title": article.get('title'),
                    "url": article.get('url'),
                    "source": article.get('url', '').split('/')[2] if article.get('url') else 'Unknown',
                    "snippet": article.get('content', '')[:200] + "..."
                }
                for article in articles
            ]
        }
        
        print(f"\n{'='*60}")
        print(f"✅ Analysis complete for {stock_name}")
        print(f"{'='*60}\n")
        
        return result


# Standalone function for easy integration
def analyze_stock_news(
    stock_name: str,
    max_articles: int = 10,
    extract_full_content: bool = True
) -> Dict:
    """
    Convenience function to analyze stock news
    
    Args:
        stock_name: Name or ticker of the stock
        max_articles: Maximum number of articles to analyze
        extract_full_content: Whether to extract full article content
        
    Returns:
        Analysis dictionary with sentiment and insights
    """
    analyzer = StockNewsAnalyzer()
    return analyzer.get_comprehensive_analysis(
        stock_name, 
        max_articles, 
        extract_full_content
    )


if __name__ == "__main__":
    # Test the analyzer
    result = analyze_stock_news("Tata Motors", max_articles=5)
    
    print("\n" + "="*60)
    print("ANALYSIS RESULT")
    print("="*60)
    print(json.dumps(result, indent=2))
