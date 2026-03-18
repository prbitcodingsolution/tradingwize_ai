#!/usr/bin/env python3
"""
Debug SMC filtering issue
"""

import sys
import os
import json

# Add drawing_instruction to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'drawing_instruction'))

from drawing_instruction.chat_drawing_agent import ChatDrawingAgent

def debug_smc_filtering():
    """Debug why SMC drawings are being filtered out"""
    
    print("🐛 Debugging SMC Filtering Issue...")
    print("=" * 60)
    
    try:
        # Initialize chat agent
        print("🤖 Initializing ChatDrawingAgent...")
        agent = ChatDrawingAgent()
        
        # Test SMC generation with debug
        print("📤 Testing SMC generation with debug...")
        print("   Message: 'mark SMC on this stock'")
        print("   Symbol: TCS")
        
        result = agent.generate_from_chat(
            user_message="mark SMC on this stock",
            symbol="TCS",
            timeframe="1d",
            start_date="2025-01-01",
            end_date="2025-12-31",
            market="stock"
        )
        
        print(f"\n📥 Result Summary:")
        print(f"   Success: {not result.get('error')}")
        print(f"   Total Drawings: {result.get('total_drawings', 0)}")
        
        # Check parsed intent
        chat_metadata = result.get('chat_metadata', {})
        parsed_intent = chat_metadata.get('parsed_intent', {})
        print(f"   Drawing Types: {parsed_intent.get('drawing_types', [])}")
        print(f"   Intent Confidence: {parsed_intent.get('confidence', 0)}")
        
        # Analyze all drawings before filtering
        all_drawings = result.get('all_drawings_before_filtering', [])
        if not all_drawings:
            # Try to get from the main drawings array
            all_drawings = result.get('drawings', [])
        
        print(f"\n🔍 Analyzing Drawings Before Filtering:")
        print(f"   Total drawings generated: {len(all_drawings)}")
        
        # Count by type and metadata
        drawing_types = {}
        smc_drawings = []
        
        for i, drawing in enumerate(all_drawings):
            drawing_type = drawing.get('type', 'unknown')
            metadata = drawing.get('metadata', {})
            
            # Count by type
            drawing_types[drawing_type] = drawing_types.get(drawing_type, 0) + 1
            
            # Check for SMC metadata
            has_smc_metadata = (
                'smc_type' in metadata or 
                'order_block_type' in metadata or 
                'structure_type' in metadata or
                'equal_level_type' in metadata
            )
            
            if has_smc_metadata:
                smc_drawings.append({
                    'index': i,
                    'type': drawing_type,
                    'metadata': metadata,
                    'text': drawing.get('state', {}).get('text', '')
                })
        
        print(f"\n📊 Drawing Types Generated:")
        for dtype, count in drawing_types.items():
            print(f"   {dtype}: {count}")
        
        print(f"\n🎯 SMC Drawings Found (before filtering):")
        print(f"   Total SMC drawings: {len(smc_drawings)}")
        
        for smc in smc_drawings:
            print(f"   [{smc['index']}] {smc['type']}")
            print(f"       Metadata: {smc['metadata']}")
            print(f"       Text: {smc['text']}")
        
        # Check final filtered drawings
        final_drawings = result.get('drawings', [])
        print(f"\n🔍 Final Filtered Drawings:")
        print(f"   Total after filtering: {len(final_drawings)}")
        
        final_smc = []
        for drawing in final_drawings:
            metadata = drawing.get('metadata', {})
            has_smc_metadata = (
                'smc_type' in metadata or 
                'order_block_type' in metadata or 
                'structure_type' in metadata or
                'equal_level_type' in metadata
            )
            if has_smc_metadata:
                final_smc.append(drawing)
        
        print(f"   SMC drawings in final result: {len(final_smc)}")
        
        # Save debug data
        debug_data = {
            'total_generated': len(all_drawings),
            'smc_found_before_filtering': len(smc_drawings),
            'total_after_filtering': len(final_drawings),
            'smc_found_after_filtering': len(final_smc),
            'drawing_types': drawing_types,
            'smc_drawings_details': smc_drawings,
            'parsed_intent': parsed_intent
        }
        
        with open('smc_filtering_debug.json', 'w') as f:
            json.dump(debug_data, f, indent=2)
        
        print(f"\n💾 Debug data saved to: smc_filtering_debug.json")
        
        # Conclusion
        if len(smc_drawings) > 0 and len(final_smc) == 0:
            print(f"\n❌ ISSUE FOUND: SMC drawings generated but filtered out!")
            print(f"   - Generated: {len(smc_drawings)} SMC drawings")
            print(f"   - Final result: {len(final_smc)} SMC drawings")
            print(f"   - This indicates a filtering logic issue")
            return False
        elif len(smc_drawings) > 0 and len(final_smc) > 0:
            print(f"\n✅ SMC filtering working correctly!")
            print(f"   - Generated: {len(smc_drawings)} SMC drawings")
            print(f"   - Final result: {len(final_smc)} SMC drawings")
            return True
        else:
            print(f"\n⚠️  No SMC drawings generated at all!")
            print(f"   - This indicates an issue with SMC generation, not filtering")
            return False
    
    except Exception as e:
        print(f"❌ Error in debug: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = debug_smc_filtering()
    
    print(f"\n" + "=" * 60)
    if success:
        print("🎉 SMC filtering is working correctly!")
    else:
        print("❌ SMC filtering issue identified - needs fixing")
    print("=" * 60)