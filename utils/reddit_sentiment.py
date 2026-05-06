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
        # Tracks the reason for the LAST failed fetch so the caller's
        # "unavailable" default can show a precise explanation in the UI
        # (e.g. "Monthly quota exhausted" vs "No posts found"). Reset on
        # each successful call.
        self.last_fetch_error: Optional[str] = None
    
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
        # Reset failure reason each call — set again on any failure path.
        self.last_fetch_error = None

        if not self.api_key or not self.api_host:
            print("⚠️ REDDIT_RAPIDAPI_KEY or REDDIT_RAPIDAPI_HOST not configured")
            self.last_fetch_error = "Reddit API credentials not configured in .env"
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
                # RapidAPI returns 429 for BOTH "requests per minute" rate
                # limits AND "monthly quota exhausted". The body distinguishes
                # them — monthly-quota messages contain the word "MONTHLY".
                # Distinguishing the two lets us show the user a clearer
                # message (quota vs transient rate-limit).
                body_msg = ""
                try:
                    body_msg = response.json().get("message", "")
                except Exception:
                    body_msg = response.text[:200]
                if "monthly" in body_msg.lower() or "quota" in body_msg.lower():
                    self.last_fetch_error = (
                        "Reddit API monthly quota exhausted on the RapidAPI BASIC plan. "
                        "Upgrade your RapidAPI subscription or wait for the quota to "
                        "reset to restore Reddit sentiment."
                    )
                    print(f"   ⚠️ Reddit API MONTHLY quota exhausted (429)")
                    print(f"      Message: {body_msg}")
                else:
                    self.last_fetch_error = (
                        "Reddit API rate limit hit (per-minute). Please try again shortly."
                    )
                    print(f"   ⚠️ Reddit API rate limit exceeded (429, transient)")
            else:
                print(f"   ⚠️ Reddit API error: {response.status_code}")
                _err_body = ""
                try:
                    _err_body = str(response.json())
                except Exception:
                    _err_body = response.text[:200]
                print(f"      Details: {_err_body}")
                self.last_fetch_error = (
                    f"Reddit API returned HTTP {response.status_code}. {_err_body}"[:220]
                )

        except Exception as e:
            print(f"   ❌ Error searching Reddit: {e}")
            import traceback
            traceback.print_exc()
            self.last_fetch_error = f"Reddit API request failed: {e}"
        
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
            return self._get_default_reddit_sentiment(
                reason=self.last_fetch_error or "No Reddit posts found for this stock"
            )
        
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
        print(f"   🤖 Analyzing sentiment of {len(posts_data)} Reddit posts with LLM classifier...")

        # --- LLM classifier scoring ---
        try:
            from .llm_sentiment import LLMSentimentAnalyzer
            texts = [
                f"{p['title']} {p['text']}"
                for p in posts_data
                if (p.get('title') or p.get('text', '')).strip()
            ]
            if not texts:
                return self._get_default_reddit_sentiment()

            classifier = LLMSentimentAnalyzer.get_instance()
            llm_result = classifier.analyze_texts(texts)

            llm_score = llm_result["score"]
            sentiment_label = llm_result["label"]
            breakdown = llm_result["breakdown"]
            positive_count = breakdown.get("positive", 0)
            negative_count = breakdown.get("negative", 0)
            neutral_count = breakdown.get("neutral", 0)
            n = len(texts)
            positive_percentage = positive_count / n * 100 if n else 0
            negative_percentage = negative_count / n * 100 if n else 0
            neutral_percentage = neutral_count / n * 100 if n else 0

            print(f"   ✅ LLM Sentiment Analysis Complete:")
            print(f"      Score: {llm_score:.1f}/100  Label: {sentiment_label}")
            print(f"      Positive: {positive_count}  Negative: {negative_count}  Neutral: {neutral_count}")

            # LLM for theme extraction only
            sentiment_prompt = f"""Analyze Reddit discussions about {stock_name} ({stock_symbol}).

OBJECTIVE SENTIMENT SCORE (LLM classifier): {llm_score:.1f}/100

Sample Reddit Posts:
{combined_text[:3000]}

Return ONLY valid JSON:
{{
  "key_themes": ["theme1", "theme2", "theme3"],
  "market_mood": "<2-3 sentence summary>"
}}"""
            try:
                response = self.client.chat.completions.create(
                    model="openai/gpt-oss-120b",
                    messages=[
                        {"role": "system", "content": "You are a Reddit sentiment analyst extracting key themes. Do not change the score, just extract themes."},
                        {"role": "user", "content": sentiment_prompt}
                    ],
                    temperature=0.1,
                    max_tokens=500
                )
                result_text = response.choices[0].message.content.strip()
                if "```json" in result_text:
                    result_text = result_text.split("```json")[1].split("```")[0].strip()
                elif "```" in result_text:
                    result_text = result_text.split("```")[1].split("```")[0].strip()
                llm_data = json.loads(result_text)
                key_themes = llm_data.get('key_themes', ['Retail investor discussions', 'Stock performance'])
                market_mood = llm_data.get('market_mood', f'Reddit sentiment is {sentiment_label.lower()} based on {n} posts.')
            except Exception as e:
                print(f"   ⚠️ LLM theme extraction failed: {e}")
                key_themes = ['Retail investor discussions', 'Stock performance', 'Market sentiment']
                market_mood = f'Based on {n} Reddit posts, LLM sentiment is {sentiment_label.lower()}.'

            subreddit_counts = {}
            for post in posts_data:
                sub = post['subreddit']
                subreddit_counts[sub] = subreddit_counts.get(sub, 0) + 1

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
                'sentiment_score': round(llm_score, 1),
                'sentiment_label': sentiment_label,
                'total_posts': len(posts_data),
                'total_items_analyzed': n,
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
                    f"Overall sentiment (LLM): {sentiment_label}",
                    market_mood
                ],
                'top_posts': top_posts,
                'subreddit_distribution': subreddit_counts,
                'confidence': 'High' if n >= 30 else 'Medium' if n >= 15 else 'Low',
                'source': 'reddit_rapidapi_llm',
                'llm_result': llm_result,
            }

        except Exception as e:
            print(f"   ⚠️ LLM classifier batch failed for Reddit: {e}, falling back to single LLM re-ask")

        # LLM re-ask fallback (single direct-score call if the batched classifier errored)
        print(f"   ⚠️ LLM classifier unavailable, using LLM-only re-ask analysis")
        
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
                model="openai/gpt-oss-120b",
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
            return self._get_default_reddit_sentiment(
                reason=f"Sentiment analysis failed: {e}"
            )

    def _get_default_reddit_sentiment(self, reason: Optional[str] = None) -> Dict:
        """Default Reddit sentiment when analysis fails (0-100 scale).

        If `reason` is provided it's surfaced through `market_mood` and the
        first line of `key_insights` so the UI can tell the user WHY Reddit
        data is unavailable (quota exhausted, rate-limit, no posts, etc.)
        instead of a generic 'Unavailable' label.
        """
        reason = reason or "Reddit data temporarily unavailable"
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
            'market_mood': reason,
            'key_insights': [
                reason,
                'Sentiment analysis continues with News, Yahoo Finance, and Twitter sources',
            ],
            'top_posts': [],
            'subreddit_distribution': {},
            'confidence': 'None',
            'source': 'reddit',
            'status': 'unavailable',
            'unavailable_reason': reason,
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

