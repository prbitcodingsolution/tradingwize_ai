# -*- coding: utf-8 -*-
"""
Sentiment Analysis Module for Stock Market
Analyzes sentiment from news sources, social media, and Yahoo Finance
"""

import requests
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
from model_config import get_client
import json
import time
import re
import pandas as pd

# Twitter scraping - Use compatible library for Python 3.12+
TWITTER_AVAILABLE = False
TWITTER_METHOD = None

# Try ntscraper first (Python 3.12+ compatible)
try:
    from ntscraper import Nitter
    TWITTER_AVAILABLE = True
    TWITTER_METHOD = 'ntscraper'
    print("✅ Using ntscraper for Twitter sentiment (Python 3.12+ compatible)")
except ImportError:
    # Try snscrape (Python 3.8-3.11 only)
    try:
        import snscrape.modules.twitter as sntwitter
        TWITTER_AVAILABLE = True
        TWITTER_METHOD = 'snscrape'
        print("✅ Using snscrape for Twitter sentiment")
    except (ImportError, AttributeError) as e:
        TWITTER_AVAILABLE = False
        TWITTER_METHOD = None
        if isinstance(e, AttributeError):
            print("⚠️ snscrape is incompatible with your Python version.")
            print("   Installing ntscraper for Twitter sentiment...")
            print("   Run: pip install ntscraper")
        else:
            print("⚠️ No Twitter scraping library installed.")
            print("   Run: pip install ntscraper")

# Sentiment analysis libraries
try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    VADER_AVAILABLE = True
except ImportError:
    VADER_AVAILABLE = False
    print("⚠️ vaderSentiment not installed. Using LLM for Twitter sentiment.")

try:
    from transformers import pipeline
    FINBERT_AVAILABLE = True
except ImportError:
    FINBERT_AVAILABLE = False
    print("⚠️ transformers not installed. FinBERT sentiment disabled.")

load_dotenv()

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")


