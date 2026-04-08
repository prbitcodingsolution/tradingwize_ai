# -*- coding: utf-8 -*-
"""
Sentiment Analysis Module for Stock Market using RapidAPI Twitter
Analyzes sentiment from news sources, Yahoo Finance, and Twitter/X via RapidAPI
"""

import requests
import httpx
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
from .model_config import get_client
import json
import time

load_dotenv()

USE_FINBERT = os.getenv("FINBERT_ENABLED", "true").lower() == "true"

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
RAPID_API_KEY = os.getenv("RAPID_API_KEY")
RAPID_API_HOST = os.getenv("RAPID_API_HOST")


class RapidAPISentimentAnalyzer:
    """
    Comprehensive sentiment analysis for stocks using multiple sources:
    1. News sources (CNBC, Financial Express, Business Standard, etc.)
    2. Yahoo Finance
    3. Twitter/X sentiment (via RapidAPI)
    
    Combines all sources into a unified sentiment score.
    """
    
    def __init__(self):
        self.client = get_client()
        self.news_sources = [
            "cnbc.com",
            "financialexpress.com", 
            "business-standard.com",
            "nseindia.com",
            "livemint.com",
            "moneycontrol.com",
            "economictimes.indiatimes.com",
            "forexfactory.com",
            "myfxbook.com",
        ]
        
        if not RAPID_API_KEY or not RAPID_API_HOST:
            print("⚠️ RAPID_API_KEY or RAPID_API_HOST not found in .env file")
            print("   Add: RAPID_API_KEY=your_key")
            print("   Add: RAPID_API_HOST=twitter-api45.p.rapidapi.com")
    
    def _normalize_sentiment_score(self, score: float) -> float:
        """
        Normalize sentiment score to 0-100 range.
        Handles cases where score might be in -100 to +100 range or VADER -1 to +1 range.
        
        Args:
            score: Raw sentiment score
            
        Returns:
            Normalized score in 0-100 range
        """
        # If score is negative or > 100, it's likely in -100 to +100 range
        if score < 0 or score > 100:
            # Convert from -100/+100 to 0-100
            score = (score + 100) / 2
        
        # Clamp to 0-100 range
        return max(0, min(100, score))
    
    def _search_tavily(self, query: str, domains: Optional[List[str]] = None, max_results: int = 10) -> Tuple[List[Dict], str]:
        """Search using Tavily API with specific domains"""
        try:
            url = "https://api.tavily.com/search"
            headers = {"Content-Type": "application/json; charset=utf-8"}
            
            payload = {
                "api_key": TAVILY_API_KEY,
                "query": query,
                "search_depth": "advanced",
                "max_results": max_results,
                "include_answer": True,
                "include_domains": domains if domains else []
            }
            
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            response.encoding = 'utf-8'
            
            if response.status_code == 200:
                data = response.json()
                results = data.get('results', [])
                answer = data.get('answer', '')
                return results, answer
            else:
                print(f"❌ Tavily API error: {response.status_code}")
                return [], ''
                
        except Exception as e:
            print(f"❌ Tavily search error: {e}")
            return [], ''
    
    def analyze_news_sentiment(self, stock_name: str, stock_symbol: str) -> Dict:
        """Analyze sentiment from news sources"""
        print(f"📰 Analyzing news sentiment for {stock_name}...")
        
        query = f"{stock_name} {stock_symbol} stock news latest updates"
        all_news = []
        news_count_by_source = {}  # Track news count per domain
        
        # Search each news source
        for source in self.news_sources:
            try:
                results, _ = self._search_tavily(query, domains=[source], max_results=3)
                news_count = len(results)
                news_count_by_source[source] = news_count
                
                for result in results:
                    all_news.append({
                        'title': result.get('title', ''),
                        'content': result.get('content', ''),
                        'url': result.get('url', ''),
                        'source': source,
                        'published_date': result.get('published_date', '')
                    })
                
                # Log news count for this source
                if news_count > 0:
                    print(f"  ✅ {source}: {news_count} articles fetched")
                else:
                    print(f"  ⚠️ {source}: No articles found")
                    
                time.sleep(0.5)
            except Exception as e:
                print(f"  ❌ Error fetching from {source}: {e}")
                news_count_by_source[source] = 0
        
        # Print summary
        total_news = len(all_news)
        print(f"\n📊 Total news articles fetched: {total_news}")
        print(f"📋 Breakdown by source:")
        for source, count in news_count_by_source.items():
            print(f"   • {source}: {count}")
        
        # Analyze sentiment using FinBERT (primary) or LLM fallback
        if all_news:
            news_text = "\n\n".join([
                f"Source: {item['source']}\nTitle: {item['title']}\nContent: {item['content'][:300]}"
                for item in all_news[:15]
            ])

            sentiment_data = None

            # --- FinBERT path ---
            if USE_FINBERT:
                try:
                    from .finbert_sentiment import FinBERTSentimentAnalyzer
                    texts = [
                        f"{a['title']} {a['content']}"
                        for a in all_news
                        if (a.get('title') or a.get('content', '')).strip()
                    ]
                    finbert = FinBERTSentimentAnalyzer.get_instance()
                    fb_result = finbert.analyze_texts(texts)
                    finbert_score = fb_result["score"]
                    article_count = len(texts)

                    if finbert_score >= 70:
                        sentiment_label = "Strongly Bullish"
                    elif finbert_score >= 60:
                        sentiment_label = "Bullish"
                    elif finbert_score >= 40:
                        sentiment_label = "Neutral"
                    elif finbert_score >= 30:
                        sentiment_label = "Bearish"
                    else:
                        sentiment_label = "Strongly Bearish"

                    print(f"\n   FinBERT News Score: {finbert_score:.1f}/100  ({sentiment_label})")

                    # LLM for key points only
                    key_prompt = f"""Analyze these news articles about {stock_name} ({stock_symbol}).
FinBERT sentiment score: {finbert_score:.1f}/100

Articles:
{news_text}

DO NOT change the score. Return ONLY valid JSON:
{{
  "positive_points": ["point1", "point2"],
  "negative_points": ["point1", "point2"],
  "market_mood": "<2-3 sentence summary>"
}}"""
                    try:
                        resp = self.client.chat.completions.create(
                            model="openai/gpt-oss-120b",
                            messages=[
                                {"role": "system", "content": "Financial analyst extracting key points. Do not change the sentiment score."},
                                {"role": "user", "content": key_prompt}
                            ],
                            temperature=0.1,
                            max_tokens=800,
                        )
                        rt = resp.choices[0].message.content.strip()
                        if "```json" in rt:
                            rt = rt.split("```json")[1].split("```")[0].strip()
                        elif "```" in rt:
                            rt = rt.split("```")[1].split("```")[0].strip()
                        llm_data = json.loads(rt)
                    except Exception as e:
                        print(f"   LLM key-points extraction failed: {e}")
                        llm_data = {}

                    sentiment_data = {
                        'sentiment_score': round(finbert_score, 1),
                        'sentiment_label': sentiment_label,
                        'positive_points': llm_data.get('positive_points', ['Positive indicators noted']),
                        'negative_points': llm_data.get('negative_points', ['Some concerns noted']),
                        'market_mood': llm_data.get('market_mood', f'Market sentiment is {sentiment_label.lower()} based on news analysis.'),
                        'confidence': 'High' if article_count >= 20 else 'Medium' if article_count >= 10 else 'Low',
                        'news_count': len(all_news),
                        'finbert_result': fb_result,
                    }

                except Exception as e:
                    print(f"   FinBERT news scoring failed: {e} — falling back to LLM")
                    sentiment_data = None

            # --- LLM-only fallback ---
            if sentiment_data is None:
                print(f"   Using LLM-only analysis for news sentiment")
                sentiment_prompt = f"""Analyze the sentiment of these news articles about {stock_name} ({stock_symbol}).

Articles:
{news_text}

BE OBJECTIVE. Return ONLY valid JSON:
{{
  "sentiment_score": <0-100>,
  "sentiment_label": "<Strongly Bullish|Bullish|Neutral|Bearish|Strongly Bearish>",
  "positive_points": ["point1", "point2"],
  "negative_points": ["point1", "point2"],
  "market_mood": "<2-3 sentence summary>",
  "confidence": "<High|Medium|Low>",
  "news_count": {len(all_news)}
}}"""
                try:
                    response = self.client.chat.completions.create(
                        model="openai/gpt-oss-120b",
                        messages=[
                            {"role": "system", "content": "Objective financial sentiment analyst."},
                            {"role": "user", "content": sentiment_prompt}
                        ],
                        temperature=0.1,
                        max_tokens=1000,
                    )
                    result_text = response.choices[0].message.content.strip()
                    if "```json" in result_text:
                        result_text = result_text.split("```json")[1].split("```")[0].strip()
                    elif "```" in result_text:
                        result_text = result_text.split("```")[1].split("```")[0].strip()
                    sentiment_data = json.loads(result_text)
                except Exception as e:
                    print(f"Error analyzing news sentiment: {e}")
                    return self._get_default_sentiment()
            
            # Add statistics
            total_articles = len(all_news)
            sentiment_data['total_articles'] = total_articles
            sentiment_data['news_count'] = total_articles  # Keep for backward compatibility
            sentiment_data['news_articles'] = all_news[:10]
            
            # Calculate sentiment breakdown
            score = sentiment_data.get('sentiment_score', 0)
            if score > 20:
                positive_count = int(total_articles * 0.7)
                negative_count = int(total_articles * 0.1)
            elif score < -20:
                positive_count = int(total_articles * 0.1)
                negative_count = int(total_articles * 0.7)
            else:
                positive_count = int(total_articles * 0.4)
                negative_count = int(total_articles * 0.3)
            
            neutral_count = total_articles - positive_count - negative_count
            
            sentiment_data['positive_count'] = positive_count
            sentiment_data['negative_count'] = negative_count
            sentiment_data['neutral_count'] = neutral_count
            sentiment_data['positive_percentage'] = (positive_count / total_articles * 100) if total_articles > 0 else 0
            sentiment_data['negative_percentage'] = (negative_count / total_articles * 100) if total_articles > 0 else 0
            sentiment_data['neutral_percentage'] = (neutral_count / total_articles * 100) if total_articles > 0 else 0
            
            # Add key insights
            if 'key_insights' not in sentiment_data:
                sentiment_data['key_insights'] = [
                    f"Analyzed {total_articles} news articles from {len(news_count_by_source)} sources",
                    f"Overall sentiment: {sentiment_data.get('sentiment_label', 'Unknown')}",
                    sentiment_data.get('market_mood', 'Market sentiment analysis complete')
                ]
            
            print(f"✅ News sentiment analyzed: {score}/100 ({sentiment_data.get('sentiment_label', 'Unknown')})")
            
            return sentiment_data
        
        return self._get_default_sentiment()
    
    def analyze_yahoo_finance_sentiment(self, stock_symbol: str, stock_name: str) -> Dict:
        """Analyze sentiment from Yahoo Finance with yfinance fallback"""
        print(f"📊 Analyzing Yahoo Finance sentiment for {stock_symbol}...")
        
        # Try yfinance FIRST for most reliable data
        print(f"   🔄 Fetching data from yfinance (direct Yahoo Finance API)...")
        try:
            import yfinance as yf
            
            ticker = yf.Ticker(stock_symbol)
            info = ticker.info
            
            # Get analyst recommendations
            try:
                recommendations = ticker.recommendations
                if recommendations is not None and not recommendations.empty:
                    latest = recommendations.iloc[-1]
                    
                    buy_count = int(latest.get('strongBuy', 0) + latest.get('buy', 0))
                    hold_count = int(latest.get('hold', 0))
                    sell_count = int(latest.get('sell', 0) + latest.get('strongSell', 0))
                    total = buy_count + hold_count + sell_count
                    
                    if total > 0:
                        # Calculate sentiment score based on recommendations (0-100 scale)
                        # Buy = +1, Hold = 0, Sell = -1
                        # Convert from -1 to +1 range to 0-100 scale
                        raw_score = (buy_count - sell_count) / total  # -1 to +1
                        sentiment_score = (raw_score + 1) * 50  # Convert to 0-100
                        
                        # Determine rating
                        if buy_count > hold_count and buy_count > sell_count:
                            rating = "Buy"
                        elif sell_count > buy_count and sell_count > hold_count:
                            rating = "Sell"
                        else:
                            rating = "Hold"
                        
                        target_price = info.get('targetMeanPrice')
                        current_price = info.get('currentPrice')
                        
                        result = {
                            'sentiment_score': round(sentiment_score, 1),
                            'analyst_rating': rating,
                            'buy_recommendations': buy_count,
                            'hold_recommendations': hold_count,
                            'sell_recommendations': sell_count,
                            'average_price_target': target_price,
                            'institutional_sentiment': 'Positive' if sentiment_score > 20 else 'Negative' if sentiment_score < -20 else 'Neutral',
                            'key_insights': [
                                f"{total} analysts covering {stock_name}",
                                f"Consensus: {rating} ({buy_count} buy, {hold_count} hold, {sell_count} sell)",
                                f"Target price: ₹{target_price:.2f}" if target_price else "No target price available"
                            ]
                        }
                        
                        print(f"   ✅ Yahoo Finance sentiment (yfinance): {result['sentiment_score']}/100 ({result['analyst_rating']})")
                        return result
                    else:
                        print(f"   ⚠️ No analyst recommendations available (total = 0)")
                else:
                    print(f"   ⚠️ No analyst recommendations data for {stock_symbol}")
                    
                # If no analyst data, try to infer sentiment from other metrics
                print(f"   🔄 Attempting to infer sentiment from other Yahoo Finance metrics...")
                
                # Get institutional holdings, insider transactions, etc.
                current_price = info.get('currentPrice')
                fifty_two_week_high = info.get('fiftyTwoWeekHigh')
                fifty_two_week_low = info.get('fiftyTwoWeekLow')
                recommendation_mean = info.get('recommendationMean')  # 1=Strong Buy, 5=Strong Sell
                
                # Calculate price position (where current price is relative to 52-week range)
                if current_price and fifty_two_week_high and fifty_two_week_low:
                    price_range = fifty_two_week_high - fifty_two_week_low
                    if price_range > 0:
                        price_position = ((current_price - fifty_two_week_low) / price_range) * 100
                        
                        # Convert price position to sentiment score (0-100 scale)
                        # Use a more balanced approach - middle range is neutral (50)
                        # Near highs = bullish, near lows = potential value opportunity (neutral to slightly bearish)
                        if price_position >= 75:
                            base_sentiment = 75  # Near 52-week high = bullish
                        elif price_position >= 60:
                            base_sentiment = 65
                        elif price_position >= 40:
                            base_sentiment = 55  # Middle range = neutral to slightly positive
                        elif price_position >= 25:
                            base_sentiment = 50  # Below middle = neutral
                        else:
                            base_sentiment = 45  # Near 52-week low = slightly bearish (but could be value opportunity)
                        
                        # Adjust based on recommendation mean if available
                        if recommendation_mean:
                            # recommendationMean: 1=Strong Buy, 2=Buy, 3=Hold, 4=Sell, 5=Strong Sell
                            # Convert to 0-100 scale: 1→100, 2→75, 3→50, 4→25, 5→0
                            rec_score = (5 - recommendation_mean) * 25
                            sentiment_score = (base_sentiment + rec_score) / 2
                        else:
                            sentiment_score = base_sentiment
                        
                        # Determine rating based on sentiment score (0-100 scale)
                        if sentiment_score >= 65:
                            rating = "Buy"
                        elif sentiment_score <= 35:
                            rating = "Sell"
                        else:
                            rating = "Hold"
                        
                        result = {
                            'sentiment_score': round(sentiment_score, 1),
                            'analyst_rating': rating,
                            'buy_recommendations': 0,
                            'hold_recommendations': 0,
                            'sell_recommendations': 0,
                            'average_price_target': None,
                            'institutional_sentiment': 'Positive' if sentiment_score > 20 else 'Negative' if sentiment_score < -20 else 'Neutral',
                            'key_insights': [
                                f"Limited analyst coverage for {stock_name}",
                                f"Current price: ₹{current_price:.2f}" if current_price else "Price data unavailable",
                                f"52-week range: ₹{fifty_two_week_low:.2f} - ₹{fifty_two_week_high:.2f}" if fifty_two_week_low and fifty_two_week_high else "Range data unavailable",
                                f"Price at {price_position:.1f}% of 52-week range" + (" (near lows - potential value opportunity)" if price_position < 30 else " (near highs)" if price_position > 70 else "")
                            ],
                            'data_source': 'price_metrics'
                        }
                        
                        print(f"   ✅ Yahoo Finance sentiment (price metrics): {result['sentiment_score']}/100 ({result['analyst_rating']})")
                        return result
                        
            except Exception as e:
                print(f"   ⚠️ Could not fetch recommendations from yfinance: {e}")
        
        except ImportError:
            print(f"   ⚠️ yfinance not installed, trying Tavily...")
        except Exception as e:
            print(f"   ⚠️ Error using yfinance: {e}, trying Tavily...")
        
        # Fallback to Tavily search + FinBERT scoring
        print(f"   🔄 Trying Tavily search as fallback...")
        query = f"{stock_name} {stock_symbol} site:finance.yahoo.com analyst rating recommendation"
        results, answer = self._search_tavily(query, domains=["finance.yahoo.com"], max_results=5)

        if results or answer:
            # Collect text snippets for FinBERT
            snippets = []
            if answer:
                snippets.append(answer)
            for r in results:
                title = r.get('title', '')
                content = r.get('content', '')
                if title or content:
                    snippets.append(f"{title} {content}")

            content = answer + "\n\n" + "\n\n".join([
                f"{r.get('title', '')}\n{r.get('content', '')}"
                for r in results
            ])

            # --- FinBERT for scoring ---
            yahoo_finbert_score = 50.0
            if USE_FINBERT and snippets:
                try:
                    from .finbert_sentiment import FinBERTSentimentAnalyzer
                    finbert = FinBERTSentimentAnalyzer.get_instance()
                    fb = finbert.analyze_texts(snippets)
                    yahoo_finbert_score = fb['score']
                    print(f"   ✅ Yahoo Finance FinBERT Score: {yahoo_finbert_score:.1f}/100")
                except Exception as e:
                    print(f"   ⚠️ FinBERT for Yahoo Tavily failed: {e}")

            # --- LLM for structured fields only (analyst counts, price target, insights) ---
            struct_prompt = f"""From this Yahoo Finance content about {stock_name} ({stock_symbol}), extract ONLY:
- analyst_rating (Buy/Hold/Sell)
- buy_recommendations (integer)
- hold_recommendations (integer)
- sell_recommendations (integer)
- average_price_target (number or null)
- institutional_sentiment (Positive/Neutral/Negative)
- key_insights (list of 2-3 strings)

Content:
{content[:3000]}

Return ONLY valid JSON:
{{
  "analyst_rating": "<Buy/Hold/Sell>",
  "buy_recommendations": <number>,
  "hold_recommendations": <number>,
  "sell_recommendations": <number>,
  "average_price_target": <number or null>,
  "institutional_sentiment": "<Positive/Neutral/Negative>",
  "key_insights": ["insight1", "insight2"]
}}"""

            try:
                response = self.client.chat.completions.create(
                    model="openai/gpt-oss-120b",
                    messages=[
                        {"role": "system", "content": "You are a financial analyst. Extract structured fields and return ONLY valid JSON."},
                        {"role": "user", "content": struct_prompt},
                    ],
                    temperature=0.1,
                    max_tokens=500,
                )
                result_text = response.choices[0].message.content.strip()
                if "```json" in result_text:
                    result_text = result_text.split("```json")[1].split("```")[0].strip()
                elif "```" in result_text:
                    result_text = result_text.split("```")[1].split("```")[0].strip()
                struct = json.loads(result_text)
                result = {
                    'sentiment_score': round(yahoo_finbert_score, 1),
                    'analyst_rating': struct.get('analyst_rating', 'Hold'),
                    'buy_recommendations': struct.get('buy_recommendations', 0),
                    'hold_recommendations': struct.get('hold_recommendations', 0),
                    'sell_recommendations': struct.get('sell_recommendations', 0),
                    'average_price_target': struct.get('average_price_target'),
                    'institutional_sentiment': struct.get('institutional_sentiment', 'Neutral'),
                    'key_insights': struct.get('key_insights', []),
                    'data_source': 'tavily_finbert',
                }
                print(f"   ✅ Yahoo Finance sentiment (Tavily+FinBERT): {result['sentiment_score']}/100 ({result['analyst_rating']})")
                return result
            except Exception as e:
                print(f"   ⚠️ Error extracting Yahoo Finance structured fields: {e}")
        
        print(f"   ⚠️ Returning default Yahoo Finance sentiment")
        return self._get_default_yahoo_sentiment()
    
    def analyze_twitter_sentiment_rapidapi(self, stock_symbol: str, stock_name: str) -> Dict:
        """
        Analyze Twitter/X sentiment using RapidAPI
        
        Args:
            stock_symbol: Stock ticker symbol (e.g., "BAJAJFINSV", "RELIANCE")
            stock_name: Company name for better context
            
        Returns:
            Dictionary with Twitter sentiment data
        """
        print(f"🐦 Analyzing Twitter/X sentiment for {stock_symbol} via RapidAPI...")
        
        if not RAPID_API_KEY or not RAPID_API_HOST:
            print("⚠️ RAPID_API_KEY or RAPID_API_HOST not configured")
            return self._get_default_social_sentiment("twitter")
        
        try:
            # Call RapidAPI Twitter search endpoint
            url = f"https://{RAPID_API_HOST}/search.php"
            
            headers = {
                "X-RapidAPI-Key": RAPID_API_KEY,
                "X-RapidAPI-Host": RAPID_API_HOST
            }
            
            params = {"query": stock_symbol}
            
            print(f"   📡 Calling: {url}?query={stock_symbol}")
            response = requests.get(url, headers=headers, params=params, timeout=15)
            print(f"   📊 Response status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                
                # Check if we got valid data
                if data.get('status') != 'ok' or 'timeline' not in data:
                    print(f"⚠️ Invalid response format from RapidAPI")
                    return self._get_default_social_sentiment("twitter")
                
                timeline = data.get('timeline', [])
                
                if not timeline:
                    print(f"   ℹ️ No tweets found for {stock_symbol}")
                    return self._get_default_social_sentiment("twitter")
                
                # Extract relevant tweet data
                tweets_data = []
                for item in timeline:
                    if item.get('type') == 'tweet':
                        tweet_info = {
                            'tweet_id': item.get('tweet_id'),
                            'screen_name': item.get('screen_name'),
                            'text': item.get('text', ''),
                            'created_at': item.get('created_at'),
                            'favorites': item.get('favorites', 0),
                            'retweets': item.get('retweets', 0),
                            'replies': item.get('replies', 0),
                            'quotes': item.get('quotes', 0),
                            'bookmarks': item.get('bookmarks', 0),
                            'lang': item.get('lang', 'en')
                        }
                        tweets_data.append(tweet_info)
                
                print(f"   ✅ Found {len(tweets_data)} tweets")
                
                # Combine all tweet texts for sentiment analysis
                combined_text = "\n\n".join([
                    f"@{tweet['screen_name']}: {tweet['text']}"
                    for tweet in tweets_data[:50]  # Limit to 50 tweets for analysis
                ])
                
                # Analyze sentiment using LLM
                sentiment_result = self._analyze_tweets_sentiment(
                    combined_text, 
                    stock_symbol, 
                    stock_name, 
                    tweets_data
                )
                
                return sentiment_result
                
            else:
                print(f"⚠️ RapidAPI returned status {response.status_code}")
                try:
                    error_detail = response.json()
                    print(f"   Error details: {error_detail}")
                except:
                    print(f"   Response text: {response.text[:200]}")
                
                return self._get_default_social_sentiment("twitter")
                
        except requests.exceptions.ConnectionError as e:
            error_msg = str(e)
            if "Failed to resolve" in error_msg or "getaddrinfo failed" in error_msg:
                print(f"⚠️ Twitter API endpoint is currently unavailable (DNS resolution failed)")
                print(f"   This is likely a temporary network issue or API service downtime")
                print(f"   Continuing with other sentiment sources...")
            else:
                print(f"❌ Connection error fetching Twitter sentiment: {error_msg[:200]}")
            return self._get_default_social_sentiment("twitter")
            
        except requests.exceptions.Timeout:
            print(f"⏱️ Twitter API request timed out after 15 seconds")
            print(f"   Continuing with other sentiment sources...")
            return self._get_default_social_sentiment("twitter")
            
        except requests.exceptions.RequestException as e:
            print(f"⚠️ Request error fetching Twitter sentiment: {str(e)[:200]}")
            return self._get_default_social_sentiment("twitter")
            
        except Exception as e:
            print(f"❌ Unexpected error in Twitter sentiment analysis: {e}")
            import traceback
            traceback.print_exc()
            return self._get_default_social_sentiment("twitter")
    
    def _analyze_tweets_sentiment(self, combined_text: str, stock_symbol: str,
                                  stock_name: str, tweets_data: List[Dict]) -> Dict:
        """
        Analyze sentiment of tweet texts using FinBERT (primary) + LLM for theme extraction.
        FinBERT is domain-specific to finance and more accurate than VADER for stock tweets.
        """
        print(f"   🤖 Analyzing sentiment of {len(tweets_data)} tweets with FinBERT...")

        tweet_texts = [t.get('text', '') for t in tweets_data if t.get('text', '').strip()]
        if not tweet_texts:
            print(f"   ⚠️ No valid tweet texts to analyze")
            return self._get_default_social_sentiment("twitter")

        # --- FinBERT scoring (primary) ---
        finbert_score = 50.0
        breakdown = {'positive': 0, 'negative': 0, 'neutral': 0}
        finbert_ok = False

        if USE_FINBERT:
            try:
                from .finbert_sentiment import FinBERTSentimentAnalyzer
                finbert = FinBERTSentimentAnalyzer.get_instance()
                fb_result = finbert.analyze_texts(tweet_texts)
                finbert_score = fb_result['score']
                breakdown = fb_result['breakdown']
                finbert_ok = True
                print(f"   ✅ FinBERT Twitter Score: {finbert_score:.1f}/100")
                print(f"      Positive: {breakdown.get('positive', 0)} | "
                      f"Negative: {breakdown.get('negative', 0)} | "
                      f"Neutral: {breakdown.get('neutral', 0)}")
            except Exception as e:
                print(f"   ⚠️ FinBERT failed for Twitter: {e}")

        # Fallback to VADER if FinBERT unavailable
        if not finbert_ok:
            try:
                from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
                vader = SentimentIntensityAnalyzer()
                compounds = [vader.polarity_scores(t)['compound'] for t in tweet_texts]
                avg_compound = sum(compounds) / len(compounds)
                finbert_score = (avg_compound + 1) * 50
                breakdown = {
                    'positive': sum(1 for c in compounds if c > 0.05),
                    'negative': sum(1 for c in compounds if c < -0.05),
                    'neutral': sum(1 for c in compounds if -0.05 <= c <= 0.05),
                }
                print(f"   ✅ VADER fallback Twitter Score: {finbert_score:.1f}/100")
            except Exception as e:
                print(f"   ⚠️ VADER fallback also failed: {e} — using LLM scoring")
                # Final fallback: LLM for scoring
                try:
                    resp = self.client.chat.completions.create(
                        model="openai/gpt-oss-120b",
                        messages=[
                            {"role": "system", "content": "You are an objective financial tweet sentiment analyst. Return ONLY valid JSON."},
                            {"role": "user", "content": (
                                f"Score Twitter sentiment for {stock_name} ({stock_symbol}) "
                                f"from these tweets (0=bearish, 50=neutral, 100=bullish).\n\n"
                                f"TWEETS:\n{combined_text[:3000]}\n\n"
                                f'Return: {{"sentiment_score": <0-100>, "positive_pct": <0-100>, '
                                f'"negative_pct": <0-100>, "neutral_pct": <0-100>}}'
                            )},
                        ],
                        temperature=0.1,
                        max_tokens=200,
                    )
                    raw = resp.choices[0].message.content.strip()
                    if "```" in raw:
                        raw = raw.split("```")[1].split("```")[0].strip()
                        if raw.startswith("json"):
                            raw = raw[4:].strip()
                    llm_scores = json.loads(raw)
                    finbert_score = float(llm_scores.get('sentiment_score', 50))
                    n = len(tweet_texts)
                    breakdown = {
                        'positive': int(llm_scores.get('positive_pct', 33) * n / 100),
                        'negative': int(llm_scores.get('negative_pct', 33) * n / 100),
                        'neutral': int(llm_scores.get('neutral_pct', 34) * n / 100),
                    }
                except Exception:
                    pass  # keep defaults

        # Determine label from score
        n_total = len(tweet_texts)
        pos = breakdown.get('positive', 0)
        neg = breakdown.get('negative', 0)
        neu = breakdown.get('neutral', 0)
        positive_pct = (pos / n_total * 100) if n_total else 0
        negative_pct = (neg / n_total * 100) if n_total else 0
        neutral_pct  = (neu / n_total * 100) if n_total else 0

        if finbert_score >= 70:
            sentiment_label = "Strongly Bullish"
        elif finbert_score >= 60:
            sentiment_label = "Bullish"
        elif finbert_score >= 40:
            sentiment_label = "Neutral"
        elif finbert_score >= 30:
            sentiment_label = "Bearish"
        else:
            sentiment_label = "Strongly Bearish"

        # --- LLM for theme/mood extraction only (not scoring) ---
        theme_prompt = f"""Analyze Twitter/X discussions about {stock_name} ({stock_symbol}).

FinBERT Sentiment Score: {finbert_score:.1f}/100 ({sentiment_label})

Sample Tweets:
{combined_text[:3000]}

Extract ONLY:
1. Key Themes (3-5 main topics being discussed)
2. Market Mood Summary (2-3 sentences)

Return ONLY valid JSON:
{{
  "key_themes": ["theme1", "theme2", "theme3"],
  "market_mood": "<2-3 sentence summary>"
}}"""

        try:
            resp = self.client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=[
                    {"role": "system", "content": "Extract key themes from tweets. Do not change the sentiment score."},
                    {"role": "user", "content": theme_prompt},
                ],
                temperature=0.1,
                max_tokens=400,
            )
            raw = resp.choices[0].message.content.strip()
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()
            llm_data = json.loads(raw)
            key_themes = llm_data.get('key_themes', ['Market discussions', 'Stock performance'])
            market_mood = llm_data.get('market_mood', f'Twitter sentiment is {sentiment_label.lower()} based on {n_total} tweets.')
        except Exception as e:
            print(f"   ⚠️ LLM theme extraction failed: {e}")
            key_themes = ['Market discussions', 'Stock performance', 'Investor sentiment']
            market_mood = f'Based on {n_total} tweets, Twitter/X sentiment is {sentiment_label.lower()}.'

        # Engagement stats
        total_engagement = sum(
            t.get('favorites', 0) + t.get('retweets', 0) + t.get('replies', 0) + t.get('quotes', 0)
            for t in tweets_data
        )
        sorted_tweets = sorted(tweets_data, key=lambda x: x.get('favorites', 0) + x.get('retweets', 0), reverse=True)[:5]

        return {
            'sentiment_score': round(finbert_score, 1),
            'sentiment_label': sentiment_label,
            'tweet_count': n_total,
            'positive_percentage': round(positive_pct, 1),
            'negative_percentage': round(negative_pct, 1),
            'neutral_percentage': round(neutral_pct, 1),
            'total_engagement': total_engagement,
            'key_themes': key_themes,
            'market_mood': market_mood,
            'top_tweets': [
                {
                    'text': t['text'][:200],
                    'screen_name': t['screen_name'],
                    'engagement': t.get('favorites', 0) + t.get('retweets', 0)
                }
                for t in sorted_tweets
            ],
            'confidence': 'High' if n_total >= 30 else 'Medium' if n_total >= 15 else 'Low',
            'source': 'rapidapi_twitter_finbert' if finbert_ok else 'rapidapi_twitter_vader_fallback',
            'finbert_result': fb_result if finbert_ok else None,
        }
    
    def analyze_reddit_sentiment_adanos(self, ticker: str) -> Dict:
        """
        Reddit sentiment analysis removed - focusing on Twitter via RapidAPI
        Returns neutral sentiment as placeholder
        """
        print(f"   ℹ️ Reddit sentiment analysis not available (removed Adanos dependency)")
        return self._get_default_social_sentiment("reddit")
    
    def analyze_twitter_sentiment_adanos(self, ticker: str, stock_name: str) -> Dict:
        """
        Legacy method - redirects to RapidAPI implementation
        """
        return self.analyze_twitter_sentiment_rapidapi(ticker, stock_name)
    
    def get_comprehensive_sentiment(self, stock_name: str, stock_symbol: str, 
                                   ticker: Optional[str] = None,
                                   include_reddit: bool = True) -> Dict:
        """
        Get comprehensive sentiment analysis combining all sources
        
        Args:
            stock_name: Company name
            stock_symbol: Stock ticker with exchange (e.g., "RELIANCE.NS")
            ticker: Base ticker for Twitter search (e.g., "RELIANCE", "BAJAJFINSV")
                   If not provided, will extract from stock_symbol
            include_reddit: Include Reddit sentiment analysis (default: True)
        """
        print(f"\n🎯 Starting comprehensive sentiment analysis for {stock_name} ({stock_symbol})...")
        
        # Extract base ticker if not provided
        if not ticker:
            ticker = stock_symbol.split('.')[0]  # Remove .NS, .BO, etc.
        
        # Get sentiment from all sources
        news_sentiment = self.analyze_news_sentiment(stock_name, stock_symbol)
        yahoo_sentiment = self.analyze_yahoo_finance_sentiment(stock_symbol, stock_name)
        twitter_sentiment = self.analyze_twitter_sentiment_rapidapi(ticker, stock_name)
        
        # Get Reddit sentiment if enabled
        reddit_sentiment = None
        if include_reddit:
            try:
                # Use RapidAPI Reddit (working and subscribed)
                from .reddit_sentiment import analyze_reddit_sentiment
                reddit_sentiment = analyze_reddit_sentiment(
                    stock_name, 
                    ticker, 
                    include_comments=False,  # Faster without comments
                    max_posts=50
                )
                print("✅ Reddit sentiment analysis complete (RapidAPI)")
            except Exception as e:
                print(f"⚠️ Reddit sentiment analysis failed: {e}")
                reddit_sentiment = None
        
        # Calculate weighted combined score
        # Weights per spec: News 40%, Yahoo 20%, Reddit 25%, Twitter 15%
        if reddit_sentiment and reddit_sentiment.get('total_posts', 0) > 0:
            # All 4 sources available
            weights = {
                'news': 0.40,
                'yahoo': 0.20,
                'reddit': 0.25,
                'twitter': 0.15,
            }
            combined_score = (
                news_sentiment.get('sentiment_score', 0) * weights['news'] +
                yahoo_sentiment.get('sentiment_score', 0) * weights['yahoo'] +
                reddit_sentiment.get('sentiment_score', 0) * weights['reddit'] +
                twitter_sentiment.get('sentiment_score', 0) * weights['twitter']
            )
        else:
            # 3 sources (no Reddit): News 53%, Yahoo 27%, Twitter 20%
            weights = {
                'news': 0.53,
                'yahoo': 0.27,
                'twitter': 0.20,
            }
            combined_score = (
                news_sentiment.get('sentiment_score', 0) * weights['news'] +
                yahoo_sentiment.get('sentiment_score', 0) * weights['yahoo'] +
                twitter_sentiment.get('sentiment_score', 0) * weights['twitter']
            )
        
        # Determine overall sentiment label (scores are 0-100)
        if combined_score >= 70:
            overall_label = "Strongly Bullish 🚀"
            color = "#10b981"
        elif combined_score >= 60:
            overall_label = "Bullish 📈"
            color = "#34d399"
        elif combined_score >= 40:
            overall_label = "Neutral ⚖️"
            color = "#fbbf24"
        elif combined_score >= 30:
            overall_label = "Bearish 📉"
            color = "#f87171"
        else:
            overall_label = "Strongly Bearish 🔻"
            color = "#ef4444"
        
        # Generate unified sentiment analysis
        final_analysis = self._generate_unified_analysis(
            stock_name,
            stock_symbol,
            news_sentiment,
            yahoo_sentiment,
            twitter_sentiment,
            reddit_sentiment,
            combined_score,
            overall_label
        )
        
        result = {
            'overall_score': round(combined_score, 1),
            'overall_label': overall_label,
            'color': color,
            'news_sentiment': news_sentiment,
            'yahoo_sentiment': yahoo_sentiment,
            'twitter_sentiment': twitter_sentiment,
            'final_analysis': final_analysis,
            'weights': weights,
            'timestamp': datetime.now().isoformat()
        }
        
        if reddit_sentiment:
            result['reddit_sentiment'] = reddit_sentiment
        
        return result
    
    def _generate_unified_analysis(self, stock_name: str, stock_symbol: str,
                                   news_sentiment: Dict, yahoo_sentiment: Dict,
                                   twitter_sentiment: Dict,
                                   reddit_sentiment: Optional[Dict],
                                   combined_score: float, overall_label: str) -> str:
        """Generate unified sentiment analysis using LLM"""
        
        reddit_section = ""
        if reddit_sentiment and reddit_sentiment.get('total_posts', 0) > 0:
            reddit_section = f"""
4. REDDIT SENTIMENT (Weight: 25%)
   - Score: {reddit_sentiment.get('sentiment_score', 0)}
   - Label: {reddit_sentiment.get('sentiment_label', 'N/A')}
   - Posts: {reddit_sentiment.get('total_posts', 0)}
   - Items Analyzed: {reddit_sentiment.get('total_items_analyzed', 0)}
   - Positive: {reddit_sentiment.get('positive_percentage', 0)}% | Negative: {reddit_sentiment.get('negative_percentage', 0)}%
   - Active Subreddits: {', '.join([f"r/{k}" for k in list(reddit_sentiment.get('subreddit_distribution', {}).keys())[:3]])}
   - Key Insights: {', '.join(reddit_sentiment.get('key_insights', [])[:2])}
"""
        
        analysis_prompt = f"""Generate a comprehensive unified sentiment analysis for {stock_name} ({stock_symbol}).

SENTIMENT DATA:
Overall Score: {combined_score:.1f}/100 ({overall_label})

1. YAHOO FINANCE - ANALYST RESEARCH (Weight: 50% - Most Reliable)
   - Score: {yahoo_sentiment.get('sentiment_score', 0)}/100
   - Analyst Rating: {yahoo_sentiment.get('analyst_rating', 'N/A')}
   - Buy: {yahoo_sentiment.get('buy_recommendations', 0)} | Hold: {yahoo_sentiment.get('hold_recommendations', 0)} | Sell: {yahoo_sentiment.get('sell_recommendations', 0)}
   - Institutional Sentiment: {yahoo_sentiment.get('institutional_sentiment', 'N/A')}
   - Time Horizon: LONG-TERM (fundamental analysis)

2. NEWS SENTIMENT - MEDIA COVERAGE (Weight: 30%)
   - Score: {news_sentiment.get('sentiment_score', 0)}/100
   - Label: {news_sentiment.get('sentiment_label', 'N/A')}
   - Articles: {news_sentiment.get('total_articles', 0)}
   - Positive Points: {', '.join(news_sentiment.get('positive_points', [])[:3])}
   - Negative Points: {', '.join(news_sentiment.get('negative_points', [])[:3])}
   - Time Horizon: SHORT-TERM (recent events)

3. TWITTER/X SENTIMENT - SOCIAL MEDIA (Weight: 20%)
   - Score: {twitter_sentiment.get('sentiment_score', 0)}/100
   - Label: {twitter_sentiment.get('sentiment_label', 'N/A')}
   - Tweets: {twitter_sentiment.get('tweet_count', 0)}
   - Positive: {twitter_sentiment.get('positive_percentage', 0)}% | Negative: {twitter_sentiment.get('negative_percentage', 0)}%
   - Key Themes: {', '.join(twitter_sentiment.get('key_themes', [])[:3])}
   - Time Horizon: IMMEDIATE (real-time sentiment)
{reddit_section}

IMPORTANT CONTEXT:
- Yahoo Finance (50% weight) is based on professional analyst research - most reliable for investment decisions
- News (30% weight) reflects recent events and media coverage - short-term focused
- Twitter (20% weight) captures immediate market reactions - can be emotional/reactionary
- Discrepancies between sources are NORMAL and reflect different time horizons
- If Yahoo is bullish but News/Twitter are bearish: Short-term concerns vs long-term opportunity
- If Yahoo is bearish but News/Twitter are bullish: Market may be overoptimistic

Create a professional 4-paragraph unified analysis:
1. Overall Market Sentiment (combining all sources, explain the weighted score)
2. Key Drivers and Themes (what's driving the sentiment across sources)
3. Time Horizon Analysis (explain any discrepancies between short-term news/twitter vs long-term Yahoo analyst views)
4. Unified Outlook and Recommendation (balanced view considering all perspectives)

Be specific, balanced, and actionable. If there are large discrepancies (>40 points), explain why and which source to trust more."""
        
        try:
            response = self.client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=[
                    {"role": "system", "content": "You are a senior market analyst creating unified sentiment reports from multiple data sources."},
                    {"role": "user", "content": analysis_prompt}
                ],
                temperature=0.3,
                max_tokens=1000
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            print(f"❌ Error generating unified analysis: {e}")
            return f"Unified sentiment analysis for {stock_name} shows {overall_label} with a combined score of {combined_score:.1f}/100 across news, Yahoo Finance, and Twitter sources."
    
    def _get_default_sentiment(self) -> Dict:
        """Default sentiment when analysis fails (0-100 scale)"""
        return {
            'sentiment_score': 50,
            'sentiment_label': 'Unavailable',
            'positive_points': ['Insufficient data'],
            'negative_points': ['Insufficient data'],
            'market_mood': 'Unable to determine market sentiment due to insufficient data.',
            'confidence': 'None',
            'news_count': 0,
            'total_articles': 0,
            'positive_count': 0,
            'negative_count': 0,
            'neutral_count': 0,
            'positive_percentage': 0,
            'negative_percentage': 0,
            'neutral_percentage': 0,
            'key_insights': ['News data temporarily unavailable'],
            'news_articles': []
        }
    
    def _get_default_yahoo_sentiment(self) -> Dict:
        """Default Yahoo sentiment when analysis fails (0-100 scale)"""
        return {
            'sentiment_score': 50,
            'analyst_rating': 'N/A',
            'buy_recommendations': 0,
            'hold_recommendations': 0,
            'sell_recommendations': 0,
            'average_price_target': None,
            'institutional_sentiment': 'Neutral',
            'key_insights': ['Insufficient data from Yahoo Finance']
        }
    
    def _get_default_social_sentiment(self, source: str) -> Dict:
        """Default social sentiment when analysis fails (0-100 scale)"""
        return {
            'sentiment_score': 50,
            'sentiment_label': 'Unavailable',
            'mentions': 0 if source == 'reddit' else None,
            'tweet_count': 0 if source == 'twitter' else None,
            'positive_percentage': 0,
            'negative_percentage': 0,
            'neutral_percentage': 0,
            'confidence': 'None',
            'source': f'adanos_{source}',
            'status': 'unavailable'
        }
    
    def _get_news_based_social_sentiment(self, ticker: str, source: str) -> Dict:
        """
        Fallback: Get social sentiment from news articles when Adanos API is unavailable
        This is used for non-US stocks that aren't in Adanos database
        """
        print(f"   📰 Using news-based {source} sentiment (Adanos unavailable for this stock)")
        
        # Search for news about social sentiment
        query = f"{ticker} stock {source} sentiment retail investors social media"
        
        try:
            results, _ = self._search_tavily(query, max_results=5)
            
            if not results:
                return self._get_default_social_sentiment(source)
            
            # Analyze the articles for social sentiment
            articles_text = "\n\n".join([
                f"Title: {article.get('title', '')}\nContent: {article.get('content', '')[:300]}"
                for article in results[:5]
            ])
            
            sentiment_prompt = f"""Analyze {source} sentiment for stock ticker {ticker} based on these news articles.

News Articles:
{articles_text}

Extract {source} sentiment indicators and provide:
1. Sentiment Score (-100 to +100)
2. Sentiment Label (Strongly Bullish/Bullish/Neutral/Bearish/Strongly Bearish)
3. Key insights about {source} discussions

Return ONLY valid JSON:
{{
  "sentiment_score": <number>,
  "sentiment_label": "<label>",
  "key_insights": ["insight1", "insight2"],
  "confidence": "<High/Medium/Low>"
}}"""
            
            response = self.client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=[
                    {"role": "system", "content": f"You are a {source} sentiment analyst. Return ONLY valid JSON."},
                    {"role": "user", "content": sentiment_prompt}
                ],
                temperature=0.2,
                max_tokens=500
            )
            
            result_text = response.choices[0].message.content.strip()
            
            # Clean JSON
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()
            
            sentiment_data = json.loads(result_text)
            
            # Calculate percentages based on sentiment score
            score = sentiment_data.get('sentiment_score', 0)
            if score > 20:
                positive_pct = 60 + (score - 20) * 0.5
                negative_pct = max(10, 40 - (score - 20) * 0.5)
            elif score < -20:
                negative_pct = 60 + abs(score + 20) * 0.5
                positive_pct = max(10, 40 - abs(score + 20) * 0.5)
            else:
                positive_pct = 40 + score * 0.5
                negative_pct = 40 - score * 0.5
            
            neutral_pct = 100 - positive_pct - negative_pct
            
            return {
                'sentiment_score': round(sentiment_data.get('sentiment_score', 0), 1),
                'sentiment_label': sentiment_data.get('sentiment_label', 'Neutral'),
                'mentions': 0 if source == 'reddit' else None,
                'tweet_count': 0 if source == 'twitter' else None,
                'positive_percentage': round(positive_pct, 1),
                'negative_percentage': round(negative_pct, 1),
                'neutral_percentage': round(neutral_pct, 1),
                'key_insights': sentiment_data.get('key_insights', []),
                'confidence': sentiment_data.get('confidence', 'Medium'),
                'source': f'news_based_{source}',
                'explanation': f'Sentiment derived from news articles (Adanos unavailable for {ticker})'
            }
            
        except Exception as e:
            print(f"   ❌ Error in news-based sentiment: {e}")
            return self._get_default_social_sentiment(source)


# Convenience function
def analyze_stock_sentiment(stock_name: str, stock_symbol: str, ticker: Optional[str] = None, 
                           include_reddit: bool = True) -> Dict:
    """
    Convenience function to analyze stock sentiment using RapidAPI for Twitter and Reddit
    
    Args:
        stock_name: Full company name
        stock_symbol: Stock ticker symbol with exchange (e.g., "RELIANCE.NS")
        ticker: Base ticker for RapidAPI Twitter search (optional, will be extracted from stock_symbol)
        include_reddit: Include Reddit sentiment analysis (default: True)
        
    Returns:
        Comprehensive sentiment analysis dictionary
    """
    analyzer = RapidAPISentimentAnalyzer()
    return analyzer.get_comprehensive_sentiment(stock_name, stock_symbol, ticker, include_reddit)
