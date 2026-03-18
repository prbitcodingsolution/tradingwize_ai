# -*- coding: utf-8 -*-
"""
Reddit Sentiment Analysis Module using RapidAPI
Analyzes sentiment from Reddit posts about stocks
Similar approach to Twitter sentiment analysis
"""

import requests
import json
import os
from typing import Dict, List, Optional
from datetime import datetime
from dotenv import load_dotenv
from .model_config import get_client
import time

load_dotenv()

# RapidAPI credentials
REDDIT_RAPIDAPI_KEY = os.getenv("REDDIT_RAPIDAPI_KEY")
REDDIT_RAPIDAPI_HOST = os.getenv("REDDIT_RAPIDAPI_HOST")


class RedditSentimentAnalyzer:
    """
    Analyze sentiment from Reddit posts about stocks using RapidAPI
    Uses VADER for objective sentiment scoring + LLM for context
    """
    
    def __init__(self):
        self.client = get_client()
        self.api_key = REDDIT_RAPIDAPI_KEY
        self.api_host = REDDIT_RAPIDAPI_HOST
        
        # Try to import VADER
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
            self.vader_analyzer = SentimentIntensityAnalyzer()
            self.vader_available = True
        except ImportError:
            self.vader_analyzer = None
            self.vader_available = False
            print("⚠️ VADER not installed. Using LLM for Reddit sentiment.")
    
    def _normalize_sentiment_score(self, score: float) -> float:
        """
        Normalize sentiment score to 0-100 range.
        Handles cases where LLM might return -100 to +100 scores.
        
        Args:
            score: Raw sentiment score (could be -100 to +100 or 0 to 100)
            
        Returns:
            Normalized score in 0-100 range
        """
        # If score is negative or > 100, it's likely in -100 to +100 range
        if score < 0 or score > 100:
            # Convert from -100/+100 to 0-100
            score = (score + 100) / 2
        
        # Clamp to 0-100 range
        return max(0, min(100, score))
    
    def search_reddit_posts(self, stock_symbol: str, stock_name: str, 
                           subreddits: Optional[List[str]] = None,
                           max_posts: int = 50) -> List[Dict]:
        """
        Search ALL of Reddit for posts about a stock using RapidAPI Reddit34
        Uses /getSearchPosts endpoint to search across all subreddits
        
        Args:
            stock_symbol: Stock ticker (e.g., "GME", "TSLA", "INFY")
            stock_name: Company name
            subreddits: Not used (kept for compatibility)
            max_posts: Maximum posts to fetch
            
        Returns:
            List of Reddit posts with text and metadata
        """
        if not self.api_key or not self.api_host:
            print("⚠️ REDDIT_RAPIDAPI_KEY or REDDIT_RAPIDAPI_HOST not configured")
            return []
        
        print(f"🔍 Searching ALL of Reddit for {stock_symbol} posts...")
        
        all_posts = []
        
        try:
            # Use RapidAPI Reddit34 /getSearchPosts endpoint
            # This searches ALL of Reddit, not limited to specific subreddits
            url = f"https://{self.api_host}/getSearchPosts"
            
            headers = {
                "X-RapidAPI-Key": self.api_key,
                "X-RapidAPI-Host": self.api_host
            }
            
            # Search for stock symbol (try with and without $)
            # Example: "GME" or "$GME" or "TSLA" or "$TSLA"
            query = stock_symbol
            
            params = {
                "query": query
            }
            
            print(f"   📡 Searching Reddit for: {query}")
            print(f"   🌐 Endpoint: /getSearchPosts (searches ALL subreddits)")
            
            response = requests.get(url, headers=headers, params=params, timeout=15)
            print(f"   📊 Response status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('success') and 'data' in data:
                    posts_data = data['data'].get('posts', [])
                    
                    print(f"   ✅ Found {len(posts_data)} posts from Reddit search")
                    
                    # Extract post data
                    for post_item in posts_data[:max_posts]:  # Limit to max_posts
                        post_data = post_item.get('data', {})
                        
                        all_posts.append({
                            'title': post_data.get('title', ''),
                            'text': post_data.get('selftext', ''),
                            'subreddit': post_data.get('subreddit', ''),
                            'author': post_data.get('author', ''),
                            'score': post_data.get('score', 0),
                            'upvote_ratio': post_data.get('upvote_ratio', 0),
                            'num_comments': post_data.get('num_comments', 0),
                            'created_utc': post_data.get('created_utc', 0),
                            'permalink': post_data.get('permalink', ''),
                            'id': post_data.get('id', '')
                        })
                    
                    # Show subreddit distribution
                    if all_posts:
                        subreddit_counts = {}
                        for post in all_posts:
                            sub = post['subreddit']
                            subreddit_counts[sub] = subreddit_counts.get(sub, 0) + 1
                        
                        print(f"   📊 Posts found across {len(subreddit_counts)} subreddits:")
                        for sub, count in sorted(subreddit_counts.items(), key=lambda x: x[1], reverse=True)[:5]:
                            print(f"      • r/{sub}: {count} posts")
                
                else:
                    print(f"   ⚠️ Invalid response format from Reddit API")
            
            elif response.status_code == 429:
                print(f"   ⚠️ Reddit API rate limit exceeded (429)")
                print("      This is normal for RapidAPI free tier")
            else:
                print(f"   ⚠️ Reddit API error: {response.status_code}")
                try:
                    error_data = response.json()
                    print(f"      Error details: {error_data}")
                except:
                    print(f"      Response text: {response.text[:200]}")
            
        except Exception as e:
            print(f"   ❌ Error searching Reddit: {e}")
            import traceback
            traceback.print_exc()
        
        # Remove duplicates by ID
        seen_ids = set()
        unique_posts = []
        for post in all_posts:
            if post['id'] not in seen_ids:
                seen_ids.add(post['id'])
                unique_posts.append(post)
        
        print(f"✅ Found {len(unique_posts)} unique Reddit posts across ALL subreddits")
        
        if not unique_posts:
            print(f"⚠️ No Reddit posts found for {stock_symbol}")
            print("   This could be due to:")
            print("   1. Stock not discussed on Reddit recently")
            print("   2. API rate limit exceeded")
            print("   3. Stock symbol not commonly used on Reddit")
        
        return unique_posts
    
    def analyze_reddit_sentiment(self, stock_name: str, stock_symbol: str,
                                 include_comments: bool = False,
                                 max_posts: int = 50) -> Dict:
        """
        Analyze Reddit sentiment for a stock using VADER + LLM
        
        Args:
            stock_name: Company name
            stock_symbol: Stock ticker
            include_comments: Whether to analyze comments (not implemented yet)
            max_posts: Maximum posts to analyze
            
        Returns:
            Dictionary with Reddit sentiment analysis
        """
        print(f"\n🔴 Analyzing Reddit sentiment for {stock_name} ({stock_symbol})...")
        
        # Search for posts
        posts = self.search_reddit_posts(stock_symbol, stock_name, max_posts=max_posts)
        
        if not posts:
            print("⚠️ No Reddit posts found")
            return self._get_default_reddit_sentiment()
        
        # Combine all post texts for analysis
        combined_text = "\n\n".join([
            f"[r/{post['subreddit']}] {post['title']}\n{post['text'][:200]}"
            for post in posts[:50]
        ])
        
        # Analyze sentiment using VADER + LLM (similar to Twitter)
        sentiment_result = self._analyze_posts_sentiment(
            combined_text,
            stock_symbol,
            stock_name,
            posts
        )
        
        return sentiment_result
    
    def _analyze_posts_sentiment(self, combined_text: str, stock_symbol: str,
                                 stock_name: str, posts_data: List[Dict]) -> Dict:
        """
        Analyze sentiment of Reddit posts using VADER (objective) + LLM (context)
        Similar to Twitter sentiment analysis
        
        Args:
            combined_text: Combined text from all posts
            stock_symbol: Stock ticker
            stock_name: Company name
            posts_data: List of post data dictionaries
            
        Returns:
            Dictionary with sentiment analysis results
        """
        print(f"   🤖 Analyzing sentiment of {len(posts_data)} Reddit posts...")
        
        # Try VADER first for objective, unbiased sentiment scoring
        if self.vader_available and self.vader_analyzer:
            try:
                print(f"   🔍 Using VADER for objective sentiment analysis...")
                
                # Analyze each post with VADER
                post_sentiments = []
                for post in posts_data:
                    text = f"{post['title']} {post['text']}"
                    if text.strip():
                        vader_scores = self.vader_analyzer.polarity_scores(text)
                        post_sentiments.append({
                            'compound': vader_scores['compound'],  # -1 to +1
                            'pos': vader_scores['pos'],
                            'neg': vader_scores['neg'],
                            'neu': vader_scores['neu'],
                            'title': post['title'][:100],
                            'subreddit': post['subreddit']
                        })
                
                if not post_sentiments:
                    print(f"   ⚠️ No valid posts to analyze")
                    return self._get_default_reddit_sentiment()
                
                # Calculate average VADER scores
                avg_compound = sum(p['compound'] for p in post_sentiments) / len(post_sentiments)
                avg_pos = sum(p['pos'] for p in post_sentiments) / len(post_sentiments)
                avg_neg = sum(p['neg'] for p in post_sentiments) / len(post_sentiments)
                avg_neu = sum(p['neu'] for p in post_sentiments) / len(post_sentiments)
                
                # Convert VADER compound score (-1 to +1) to 0-100 scale
                vader_sentiment_score = (avg_compound + 1) * 50
                
                # Determine sentiment label based on VADER score (0-100 scale)
                if vader_sentiment_score >= 70:
                    sentiment_label = "Strongly Bullish"
                elif vader_sentiment_score >= 60:
                    sentiment_label = "Bullish"
                elif vader_sentiment_score >= 40:
                    sentiment_label = "Neutral"
                elif vader_sentiment_score >= 30:
                    sentiment_label = "Bearish"
                else:
                    sentiment_label = "Strongly Bearish"
                
                # Count positive, negative, neutral posts
                positive_count = sum(1 for p in post_sentiments if p['compound'] > 0.05)
                negative_count = sum(1 for p in post_sentiments if p['compound'] < -0.05)
                neutral_count = len(post_sentiments) - positive_count - negative_count
                
                # Calculate percentages
                positive_percentage = (positive_count / len(post_sentiments) * 100) if post_sentiments else 0
                negative_percentage = (negative_count / len(post_sentiments) * 100) if post_sentiments else 0
                neutral_percentage = (neutral_count / len(post_sentiments) * 100) if post_sentiments else 0
                
                print(f"   ✅ VADER Analysis Complete:")
                print(f"      Score: {vader_sentiment_score:.1f}/100")
                print(f"      Positive: {positive_count}/{len(post_sentiments)} posts ({positive_percentage:.1f}%)")
                print(f"      Negative: {negative_count}/{len(post_sentiments)} posts ({negative_percentage:.1f}%)")
                print(f"      Neutral: {neutral_count}/{len(post_sentiments)} posts ({neutral_percentage:.1f}%)")
                
                # Now use LLM only for extracting key themes (not for scoring)
                sentiment_prompt = f"""Analyze Reddit discussions about {stock_name} ({stock_symbol}).

OBJECTIVE SENTIMENT SCORE (from VADER analysis): {vader_sentiment_score:.1f}/100
This score is calculated objectively based on the post content.

Sample Reddit Posts:
{combined_text[:3000]}

Based on the posts, provide:
1. Key Themes (3-5 main topics being discussed)
2. Market Mood Summary (2-3 sentences explaining the overall Reddit sentiment)

DO NOT change the sentiment score. Just extract the key themes and context.

Return ONLY valid JSON:
{{
  "key_themes": ["theme1", "theme2", "theme3", ...],
  "market_mood": "<2-3 sentence summary>"
}}"""
                
                try:
                    response = self.client.chat.completions.create(
                        model="openai/gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": "You are a Reddit sentiment analyst extracting key themes. Do not change the sentiment score, just extract themes."},
                            {"role": "user", "content": sentiment_prompt}
                        ],
                        temperature=0.1,
                        max_tokens=500
                    )
                    
                    result_text = response.choices[0].message.content.strip()
                    
                    # Clean JSON
                    if "```json" in result_text:
                        result_text = result_text.split("```json")[1].split("```")[0].strip()
                    elif "```" in result_text:
                        result_text = result_text.split("```")[1].split("```")[0].strip()
                    
                    llm_data = json.loads(result_text)
                    key_themes = llm_data.get('key_themes', ['Retail investor discussions', 'Stock performance'])
                    market_mood = llm_data.get('market_mood', f'Reddit sentiment is {sentiment_label.lower()} based on {len(post_sentiments)} posts.')
                    
                except Exception as e:
                    print(f"   ⚠️ LLM theme extraction failed: {e}, using defaults")
                    key_themes = ['Retail investor discussions', 'Stock performance', 'Market sentiment']
                    market_mood = f'Based on {len(post_sentiments)} Reddit posts, sentiment is {sentiment_label.lower()}.'
                
                # Calculate subreddit distribution
                subreddit_counts = {}
                for post in posts_data:
                    sub = post['subreddit']
                    subreddit_counts[sub] = subreddit_counts.get(sub, 0) + 1
                
                # Get top posts by engagement
                sorted_posts = sorted(
                    posts_data,
                    key=lambda x: x.get('score', 0) + x.get('num_comments', 0) * 2,
                    reverse=True
                )[:5]
                
                top_posts = [
                    {
                        'title': post['title'][:150],
                        'subreddit': post['subreddit'],
                        'score': post['score'],
                        'num_comments': post['num_comments'],
                        'url': f"https://reddit.com{post['permalink']}" if post.get('permalink') else None
                    }
                    for post in sorted_posts
                ]
                
                return {
                    'sentiment_score': round(vader_sentiment_score, 1),
                    'sentiment_label': sentiment_label,
                    'total_posts': len(posts_data),
                    'total_items_analyzed': len(post_sentiments),
                    'positive_count': positive_count,
                    'negative_count': negative_count,
                    'neutral_count': neutral_count,
                    'positive_percentage': round(positive_percentage, 1),
                    'negative_percentage': round(negative_percentage, 1),
                    'neutral_percentage': round(neutral_percentage, 1),
                    'key_themes': key_themes,
                    'market_mood': market_mood,
                    'key_insights': [
                        f"Analyzed {len(posts_data)} Reddit posts from {len(subreddit_counts)} subreddits",
                        f"Overall sentiment: {sentiment_label}",
                        market_mood
                    ],
                    'top_posts': top_posts,
                    'subreddit_distribution': subreddit_counts,
                    'confidence': 'High' if len(post_sentiments) >= 30 else 'Medium' if len(post_sentiments) >= 15 else 'Low',
                    'source': 'reddit_rapidapi_vader'
                }
                
            except Exception as e:
                print(f"   ⚠️ VADER analysis failed: {e}, falling back to LLM")
        
        # Fallback to LLM-only if VADER not available
        print(f"   ⚠️ VADER not available, using LLM-only analysis")
        print(f"   💡 Install VADER for unbiased sentiment: pip install vaderSentiment")
        
        sentiment_prompt = f"""Analyze Reddit sentiment for {stock_name} ({stock_symbol}) based on these posts.

Reddit Posts:
{combined_text[:4000]}

BE OBJECTIVE AND UNBIASED. Base your score ONLY on the actual post content, not assumptions.

Provide a comprehensive sentiment analysis with:
1. Overall Sentiment Score (0 to 100, where 0 is extremely bearish, 50 is neutral, 100 is extremely bullish)
2. Sentiment Label (Strongly Bullish, Bullish, Neutral, Bearish, Strongly Bearish)
3. Positive Percentage (0-100)
4. Negative Percentage (0-100)
5. Neutral Percentage (0-100)
6. Key Themes (3-5 main topics discussed)
7. Market Mood Summary (2-3 sentences)
8. Confidence Level (High/Medium/Low based on post quality and quantity)

Return ONLY valid JSON:
{{
  "sentiment_score": <number between 0 and 100>,
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
                    {"role": "system", "content": "You are an objective Reddit sentiment analyst. Analyze sentiment based ONLY on actual content without bias."},
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
            
            # Normalize sentiment score to 0-100 range
            raw_score = sentiment_data.get('sentiment_score', 50)
            normalized_score = self._normalize_sentiment_score(raw_score)
            sentiment_data['sentiment_score'] = round(normalized_score, 1)
            
            print(f"   🔴 Reddit Sentiment (LLM): {sentiment_data['sentiment_score']}/100 ({sentiment_data.get('sentiment_label', 'N/A')})")
            
            # Calculate subreddit distribution
            subreddit_counts = {}
            for post in posts_data:
                sub = post['subreddit']
                subreddit_counts[sub] = subreddit_counts.get(sub, 0) + 1
            
            # Get top posts
            sorted_posts = sorted(
                posts_data,
                key=lambda x: x.get('score', 0) + x.get('num_comments', 0) * 2,
                reverse=True
            )[:5]
            
            top_posts = [
                {
                    'title': post['title'][:150],
                    'subreddit': post['subreddit'],
                    'score': post['score'],
                    'num_comments': post['num_comments'],
                    'url': f"https://reddit.com{post['permalink']}" if post.get('permalink') else None
                }
                for post in sorted_posts
            ]
            
            return {
                'sentiment_score': sentiment_data['sentiment_score'],  # Already normalized
                'sentiment_label': sentiment_data.get('sentiment_label', 'Neutral'),
                'total_posts': len(posts_data),
                'total_items_analyzed': len(posts_data),
                'positive_percentage': round(sentiment_data.get('positive_percentage', 0), 1),
                'negative_percentage': round(sentiment_data.get('negative_percentage', 0), 1),
                'neutral_percentage': round(sentiment_data.get('neutral_percentage', 0), 1),
                'key_themes': sentiment_data.get('key_themes', []),
                'market_mood': sentiment_data.get('market_mood', ''),
                'key_insights': [
                    f"Analyzed {len(posts_data)} Reddit posts from {len(subreddit_counts)} subreddits",
                    f"Overall sentiment: {sentiment_data.get('sentiment_label', 'Neutral')}",
                    sentiment_data.get('market_mood', '')
                ],
                'top_posts': top_posts,
                'subreddit_distribution': subreddit_counts,
                'confidence': sentiment_data.get('confidence', 'Medium'),
                'source': 'reddit_rapidapi_llm'
            }
            
        except Exception as e:
            print(f"❌ Error analyzing Reddit sentiment: {e}")
            import traceback
            traceback.print_exc()
            return self._get_default_reddit_sentiment()
    
    def _get_default_reddit_sentiment(self) -> Dict:
        """Default Reddit sentiment when analysis fails (0-100 scale)"""
        return {
            'sentiment_score': 50,
            'sentiment_label': 'Unavailable',
            'total_posts': 0,
            'total_items_analyzed': 0,
            'positive_count': 0,
            'negative_count': 0,
            'neutral_count': 0,
            'positive_percentage': 0,
            'negative_percentage': 0,
            'neutral_percentage': 0,
            'key_themes': [],
            'market_mood': 'Reddit data temporarily unavailable',
            'key_insights': [
                'Reddit data temporarily unavailable',
                'This could be due to API rate limits or the stock not being discussed',
                'Sentiment analysis continues with News, Yahoo Finance, and Twitter sources'
            ],
            'top_posts': [],
            'subreddit_distribution': {},
            'confidence': 'None',
            'source': 'reddit',
            'status': 'unavailable'
        }


# Convenience function
def analyze_reddit_sentiment(stock_name: str, stock_symbol: str,
                             include_comments: bool = False,
                             max_posts: int = 50) -> Dict:
    """
    Convenience function to analyze Reddit sentiment using RapidAPI
    
    Args:
        stock_name: Full company name
        stock_symbol: Stock ticker symbol
        include_comments: Include comment analysis (not implemented yet)
        max_posts: Maximum posts to analyze (default: 50)
        
    Returns:
        Reddit sentiment analysis dictionary
    """
    analyzer = RedditSentimentAnalyzer()
    return analyzer.analyze_reddit_sentiment(stock_name, stock_symbol, include_comments, max_posts)