class SentimentAnalyzer:
    """
    Comprehensive sentiment analysis for stocks using multiple sources:
    1. News sources (CNBC, Financial Express, Business Standard, NSE India, LiveMint)
    2. Yahoo Finance
    3. Twitter/X (social media sentiment)
    """
    
    def __init__(self, use_finbert: bool = False):
        self.client = get_client()
        self.news_sources = [
            "cnbc.com",
            "financialexpress.com", 
            "business-standard.com",
            "nseindia.com",
            "livemint.com",
            "moneycontrol.com",
            "economictimes.indiatimes.com",
            "https://www.forexfactory.com",
            "https://www.myfxbook.com/community/outlook"
            
        ]
        
        # Initialize sentiment analyzers
        self.vader_analyzer = SentimentIntensityAnalyzer() if VADER_AVAILABLE else None
        self.finbert_model = None
        
        if use_finbert and FINBERT_AVAILABLE:
            try:
                print("🔄 Loading FinBERT model...")
                self.finbert_model = pipeline("sentiment-analysis", model="ProsusAI/finbert")
                print("✅ FinBERT loaded successfully")
            except Exception as e:
                print(f"⚠️ Failed to load FinBERT: {e}")
                self.finbert_model = None
    
    def _search_tavily(self, query: str, domains: Optional[List[str]] = None, max_results: int = 10) -> Tuple[List[Dict], str]:
        """
        Search using Tavily API with specific domains
        """
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
        """
        Analyze sentiment from news sources
        """
        print(f"📰 Analyzing news sentiment for {stock_name}...")
        
        # Search for recent news from multiple sources
        query = f"{stock_name} {stock_symbol} stock news latest updates"
        
        all_news = []
        
        # Search each news source
        for source in self.news_sources:
            try:
                results, _ = self._search_tavily(query, domains=[source], max_results=3)
                for result in results:
                    all_news.append({
                        'title': result.get('title', ''),
                        'content': result.get('content', ''),
                        'url': result.get('url', ''),
                        'source': source,
                        'published_date': result.get('published_date', '')
                    })
                time.sleep(0.5)  # Rate limiting
            except Exception as e:
                print(f"⚠️ Error fetching from {source}: {e}")
        
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
        """
        Analyze sentiment from Yahoo Finance discussions and analyst ratings
        """
        print(f"📊 Analyzing Yahoo Finance sentiment for {stock_symbol}...")
        
        # Search Yahoo Finance for sentiment indicators
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
    
    def _clean_tweet_text(self, text: str) -> str:
        """
        Clean tweet text by removing URLs, mentions, hashtags, and extra whitespace
        """
        # Remove URLs
        text = re.sub(r'http\S+|www\S+|https\S+', '', text, flags=re.MULTILINE)
        # Remove mentions
        text = re.sub(r'@\w+', '', text)
        # Remove hashtags (keep the text, remove #)
        text = re.sub(r'#', '', text)
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    
    def fetch_tweets(self, stock_name: str, stock_symbol: str, 
                    since_date: Optional[str] = None, limit: int = 200) -> pd.DataFrame:
        """
        Fetch tweets about a specific stock using available Twitter scraping library
        
        Args:
            stock_name: Company name
            stock_symbol: Stock ticker
            since_date: Start date in YYYY-MM-DD format (default: 7 days ago)
            limit: Maximum number of tweets to fetch
            
        Returns:
            DataFrame with tweets
        """
        if not TWITTER_AVAILABLE:
            print("❌ Twitter scraping not available.")
            print("   Install ntscraper: pip install ntscraper")
            return pd.DataFrame()
        
        if since_date is None:
            since_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        
        print(f"🐦 Fetching tweets for {stock_name} ({stock_symbol}) using {TWITTER_METHOD}...")
        
        all_tweets = []
        
        if TWITTER_METHOD == 'ntscraper':
            # Use ntscraper (Python 3.12+ compatible)
            all_tweets = self._fetch_tweets_ntscraper(stock_name, stock_symbol, limit)
        elif TWITTER_METHOD == 'snscrape':
            # Use snscrape (Python 3.8-3.11)
            all_tweets = self._fetch_tweets_snscrape(stock_name, stock_symbol, since_date, limit)
        
        if not all_tweets:
            print("⚠️ No tweets found")
            return pd.DataFrame()
        
        df = pd.DataFrame(all_tweets)
        
        # Remove duplicates
        df = df.drop_duplicates(subset=['content'])
        
        # Clean tweet text
        df['cleaned'] = df['content'].apply(self._clean_tweet_text)
        
        # Filter out very short tweets
        df = df[df['cleaned'].str.len() > 20]
        
        print(f"✅ Fetched {len(df)} unique tweets")
        return df
    
    def _fetch_tweets_ntscraper(self, stock_name: str, stock_symbol: str, limit: int = 200) -> List[Dict]:
        """
        Fetch tweets using ntscraper (Python 3.12+ compatible)
        """
        try:
            from ntscraper import Nitter
            
            scraper = Nitter(log_level=1, skip_instance_check=False)
            
            # Build search queries
            queries = [
                f"{stock_name} {stock_symbol}",
                f"${stock_symbol}",
                f"#{stock_symbol}",
                f"{stock_symbol} stock"
            ]
            
            all_tweets = []
            
            for query in queries:
                try:
                    print(f"   Searching: {query}")
                    tweets = scraper.get_tweets(query, mode='term', number=limit // len(queries))
                    
                    if tweets and 'tweets' in tweets:
                        for tweet in tweets['tweets']:
                            all_tweets.append({
                                "date": datetime.now(),  # ntscraper doesn't always provide dates
                                "content": tweet.get('text', ''),
                                "username": tweet.get('user', {}).get('name', 'Unknown'),
                                "likes": tweet.get('stats', {}).get('likes', 0),
                                "retweets": tweet.get('stats', {}).get('retweets', 0),
                                "replies": tweet.get('stats', {}).get('comments', 0)
                            })
                    
                    time.sleep(2)  # Rate limiting
                    
                except Exception as e:
                    print(f"   ⚠️ Error with query '{query}': {e}")
                    continue
            
            return all_tweets
            
        except Exception as e:
            print(f"❌ ntscraper error: {e}")
            return []
    
    def _fetch_tweets_snscrape(self, stock_name: str, stock_symbol: str, 
                               since_date: str, limit: int = 200) -> List[Dict]:
        """
        Fetch tweets using snscrape (Python 3.8-3.11 only)
        """
        try:
            import snscrape.modules.twitter as sntwitter
            
            # Build search query with multiple variations
            queries = [
                f'("{stock_name}" OR ${stock_symbol} OR #{stock_symbol}) since:{since_date} lang:en',
                f'{stock_symbol} stock since:{since_date} lang:en'
            ]
            
            all_tweets = []
            
            for query in queries:
                try:
                    tweet_count = 0
                    for tweet in sntwitter.TwitterSearchScraper(query).get_items():
                        all_tweets.append({
                            "date": tweet.date,
                            "content": tweet.content,
                            "username": tweet.user.username,
                            "likes": tweet.likeCount,
                            "retweets": tweet.retweetCount,
                            "replies": tweet.replyCount
                        })
                        tweet_count += 1
                        if tweet_count >= limit // len(queries):
                            break
                    
                    time.sleep(1)  # Rate limiting
                    
                except Exception as e:
                    print(f"⚠️ Error fetching tweets with query '{query}': {e}")
            
            return all_tweets
            
        except Exception as e:
            print(f"❌ snscrape error: {e}")
            return []
    
    def _analyze_tweet_sentiment_vader(self, text: str) -> Tuple[str, float]:
        """
        Analyze sentiment using VADER (fast, good for social media)
        
        Returns:
            Tuple of (sentiment_label, score)
        """
        if not self.vader_analyzer:
            return "Neutral", 0.0
        
        score = self.vader_analyzer.polarity_scores(text)["compound"]
        
        if score >= 0.05:
            label = "Positive"
        elif score <= -0.05:
            label = "Negative"
        else:
            label = "Neutral"
        
        return label, score
    
    def _analyze_tweet_sentiment_finbert(self, text: str) -> Tuple[str, float]:
        """
        Analyze sentiment using FinBERT (more accurate for financial content)
        
        Returns:
            Tuple of (sentiment_label, score)
        """
        if not self.finbert_model:
            return self._analyze_tweet_sentiment_vader(text)
        
        try:
            # FinBERT has max length of 512 tokens
            result = self.finbert_model(text[:512])[0]
            label = result['label']  # positive, negative, neutral
            score = result['score']
            
            # Convert to standardized format
            if label.lower() == 'positive':
                return "Positive", score
            elif label.lower() == 'negative':
                return "Negative", -score
            else:
                return "Neutral", 0.0
                
        except Exception as e:
            print(f"⚠️ FinBERT error: {e}")
            return self._analyze_tweet_sentiment_vader(text)
    
    def analyze_twitter_sentiment(self, stock_name: str, stock_symbol: str, 
                                  use_finbert: bool = False) -> Dict:
        """
        Analyze social media sentiment (Twitter/X alternative using news-based social sentiment)
        
        Since Twitter scraping is unreliable, we use news articles that discuss
        social media sentiment, retail investor mood, and market buzz as a proxy.
        
        Args:
            stock_name: Company name
            stock_symbol: Stock ticker
            use_finbert: Not used in this implementation
            
        Returns:
            Dictionary with social sentiment analysis
        """
        print(f"🐦 Analyzing social media sentiment for {stock_name}...")
        
        # Try actual Twitter scraping first
        if TWITTER_AVAILABLE:
            print(f"   Attempting to fetch tweets using {TWITTER_METHOD}...")
            df = self.fetch_tweets(stock_name, stock_symbol, limit=200)
            
            if not df.empty:
                # Successfully got tweets - use them
                return self._analyze_tweets_dataframe(df, stock_name, stock_symbol, use_finbert)
        
        # Fallback: Use news-based social sentiment analysis
        print("   📰 Using news-based social sentiment analysis (Twitter alternative)...")
        return self._analyze_social_sentiment_from_news(stock_name, stock_symbol)
    
    def _analyze_tweets_dataframe(self, df: pd.DataFrame, stock_name: str, 
                                  stock_symbol: str, use_finbert: bool = False) -> Dict:
        """
        Analyze sentiment from actual tweets DataFrame
        """
        # Analyze sentiment for each tweet
        if use_finbert and self.finbert_model:
            print("🤖 Using FinBERT for sentiment analysis...")
            sentiments = df['cleaned'].apply(lambda x: self._analyze_tweet_sentiment_finbert(x))
        else:
            print("⚡ Using VADER for sentiment analysis...")
            sentiments = df['cleaned'].apply(lambda x: self._analyze_tweet_sentiment_vader(x))
        
        df['sentiment_label'] = sentiments.apply(lambda x: x[0])
        df['sentiment_score'] = sentiments.apply(lambda x: x[1])
        
        # Calculate statistics
        total_tweets = len(df)
        positive_count = len(df[df['sentiment_label'] == 'Positive'])
        negative_count = len(df[df['sentiment_label'] == 'Negative'])
        neutral_count = len(df[df['sentiment_label'] == 'Neutral'])
        
        positive_pct = (positive_count / total_tweets * 100) if total_tweets > 0 else 0
        negative_pct = (negative_count / total_tweets * 100) if total_tweets > 0 else 0
        neutral_pct = (neutral_count / total_tweets * 100) if total_tweets > 0 else 0
        
        # Calculate weighted sentiment score (-100 to +100)
        avg_score = df['sentiment_score'].mean()
        sentiment_score = avg_score * 100
        
        # Get most engaging tweets
        df['engagement'] = df['likes'] + df['retweets'] * 2
        top_tweets = df.nlargest(5, 'engagement')[['content', 'sentiment_label', 'likes', 'retweets']].to_dict('records')
        
        # Determine overall sentiment label
        if sentiment_score >= 30:
            overall_label = "Strongly Bullish"
        elif sentiment_score >= 10:
            overall_label = "Bullish"
        elif sentiment_score >= -10:
            overall_label = "Neutral"
        elif sentiment_score >= -30:
            overall_label = "Bearish"
        else:
            overall_label = "Strongly Bearish"
        
        # Generate insights
        insights = self._generate_twitter_insights(
            stock_name, stock_symbol, df, sentiment_score, overall_label
        )
        
        return {
            'sentiment_score': round(sentiment_score, 1),
            'sentiment_label': overall_label,
            'total_tweets': total_tweets,
            'positive_count': positive_count,
            'negative_count': negative_count,
            'neutral_count': neutral_count,
            'positive_percentage': round(positive_pct, 1),
            'negative_percentage': round(negative_pct, 1),
            'neutral_percentage': round(neutral_pct, 1),
            'top_tweets': top_tweets,
            'key_insights': insights,
            'confidence': 'High' if total_tweets >= 50 else 'Medium' if total_tweets >= 20 else 'Low',
            'source': 'twitter'
        }
    
    def _analyze_social_sentiment_from_news(self, stock_name: str, stock_symbol: str) -> Dict:
        """
        Analyze social media sentiment using news articles as a proxy
        
        This searches for news articles that discuss:
        - Social media buzz
        - Retail investor sentiment
        - Market mood
        - Trading activity
        """
        print(f"   Searching for social sentiment indicators in news...")
        
        # Search for news about social sentiment, retail investors, market buzz
        queries = [
            f"{stock_name} {stock_symbol} retail investors sentiment social media",
            f"{stock_name} {stock_symbol} market buzz trading activity",
            f"{stock_name} {stock_symbol} investor mood retail sentiment"
        ]
        
        all_articles = []
        
        for query in queries:
            try:
                results, _ = self._search_tavily(query, max_results=5)
                all_articles.extend(results)
                time.sleep(0.5)
            except Exception as e:
                print(f"   ⚠️ Error searching: {e}")
                continue
        
        if not all_articles:
            print("   ⚠️ No social sentiment data found")
            return self._get_default_twitter_sentiment()
        
        # Analyze the articles for social sentiment indicators
        articles_text = "\n\n".join([
            f"Title: {article.get('title', '')}\nContent: {article.get('content', '')[:500]}"
            for article in all_articles[:10]
        ])
        
        sentiment_prompt = f"""Analyze social media and retail investor sentiment for {stock_name} ({stock_symbol}) based on these news articles.

News Articles:
{articles_text}

Extract and analyze:
1. Social Media Sentiment (what are retail investors saying on Twitter, Reddit, forums?)
2. Retail Investor Mood (bullish, bearish, neutral?)
3. Market Buzz Level (high, medium, low?)
4. Trading Activity Sentiment (buying pressure, selling pressure?)
5. Overall Social Sentiment Score (-100 to +100)

Focus on indicators like:
- "Retail investors are buying/selling"
- "Social media buzz around"
- "Trending on Twitter/Reddit"
- "Retail sentiment is positive/negative"
- "Individual investors are optimistic/pessimistic"

Return ONLY valid JSON:
{{
  "sentiment_score": <number between -100 and 100>,
  "sentiment_label": "<Strongly Bullish/Bullish/Neutral/Bearish/Strongly Bearish>",
  "positive_indicators": ["indicator1", "indicator2"],
  "negative_indicators": ["indicator1", "indicator2"],
  "market_buzz": "<High/Medium/Low>",
  "retail_mood": "<description>",
  "key_insights": ["insight1", "insight2", "insight3"],
  "confidence": "<High/Medium/Low>"
}}"""
        
        try:
            response = self.client.chat.completions.create(
                model="openai/gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a social media sentiment analyst. Analyze retail investor sentiment from news articles and return ONLY valid JSON."},
                    {"role": "user", "content": sentiment_prompt}
                ],
                temperature=0.2,
                max_tokens=800
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
            
            # Create simulated social sentiment data
            return {
                'sentiment_score': round(sentiment_data.get('sentiment_score', 0), 1),
                'sentiment_label': sentiment_data.get('sentiment_label', 'Neutral'),
                'total_tweets': 0,  # Indicate this is news-based
                'positive_count': 0,
                'negative_count': 0,
                'neutral_count': 0,
                'positive_percentage': round(positive_pct, 1),
                'negative_percentage': round(negative_pct, 1),
                'neutral_percentage': round(neutral_pct, 1),
                'top_tweets': [],
                'key_insights': sentiment_data.get('key_insights', []),
                'confidence': sentiment_data.get('confidence', 'Medium'),
                'source': 'news_based_social_sentiment',
                'market_buzz': sentiment_data.get('market_buzz', 'Medium'),
                'retail_mood': sentiment_data.get('retail_mood', 'Mixed')
            }
            
        except Exception as e:
            print(f"   ❌ Error analyzing social sentiment: {e}")
            return self._get_default_twitter_sentiment()
    
    def _generate_twitter_insights(self, stock_name: str, stock_symbol: str,
                                   df: pd.DataFrame, sentiment_score: float,
                                   overall_label: str) -> List[str]:
        """
        Generate insights from Twitter sentiment using LLM
        """
        # Get sample tweets from each sentiment category
        positive_samples = df[df['sentiment_label'] == 'Positive']['cleaned'].head(3).tolist()
        negative_samples = df[df['sentiment_label'] == 'Negative']['cleaned'].head(3).tolist()
        
        insight_prompt = f"""Analyze Twitter sentiment for {stock_name} ({stock_symbol}).

Overall Sentiment: {overall_label} (Score: {sentiment_score:.1f}/100)
Total Tweets Analyzed: {len(df)}

Sample Positive Tweets:
{chr(10).join(['- ' + t for t in positive_samples])}

Sample Negative Tweets:
{chr(10).join(['- ' + t for t in negative_samples])}

Generate 4-5 key insights about:
1. Main themes in positive sentiment
2. Main concerns in negative sentiment
3. Retail investor mood
4. Social media momentum
5. Any notable trends or patterns

Return as JSON array of strings:
["insight1", "insight2", "insight3", ...]"""
        
        try:
            response = self.client.chat.completions.create(
                model="openai/gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a social media sentiment analyst. Extract key insights and return ONLY a JSON array."},
                    {"role": "user", "content": insight_prompt}
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
            
            insights = json.loads(result_text)
            return insights if isinstance(insights, list) else []
            
        except Exception as e:
            print(f"⚠️ Error generating Twitter insights: {e}")
            return [
                f"Twitter sentiment is {overall_label.lower()} with {len(df)} tweets analyzed",
                f"Positive sentiment: {len(df[df['sentiment_label'] == 'Positive'])} tweets",
                f"Negative sentiment: {len(df[df['sentiment_label'] == 'Negative'])} tweets"
            ]
    
    def get_comprehensive_sentiment(self, stock_name: str, stock_symbol: str, 
                                   include_twitter: bool = True,
                                   use_finbert: bool = False) -> Dict:
        """
        Get comprehensive sentiment analysis combining all sources
        
        Args:
            stock_name: Company name
            stock_symbol: Stock ticker
            include_twitter: Include Twitter/X sentiment analysis
            use_finbert: Use FinBERT for Twitter sentiment (slower but more accurate)
        """
        print(f"\n🎯 Starting comprehensive sentiment analysis for {stock_name} ({stock_symbol})...")
        
        # Get sentiment from different sources
        news_sentiment = self.analyze_news_sentiment(stock_name, stock_symbol)
        yahoo_sentiment = self.analyze_yahoo_finance_sentiment(stock_symbol, stock_name)
        
        twitter_sentiment = None
        if include_twitter:
            twitter_sentiment = self.analyze_twitter_sentiment(stock_name, stock_symbol, use_finbert)
            # Always include social sentiment (either from Twitter or news-based)
            if twitter_sentiment.get('source') == 'news_based_social_sentiment':
                print("✅ Using news-based social sentiment analysis")
        
        # Combine sentiments with weights
        if twitter_sentiment and (twitter_sentiment.get('total_tweets', 0) > 0 or twitter_sentiment.get('source') == 'news_based_social_sentiment'):
            # Three sources: News (40%), Yahoo (30%), Social/Twitter (30%)
            combined_score = (
                news_sentiment.get('sentiment_score', 0) * 0.4 + 
                yahoo_sentiment.get('sentiment_score', 0) * 0.3 +
                twitter_sentiment.get('sentiment_score', 0) * 0.3
            )
        else:
            # Two sources: News (60%), Yahoo (40%)
            combined_score = (
                news_sentiment.get('sentiment_score', 0) * 0.6 + 
                yahoo_sentiment.get('sentiment_score', 0) * 0.4
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
        
        # Generate final analysis
        final_analysis = self._generate_final_analysis(
            stock_name, 
            stock_symbol,
            news_sentiment, 
            yahoo_sentiment,
            twitter_sentiment,
            combined_score,
            overall_label
        )
        
        result = {
            'overall_score': round(combined_score, 1),
            'overall_label': overall_label,
            'color': color,
            'news_sentiment': news_sentiment,
            'yahoo_sentiment': yahoo_sentiment,
            'final_analysis': final_analysis,
            'timestamp': datetime.now().isoformat()
        }
        
        if twitter_sentiment:
            result['twitter_sentiment'] = twitter_sentiment
        
        return result
    
    def _generate_final_analysis(self, stock_name: str, stock_symbol: str, 
                                 news_sentiment: Dict, yahoo_sentiment: Dict,
                                 twitter_sentiment: Optional[Dict],
                                 combined_score: float, overall_label: str) -> str:
        """
        Generate final comprehensive analysis using LLM
        """
        twitter_section = ""
        if twitter_sentiment and twitter_sentiment.get('total_tweets', 0) > 0:
            twitter_section = f"""
- Twitter Sentiment Score: {twitter_sentiment.get('sentiment_score', 0)}
- Twitter Sentiment: {twitter_sentiment.get('sentiment_label', 'N/A')}
- Total Tweets Analyzed: {twitter_sentiment.get('total_tweets', 0)}
- Positive: {twitter_sentiment.get('positive_percentage', 0)}% | Negative: {twitter_sentiment.get('negative_percentage', 0)}% | Neutral: {twitter_sentiment.get('neutral_percentage', 0)}%

Twitter Insights:
{chr(10).join(['- ' + i for i in twitter_sentiment.get('key_insights', [])])}
"""
        
        analysis_prompt = f"""Generate a comprehensive sentiment analysis report for {stock_name} ({stock_symbol}).

Data:
- Overall Sentiment Score: {combined_score:.1f}/100
- Overall Label: {overall_label}
- News Sentiment Score: {news_sentiment.get('sentiment_score', 0)}
- News Sentiment: {news_sentiment.get('sentiment_label', 'N/A')}
- Yahoo Finance Sentiment: {yahoo_sentiment.get('sentiment_score', 0)}
- Analyst Rating: {yahoo_sentiment.get('analyst_rating', 'N/A')}
{twitter_section}

News Positive Points:
{chr(10).join(['- ' + p for p in news_sentiment.get('positive_points', [])])}

News Negative Points:
{chr(10).join(['- ' + p for p in news_sentiment.get('negative_points', [])])}

Yahoo Insights:
{chr(10).join(['- ' + i for i in yahoo_sentiment.get('key_insights', [])])}

Create a professional 4-paragraph analysis covering:
1. Overall Market Sentiment Summary (including social media if available)
2. Key Drivers (Positive and Negative)
3. Investor Mood and Market Psychology (institutional + retail)
4. Short-term Outlook and Recommendations

Write in a professional, balanced tone. Be specific and actionable."""
        
        try:
            response = self.client.chat.completions.create(
                model="openai/gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a senior financial analyst writing sentiment reports."},
                    {"role": "user", "content": analysis_prompt}
                ],
                temperature=0.3,
                max_tokens=800
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            print(f"❌ Error generating final analysis: {e}")
            return f"Sentiment analysis for {stock_name} shows {overall_label} with a score of {combined_score:.1f}/100."
    
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
    
    def _get_default_twitter_sentiment(self) -> Dict:
        """Default Twitter sentiment when analysis fails"""
        return {
            'sentiment_score': 0,
            'sentiment_label': 'Unavailable',
            'total_tweets': 0,
            'positive_count': 0,
            'negative_count': 0,
            'neutral_count': 0,
            'positive_percentage': 0,
            'negative_percentage': 0,
            'neutral_percentage': 0,
            'top_tweets': [],
            'key_insights': [
                'Twitter data temporarily unavailable',
                'This could be due to network issues or Nitter instance availability',
                'Sentiment analysis continues with News and Yahoo Finance data'
            ],
            'confidence': 'None',
            'status': 'unavailable'
        }


# Convenience function for easy import
def analyze_stock_sentiment(stock_name: str, stock_symbol: str, 
                           include_twitter: bool = True,
                           use_finbert: bool = False) -> Dict:
    """
    Convenience function to analyze stock sentiment
    
    Args:
        stock_name: Full company name
        stock_symbol: Stock ticker symbol
        include_twitter: Include Twitter/X sentiment analysis (default: True)
        use_finbert: Use FinBERT for Twitter sentiment instead of VADER (default: False)
        
    Returns:
        Comprehensive sentiment analysis dictionary
    """
    analyzer = SentimentAnalyzer(use_finbert=use_finbert)
    return analyzer.get_comprehensive_sentiment(stock_name, stock_symbol, include_twitter, use_finbert)
