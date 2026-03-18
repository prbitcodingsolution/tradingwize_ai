#!/usr/bin/env python3
"""
Quick test to check if the Tata stock issue is fixed
"""

import asyncio
from agent1 import agent, ConversationState

async def quick_test():
    """Quick test of the fix"""
    print("🧪 Quick test: 'tata stock' behavior...")
    
    deps = ConversationState()
    
    try:
        # Test with a shorter timeout
        result = await asyncio.wait_for(
            agent.run("tata stock", deps=deps),
            timeout=30.0  # 30 second timeout
        )
        
        response = result.data if hasattr(result, 'data') else str(result)
        
        print(f"📊 Response length: {len(response)} characters")
        
        # Check key indicators
        if "Found" in response and "Select which one to analyze:" in response:
            print("✅ SUCCESS: Shows multiple options for selection")
            
            # Count options
            option_count = response.count('\n') - response.count('\n\n')  # Rough count
            print(f"📊 Approximately {option_count} lines in response")
            
            return True
        elif "Selected:" in response:
            print("❌ ISSUE: Still auto-selecting instead of showing options")
            return False
        else:
            print("❓ UNCLEAR: Unexpected response format")
            print(f"Preview: {response[:200]}...")
            return False
            
    except asyncio.TimeoutError:
        print("⏰ Test timed out after 30 seconds")
        return False
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False

if __name__ == "__main__":
    result = asyncio.run(quick_test())
    if result:
        print("\n🎉 Fix appears to be working!")
    else:
        print("\n⚠️ Issue may still exist")