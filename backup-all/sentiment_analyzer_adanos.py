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
from model_config import get_client
import json
import time

load_dotenv()

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
        
        # Analyze sentiment using LLM
        if all_news:
            news_text = "\n\n".join([
                f"Source: {item['source']}\nTitle: {item['title']}\nContent: {item['content'][:300]}"
                for item in all_news[:15]
            ])
            
            sentiment_prompt = f"""Analyze the sentiment of the following news articles about {stock_name} ({stock_symbol}).

News Articles:
{news_text}

Provide a comprehensive sentiment analysis with:
1. Overall Sentiment Score (-100 to +100, where -100 is extremely bearish, 0 is neutral, +100 is extremely bullish)
2. Sentiment Label (Strongly Bullish, Bullish, Neutral, Bearish, Strongly Bearish)
3. Key Positive Points (3-5 bullet points)
4. Key Negative Points (3-5 bullet points)
5. Market Mood Summary (2-3 sentences)
6. Confidence Level (High/Medium/Low)

Return ONLY valid JSON:
{{
  "sentiment_score": <number between -100 and 100>,
  "sentiment_label": "<label>",
  "positive_points": ["point1", "point2", ...],
  "negative_points": ["point1", "point2", ...],
  "market_mood": "<summary>",
  "confidence": "<High/Medium/Low>",
  "news_count": <number>
}}"""
            
            try:
                response = self.client.chat.completions.create(
                    model="openai/gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are a financial sentiment analysis expert. Analyze news sentiment and return ONLY valid JSON."},
                        {"role": "user", "content": sentiment_prompt}
                    ],
                    temperature=0.1,
                    max_tokens=1000
                )
                
                result_text = response.choices[0].message.content.strip()
                
                # Clean JSON
                if "```json" in result_text:
                    result_text = result_text.split("```json")[1].split("```")[0].strip()
                elif "```" in result_text:
                    result_text = result_text.split("```")[1].split("```")[0].strip()
                
                sentiment_data = json.loads(result_text)
                sentiment_data['news_articles'] = all_news[:10]
                return sentiment_data
                
            except Exception as e:
                print(f"❌ Error analyzing news sentiment: {e}")
                return self._get_default_sentiment()
        
        return self._get_default_sentiment()
    
    def analyze_yahoo_finance_sentiment(self, stock_symbol: str, stock_name: str) -> Dict:
        """Analyze sentiment from Yahoo Finance"""
        print(f"📊 Analyzing Yahoo Finance sentiment for {stock_symbol}...")
        
        query = f"{stock_name} {stock_symbol} site:finance.yahoo.com analyst rating recommendation"
        results, answer = self._search_tavily(query, domains=["finance.yahoo.com"], max_results=5)
        
        if results or answer:
            content = answer + "\n\n" + "\n\n".join([
                f"{r.get('title', '')}\n{r.get('content', '')}"
                for r in results
            ])
            
            sentiment_prompt = f"""Analyze Yahoo Finance sentiment for {stock_name} ({stock_symbol}).

Content:
{content[:3000]}

Extract and analyze:
1. Analyst Ratings (Buy/Hold/Sell recommendations)
2. Price Targets
3. Institutional Sentiment
4. Overall Yahoo Finance Sentiment Score (-100 to +100)
5. Key Insights

Return ONLY valid JSON:
{{
  "sentiment_score": <number>,
  "analyst_rating": "<Buy/Hold/Sell>",
  "buy_recommendations": <number>,
  "hold_recommendations": <number>,
  "sell_recommendations": <number>,
  "average_price_target": <number or null>,
  "institutional_sentiment": "<Positive/Neutral/Negative>",
  "key_insights": ["insight1", "insight2", ...]
}}"""
            
            try:
                response = self.client.chat.completions.create(
                    model="openai/gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are a financial analyst expert. Extract sentiment data and return ONLY valid JSON."},
                        {"role": "user", "content": sentiment_prompt}
                    ],
                    temperature=0.1,
                    max_tokens=800
                )
                
                result_text = response.choices[0].message.content.strip()
                
                # Clean JSON
                if "```json" in result_text:
                    result_text = result_text.split("```json")[1].split("```")[0].strip()
                elif "```" in result_text:
                    result_text = result_text.split("```")[1].split("```")[0].strip()
                
                return json.loads(result_text)
                
            except Exception as e:
                print(f"❌ Error analyzing Yahoo Finance sentiment: {e}")
                return self._get_default_yahoo_sentiment()
        
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
                
        except Exception as e:
            print(f"❌ Error fetching Twitter sentiment from RapidAPI: {e}")
            import traceback
            traceback.print_exc()
            return self._get_default_social_sentiment("twitter")
    
    def _analyze_tweets_sentiment(self, combined_text: str, stock_symbol: str, 
                                  stock_name: str, tweets_data: List[Dict]) -> Dict:
        """
        Analyze sentiment of combined tweet texts using LLM
        
        Args:
            combined_text: Combined text from all tweets
            stock_symbol: Stock ticker
            stock_name: Company name
            tweets_data: List of tweet data dictionaries
            
        Returns:
            Dictionary with sentiment analysis results
        """
        print(f"   🤖 Analyzing sentiment of {len(tweets_data)} tweets using LLM...")
        
        sentiment_prompt = f"""Analyze the Twitter/X sentiment for {stock_name} ({stock_symbol}) based on these recent tweets.

TWEETS:
{combined_text[:4000]}

Provide a comprehensive sentiment analysis with:
1. Overall Sentiment Score (-100 to +100, where -100 is extremely bearish, 0 is neutral, +100 is extremely bullish)
2. Sentiment Label (Strongly Bullish, Bullish, Neutral, Bearish, Strongly Bearish)
3. Positive Percentage (0-100)
4. Negative Percentage (0-100)
5. Neutral Percentage (0-100)
6. Key Themes (3-5 main topics discussed)
7. Market Mood Summary (2-3 sentences)
8. Confidence Level (High/Medium/Low based on tweet quality and quantity)

Return ONLY valid JSON:
{{
  "sentiment_score": <number between -100 and 100>,
  "sentiment_label": "<label>",
  "positive_percentage": <number>,
  "negative_percentage": <number>,
  "neutral_percentage": <number>,
  "key_themes": ["theme1", "theme2", ...],
  "market_mood": "<summary>",
  "confidence": "<High/Medium/Low>"
}}"""
        
        try:
            response = self.client.chat.completions.create(
                model="openai/gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a Twitter sentiment analysis expert specializing in stock market discussions. Analyze sentiment and return ONLY valid JSON."},
                    {"role": "user", "content": sentiment_prompt}
                ],
                temperature=0.1,
                max_tokens=800
            )
            
            result_text = response.choices[0].message.content.strip()
            
            # Clean JSON
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()
            
            sentiment_data = json.loads(result_text)
            
            # Calculate total engagement
            total_engagement = sum(
                tweet.get('favorites', 0) + 
                tweet.get('retweets', 0) + 
                tweet.get('replies', 0) + 
                tweet.get('quotes', 0)
                for tweet in tweets_data
            )
            
            # Get top tweets by engagement
            sorted_tweets = sorted(
                tweets_data, 
                key=lambda x: x.get('favorites', 0) + x.get('retweets', 0),
                reverse=True
            )[:5]
            
            return {
                'sentiment_score': round(sentiment_data.get('sentiment_score', 0), 1),
                'sentiment_label': sentiment_data.get('sentiment_label', 'Neutral'),
                'tweet_count': len(tweets_data),
                'positive_percentage': round(sentiment_data.get('positive_percentage', 0), 1),
                'negative_percentage': round(sentiment_data.get('negative_percentage', 0), 1),
                'neutral_percentage': round(sentiment_data.get('neutral_percentage', 0), 1),
                'total_engagement': total_engagement,
                'key_themes': sentiment_data.get('key_themes', []),
                'market_mood': sentiment_data.get('market_mood', ''),
                'top_tweets': [
                    {
                        'text': tweet['text'][:200],
                        'screen_name': tweet['screen_name'],
                        'engagement': tweet.get('favorites', 0) + tweet.get('retweets', 0)
                    }
                    for tweet in sorted_tweets
                ],
                'confidence': sentiment_data.get('confidence', 'Medium'),
                'source': 'rapidapi_twitter'
            }
            
        except Exception as e:
            print(f"❌ Error analyzing tweet sentiment: {e}")
            import traceback
            traceback.print_exc()
            
            # Return basic sentiment based on tweet count
            return {
                'sentiment_score': 0,
                'sentiment_label': 'Neutral',
                'tweet_count': len(tweets_data),
                'positive_percentage': 33.3,
                'negative_percentage': 33.3,
                'neutral_percentage': 33.3,
                'total_engagement': sum(
                    tweet.get('favorites', 0) + tweet.get('retweets', 0)
                    for tweet in tweets_data
                ),
                'key_themes': ['Unable to analyze'],
                'market_mood': 'Sentiment analysis failed',
                'confidence': 'Low',
                'source': 'rapidapi_twitter'
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
                                   ticker: Optional[str] = None) -> Dict:
        """
        Get comprehensive sentiment analysis combining all sources
        
        Args:
            stock_name: Company name
            stock_symbol: Stock ticker with exchange (e.g., "RELIANCE.NS")
            ticker: Base ticker for Twitter search (e.g., "RELIANCE", "BAJAJFINSV")
                   If not provided, will extract from stock_symbol
        """
        print(f"\n🎯 Starting comprehensive sentiment analysis for {stock_name} ({stock_symbol})...")
        
        # Extract base ticker if not provided
        if not ticker:
            ticker = stock_symbol.split('.')[0]  # Remove .NS, .BO, etc.
        
        # Get sentiment from all sources
        news_sentiment = self.analyze_news_sentiment(stock_name, stock_symbol)
        yahoo_sentiment = self.analyze_yahoo_finance_sentiment(stock_symbol, stock_name)
        twitter_sentiment = self.analyze_twitter_sentiment_rapidapi(ticker, stock_name)
        
        # Calculate weighted combined score
        # News: 40%, Yahoo: 30%, Twitter: 30% (Reddit removed)
        weights = {
            'news': 0.40,
            'yahoo': 0.30,
            'twitter': 0.30
        }
        
        combined_score = (
            news_sentiment.get('sentiment_score', 0) * weights['news'] +
            yahoo_sentiment.get('sentiment_score', 0) * weights['yahoo'] +
            twitter_sentiment.get('sentiment_score', 0) * weights['twitter']
        )
        
        # Determine overall sentiment label
        if combined_score >= 60:
            overall_label = "Strongly Bullish 🚀"
            color = "#10b981"
        elif combined_score >= 20:
            overall_label = "Bullish 📈"
            color = "#34d399"
        elif combined_score >= -20:
            overall_label = "Neutral ⚖️"
            color = "#fbbf24"
        elif combined_score >= -60:
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
            combined_score,
            overall_label
        )
        
        return {
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
    
    def _generate_unified_analysis(self, stock_name: str, stock_symbol: str,
                                   news_sentiment: Dict, yahoo_sentiment: Dict,
                                   twitter_sentiment: Dict,
                                   combined_score: float, overall_label: str) -> str:
        """Generate unified sentiment analysis using LLM"""
        
        analysis_prompt = f"""Generate a comprehensive unified sentiment analysis for {stock_name} ({stock_symbol}).

SENTIMENT DATA:
Overall Score: {combined_score:.1f}/100 ({overall_label})

1. NEWS SENTIMENT (Weight: 40%)
   - Score: {news_sentiment.get('sentiment_score', 0)}
   - Label: {news_sentiment.get('sentiment_label', 'N/A')}
   - Positive Points: {', '.join(news_sentiment.get('positive_points', [])[:3])}
   - Negative Points: {', '.join(news_sentiment.get('negative_points', [])[:3])}

2. YAHOO FINANCE (Weight: 30%)
   - Score: {yahoo_sentiment.get('sentiment_score', 0)}
   - Analyst Rating: {yahoo_sentiment.get('analyst_rating', 'N/A')}
   - Institutional Sentiment: {yahoo_sentiment.get('institutional_sentiment', 'N/A')}

3. TWITTER/X SENTIMENT (Weight: 30%)
   - Score: {twitter_sentiment.get('sentiment_score', 0)}
   - Label: {twitter_sentiment.get('sentiment_label', 'N/A')}
   - Tweets: {twitter_sentiment.get('tweet_count', 0)}
   - Positive: {twitter_sentiment.get('positive_percentage', 0)}% | Negative: {twitter_sentiment.get('negative_percentage', 0)}%
   - Key Themes: {', '.join(twitter_sentiment.get('key_themes', [])[:3])}

Create a professional 4-paragraph unified analysis:
1. Overall Market Sentiment (combining all 3 sources)
2. Key Drivers and Themes (what's driving the sentiment across sources)
3. Institutional vs Retail Perspective (Yahoo/News vs Twitter)
4. Unified Outlook and Recommendation

Be specific, balanced, and actionable. Highlight consensus and divergences across sources."""
        
        try:
            response = self.client.chat.completions.create(
                model="openai/gpt-4o-mini",
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
        """Default sentiment when analysis fails"""
        return {
            'sentiment_score': 0,
            'sentiment_label': 'Neutral',
            'positive_points': ['Insufficient data'],
            'negative_points': ['Insufficient data'],
            'market_mood': 'Unable to determine market sentiment due to insufficient data.',
            'confidence': 'Low',
            'news_count': 0,
            'news_articles': []
        }
    
    def _get_default_yahoo_sentiment(self) -> Dict:
        """Default Yahoo sentiment when analysis fails"""
        return {
            'sentiment_score': 0,
            'analyst_rating': 'N/A',
            'buy_recommendations': 0,
            'hold_recommendations': 0,
            'sell_recommendations': 0,
            'average_price_target': None,
            'institutional_sentiment': 'Neutral',
            'key_insights': ['Insufficient data from Yahoo Finance']
        }
    
    def _get_default_social_sentiment(self, source: str) -> Dict:
        """Default social sentiment when analysis fails"""
        return {
            'sentiment_score': 0,
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
                model="openai/gpt-4o-mini",
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
def analyze_stock_sentiment(stock_name: str, stock_symbol: str, ticker: Optional[str] = None) -> Dict:
    """
    Convenience function to analyze stock sentiment using RapidAPI for Twitter
    
    Args:
        stock_name: Full company name
        stock_symbol: Stock ticker symbol with exchange (e.g., "RELIANCE.NS")
        ticker: Base ticker for RapidAPI Twitter search (optional, will be extracted from stock_symbol)
        
    Returns:
        Comprehensive sentiment analysis dictionary
    """
    analyzer = RapidAPISentimentAnalyzer()
    return analyzer.get_comprehensive_sentiment(stock_name, stock_symbol, ticker)
