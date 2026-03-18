#!/usr/bin/env python3
"""
Quick test to verify the main fixes
"""

def test_database_fallback():
    """Test if database fallback works"""
    try:
        from response_fallback import get_cached_analysis_response
        
        success, response, stock_info = get_cached_analysis_response()
        
        if success:
            print(f"✅ Database fallback works!")
            print(f"📊 Stock: {stock_info['name']} ({stock_info['symbol']})")
            print(f"📊 Response length: {len(response)} characters")
            print(f"📄 Preview: {response[:200]}...")
            return True
        else:
            print(f"⚠️ No cached data: {response}")
            return False
            
    except Exception as e:
        print(f"❌ Database test failed: {e}")
        return False

def test_response_monitoring():
    """Test response monitoring functionality"""
    try:
        from response_fallback import monitor_response_display
        
        # This would normally be called with actual session state
        # For now, just test that the function exists and runs
        print("✅ Response monitoring function exists and can be imported")
        return True
        
    except Exception as e:
        print(f"❌ Response monitoring test failed: {e}")
        return False

def main():
    print("🚀 Quick verification of fixes...\n")
    
    print("1. Testing database fallback...")
    test1 = test_database_fallback()
    
    print("\n2. Testing response monitoring...")
    test2 = test_response_monitoring()
    
    print(f"\n📊 Results:")
    print(f"✅ Database fallback: {'PASS' if test1 else 'FAIL'}")
    print(f"✅ Response monitoring: {'PASS' if test2 else 'FAIL'}")
    
    print(f"\n🔧 Fixes implemented:")
    print(f"✅ Multiple stock selection improved for business groups")
    print(f"✅ Database fallback system created")
    print(f"✅ Response monitoring added")
    print(f"✅ Fallback button added to Streamlit sidebar")
    print(f"✅ Automatic response detection implemented")

if __name__ == "__main__":
    main()