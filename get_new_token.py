"""
Simple script to help you get a new API token
"""

import requests
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()  # Pick up `.env` so LMS_BASE_URL is visible to get_lms_base_url().

# Make project-level utils importable when this script is run directly
# (`python get_new_token.py`) — without this `from utils...` would fail.
_PROJECT_ROOT = str(Path(__file__).resolve().parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from utils.base_url import get_lms_base_url

# Reads LMS_BASE_URL (or legacy API_BASE_URL / DRAWING_EXPLAINER_BASE_URL)
# from `.env` — change the URL there once instead of editing this file.
API_BASE_URL = get_lms_base_url()

print("\n" + "="*70)
print("🔐 Get New API Token")
print("="*70)

print(f"\n📍 API Server: {API_BASE_URL}")
print("\n📋 To get a new token, you need to:")
print("   1. Login to your API system")
print("   2. Get the access token")
print("   3. Update it in .env file")

print("\n" + "="*70)
print("Option 1: Login via API (if you have credentials)")
print("="*70)

username = input("\nEnter username (or press Enter to skip): ").strip()

if username:
    password = input("Enter password: ").strip()
    
    # Try to login
    login_url = f"{API_BASE_URL}/api/token/"
    
    try:
        print(f"\n🔄 Attempting login to {login_url}...")
        response = requests.post(
            login_url,
            json={"username": username, "password": password},
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            access_token = data.get('access')
            refresh_token = data.get('refresh')
            
            print("\n✅ Login successful!")
            print(f"\n📝 Your new tokens:")
            print(f"\nAccess Token:")
            print(access_token)
            print(f"\nRefresh Token:")
            print(refresh_token)
            
            # Update .env file
            print("\n🔄 Updating .env file...")
            from dotenv import set_key
            set_key('.env', 'API_BEARER_TOKEN', access_token)
            print("✅ .env file updated!")
            
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
                headers={'authorization': f'Bearer {access_token}'},
                timeout=10
            )
            
            if test_response.status_code == 200:
                print("✅ New token is working!")
            else:
                print(f"⚠️  Token test returned: {test_response.status_code}")
                print(f"   Response: {test_response.text}")
        else:
            print(f"\n❌ Login failed: {response.status_code}")
            print(f"   Response: {response.text}")
            
    except Exception as e:
        print(f"\n❌ Error: {e}")

else:
    print("\n" + "="*70)
    print("Option 2: Manual Token Entry")
    print("="*70)
    
    print(f"\n1. Open your browser and go to: {API_BASE_URL}")
    print("2. Login with your credentials")
    print("3. Copy the access token")
    print("4. Paste it below")
    
    new_token = input("\nPaste your new token here (or press Enter to skip): ").strip()
    
    if new_token:
        # Update .env file
        print("\n🔄 Updating .env file...")
        from dotenv import set_key
        set_key('.env', 'API_BEARER_TOKEN', new_token)
        print("✅ .env file updated!")
        
        # Test the new token
        print("\n🧪 Testing new token...")
        test_url = f"{API_BASE_URL}/api/v1/mentor/get-forex-data/"
        try:
            test_response = requests.get(
                test_url,
                params={
                    'pair': 'ONGC.NS',
                    'from': '2025-01-01',
                    'to': '2025-01-31',
                    'market': 'stock',
                    'timeframe': '1d'
                },
                headers={'authorization': f'Bearer {new_token}'},
                timeout=10
            )
            
            if test_response.status_code == 200:
                print("✅ New token is working!")
            else:
                print(f"⚠️  Token test returned: {test_response.status_code}")
                print(f"   Response: {test_response.text}")
        except Exception as e:
            print(f"❌ Test failed: {e}")

print("\n" + "="*70)
print("💡 IMPORTANT: Restart your API server after updating the token")
print("   Command: python api_chat_drawing.py")
print("="*70 + "\n")
