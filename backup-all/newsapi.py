"""
Twitter/X Data Fetching for Stock Sentiment Analysis

IMPORTANT: snscrape no longer works (Twitter blocked it)

Working alternatives:
1. Official Twitter API (tweepy) - RECOMMENDED but requires API key
2. Mock data for testing - Use this to test your sentiment pipeline
"""

import tweepy
import os
from datetime import datetime, timedelta
import random
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def fetch_stock_tweets_api(stock_name, since_date="2026-02-09", limit=50):
    """
    Fetch tweets using Twitter API v2 (requires API keys)
    You need to set TWITTER_BEARER_TOKEN in your .env file
    
    Get free API access at: https://developer.twitter.com/
    """
    
    bearer_token = os.getenv("TWITTER_BEARER_TOKEN")
    
    if not bearer_token:
        print("❌ TWITTER_BEARER_TOKEN not found in environment variables")
        print("\n📝 To get a bearer token:")
        print("1. Go to https://developer.twitter.com/")
        print("2. Sign up for a free developer account")
        print("3. Create a new app")
        print("4. Copy the Bearer Token")
        print("5. Add to .env file: TWITTER_BEARER_TOKEN=your_token_here")
        return []
    
    try:
        client = tweepy.Client(bearer_token=bearer_token)
        
        query = f'("{stock_name}" OR ${stock_name}) lang:en -is:retweet'
        
        print(f"🔍 Searching: {query}")
        print(f"📅 Since: {since_date}")
        print(f"📊 Limit: {limit}")
        print("=" * 60)
        
        tweets = client.search_recent_tweets(
            query=query,
            max_results=min(limit, 100),
            tweet_fields=['created_at', 'public_metrics', 'author_id'],
            expansions=['author_id'],
            user_fields=['username']
        )
        
        if not tweets.data:
            print("⚠️ No tweets found!")
            return []
        
        users = {user.id: user for user in tweets.includes['users']}
        
        results = []
        for tweet in tweets.data:
            user = users.get(tweet.author_id)
            tweet_data = {
                'date': tweet.created_at,
                'user': user.username if user else "Unknown",
                'content': tweet.text,
                'likes': tweet.public_metrics['like_count'],
                'retweets': tweet.public_metrics['retweet_count']
            }
            results.append(tweet_data)
            
            print(f"📅 {tweet_data['date']}")
            print(f"👤 @{tweet_data['user']}")
            print(f"💬 {tweet_data['content']}")
            print(f"❤️ {tweet_data['likes']} | 🔄 {tweet_data['retweets']}")
            print("-" * 60)
        
        return results
            
    except tweepy.TweepyException as e:
        print(f"❌ Twitter API Error: {e}")
        return []
    except Exception as e:
        print(f"❌ Error: {e}")
        return []


def generate_mock_tweets(stock_name, limit=20):
    """
    Generate mock tweets for testing sentiment analysis
    Use this when you don't have Twitter API access
    """
    
    print(f"🧪 Generating {limit} mock tweets for {stock_name}")
    print("=" * 60)
    
    # Sample tweet templates with different sentiments
    positive_templates = [
        f"{stock_name} is showing strong growth potential! 📈",
        f"Great quarterly results from {stock_name}! Bullish on this stock 🚀",
        f"{stock_name} breaking resistance levels. Time to buy! 💰",
        f"Impressed with {stock_name}'s performance this quarter",
        f"{stock_name} fundamentals looking solid. Long term hold 👍",
    ]
    
    negative_templates = [
        f"Concerned about {stock_name}'s declining margins 📉",
        f"{stock_name} missing earnings expectations. Bearish signal 🐻",
        f"Selling my {stock_name} position. Too much risk",
        f"{stock_name} facing regulatory challenges. Not good",
        f"Disappointed with {stock_name}'s management decisions",
    ]
    
    neutral_templates = [
        f"Watching {stock_name} closely. Waiting for clear signals",
        f"{stock_name} trading sideways. No clear direction yet",
        f"Analyzing {stock_name}'s latest financial reports",
        f"{stock_name} at key support level. Could go either way",
        f"Mixed signals from {stock_name}. Need more data",
    ]
    
    all_templates = positive_templates + negative_templates + neutral_templates
    usernames = ["trader_pro", "stock_guru", "market_watch", "invest_smart", 
                 "bull_trader", "value_investor", "day_trader", "long_term_hold"]
    
    results = []
    base_date = datetime.now()
    
    for i in range(limit):
        template = random.choice(all_templates)
        tweet_data = {
            'date': base_date - timedelta(hours=random.randint(1, 48)),
            'user': random.choice(usernames),
            'content': template,
            'likes': random.randint(5, 500),
            'retweets': random.randint(1, 100)
        }
        results.append(tweet_data)
        
        print(f"📅 {tweet_data['date'].strftime('%Y-%m-%d %H:%M')}")
        print(f"👤 @{tweet_data['user']}")
        print(f"💬 {tweet_data['content']}")
        print(f"❤️ {tweet_data['likes']} | 🔄 {tweet_data['retweets']}")
        print("-" * 60)
    
    return results


def fetch_stock_tweets(stock_name, since_date="2026-02-09", limit=50, use_mock=False):
    """
    Main function to fetch stock tweets
    
    Args:
        stock_name: Stock symbol or name
        since_date: Start date for search
        limit: Maximum number of tweets
        use_mock: If True, generate mock data instead of calling API
    """
    
    if use_mock:
        return generate_mock_tweets(stock_name, limit)
    else:
        return fetch_stock_tweets_api(stock_name, since_date, limit)


if __name__ == "__main__":
    print("🐦 Twitter/X Data Fetching Test")
    print("=" * 60)
    
    # Check if API key exists
    has_api_key = bool(os.getenv("TWITTER_BEARER_TOKEN"))
    
    if has_api_key:
        print("✅ Twitter API key found. Trying real API...")
        tweets = fetch_stock_tweets("RELIANCE", limit=20, use_mock=False)
        
        # If API failed (no tweets), fall back to mock data
        if not tweets:
            print("\n⚠️ Twitter API failed (likely needs paid plan)")
            print("📝 Falling back to mock data for testing...\n")
            tweets = fetch_stock_tweets("RELIANCE", limit=20, use_mock=True)
    else:
        print("⚠️ No Twitter API key found.")
        print("📝 Using mock data for testing...\n")
        tweets = fetch_stock_tweets("RELIANCE", limit=20, use_mock=True)
    
    print(f"\n✅ Fetched {len(tweets)} tweets")
    print("\n💡 IMPORTANT: Twitter API now requires a paid plan ($100+/month)")
    print("   Alternatives:")
    print("   1. Use mock data for testing (current approach)")
    print("   2. Use Reddit API (free tier available)")
    print("   3. Use news APIs (NewsAPI, Alpha Vantage)")
    print("   4. Web scraping with Selenium (slower but free)")
    print("\n   For production, consider integrating multiple sources!")
