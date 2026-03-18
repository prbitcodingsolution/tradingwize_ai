"""
Utility script to test and refresh API bearer token
Run this when you get 401 authentication errors
"""

import os
import requests
from dotenv import load_dotenv, set_key
from datetime import datetime

# Load environment variables
load_dotenv()

API_BASE_URL = os.getenv("API_BASE_URL", "http://192.168.0.126:8000")
CURRENT_TOKEN = os.getenv("API_BEARER_TOKEN", "")

print("\n" + "="*70)
print("🔐 API Token Refresh Utility")
print("="*70)
print(f"\n📍 API Base URL: {API_BASE_URL}")
print(f"📍 Current Token: {CURRENT_TOKEN[:50]}..." if len(CURRENT_TOKEN) > 50 else f"📍 Current Token: {CURRENT_TOKEN}")

# Test current token
print("\n🧪 Testing current token...")

test_endpoint = f"{API_BASE_URL}/api/v1/mentor/get-forex-data/"
test_params = {
    'pair': 'ONGC.NS',
    'from': '2025-01-01',
    'to': '2025-01-31',
    'market': 'stock',
    'timeframe': '1d'
}

headers = {
    'accept': 'application/json'
}

if CURRENT_TOKEN:
    headers['authorization'] = f'Bearer {CURRENT_TOKEN}'

try:
    response = requests.get(test_endpoint, params=test_params, headers=headers, timeout=10)
    
    if response.status_code == 200:
        print("✅ Token is valid and working!")
        print(f"   Successfully fetched data from API")
        print("\n✨ No action needed - your token is working fine")
    elif response.status_code == 401:
        print("❌ Token is EXPIRED or INVALID")
        print(f"   Status: {response.status_code}")
        print(f"   Error: {response.json()}")
        print("\n" + "="*70)
        print("📋 HOW TO FIX:")
        print("="*70)
        print("\n1️⃣  Login to your API system:")
        print(f"   URL: {API_BASE_URL}")
        print("   Use your credentials to login")
        
        print("\n2️⃣  Get a new access token:")
        print("   - Look for 'Authentication' or 'API Tokens' section")
        print("   - Generate or copy a new access token")
        
        print("\n3️⃣  Update your .env file:")
        print("   - Open .env file in your editor")
        print("   - Find the line: API_BEARER_TOKEN=...")
        print("   - Replace with: API_BEARER_TOKEN=your_new_token_here")
        
        print("\n4️⃣  Restart your API server:")
        print("   python api_chat_drawing.py")
        
        print("\n" + "="*70)
        print("\n💡 TIP: You can also run this script again after updating")
        print("   to verify the new token works")
        print("\n" + "="*70)
        
        # Offer to update token interactively
        print("\n🔧 Would you like to update the token now? (y/n): ", end="")
        choice = input().strip().lower()
        
        if choice == 'y':
            print("\n📝 Enter your new bearer token: ", end="")
            new_token = input().strip()
            
            if new_token:
                # Update .env file
                env_file = '.env'
                set_key(env_file, 'API_BEARER_TOKEN', new_token)
                print(f"\n✅ Token updated in {env_file}")
                print("🔄 Please restart your API server for changes to take effect")
                
                # Test new token
                print("\n🧪 Testing new token...")
                headers['authorization'] = f'Bearer {new_token}'
                test_response = requests.get(test_endpoint, params=test_params, headers=headers, timeout=10)
                
                if test_response.status_code == 200:
                    print("✅ New token is valid and working!")
                else:
                    print(f"❌ New token test failed: {test_response.status_code}")
                    print(f"   Response: {test_response.text}")
            else:
                print("❌ No token provided. Update cancelled.")
    else:
        print(f"⚠️  Unexpected response: {response.status_code}")
        print(f"   Response: {response.text}")
        
except requests.exceptions.ConnectionError:
    print(f"❌ Cannot connect to API at {API_BASE_URL}")
    print("   Make sure the API server is running")
except requests.exceptions.Timeout:
    print(f"❌ Request timeout - API at {API_BASE_URL} is not responding")
except Exception as e:
    print(f"❌ Error: {e}")

print("\n" + "="*70 + "\n")
