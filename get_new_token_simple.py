"""
Simple script to get a new API token
"""

import requests
import os
from dotenv import set_key

API_BASE_URL = "http://192.168.0.126:8000"

print("\n" + "="*70)
print("🔐 Get New API Token")
print("="*70)
print(f"\n📍 API Server: {API_BASE_URL}")
print(f"⚠️  Current token expired on: March 3, 2026 12:32:24")
print(f"⚠️  You need to get a new token from your API server")

print("\n" + "="*70)
print("📋 Steps to get a new token:")
print("="*70)
print("\n1. Open your browser and go to:")
print(f"   {API_BASE_URL}")
print("\n2. Login with your credentials")
print("\n3. Look for 'API Tokens' or 'Authentication' section")
print("\n4. Copy the new access token")
print("\n5. Run this script to update it automatically")

print("\n" + "="*70)
print("Manual Update (if script doesn't work):")
print("="*70)
print("\n1. Open .env file in your editor")
print("2. Find the line: API_BEARER_TOKEN=...")
print("3. Replace with your new token:")
print("   API_BEARER_TOKEN=your_new_token_here")
print("4. Save the file")
print("\n5. Restart your API server:")
print("   python api_chat_drawing.py")

print("\n" + "="*70 + "\n")

# Ask user if they want to try automatic update
try:
    choice = input("Do you want to try automatic token update? (y/n): ").strip().lower()
    
    if choice == 'y':
        print("\n📝 Enter your new token: ", end="")
        new_token = input().strip()
        
        if new_token:
            # Update .env file
            env_file = '.env'
            set_key(env_file, 'API_BEARER_TOKEN', new_token)
            print(f"\n✅ Token updated in {env_file}")
            
            # Test the new token
            print("\n🧪 Testing new token...")
            test_url = f"{API_BASE_URL}/api/v1/mentor/get-forex-data/"
            test_response = requests.get(
                test_url,
                params={
                    'pair': 'ONGC.NS',
                    'from': '2025-01-01',
                    'to': '2025-01-31',
                    'market': 'stock',
                    'timeframe': '1d'
                },
                headers={
                    'authorization': f'Bearer {new_token}',
                    'accept': 'application/json'
                },
                timeout=10
            )
            
            if test_response.status_code == 200:
                print("✅ New token is working!")
            else:
                print(f"⚠️  Token test returned: {test_response.status_code}")
                print(f"   Response: {test_response.text}")
        else:
            print("❌ No token provided")
    
except KeyboardInterrupt:
    print("\n\n❌ Operation cancelled")

print("\n" + "="*70 + "\n")
