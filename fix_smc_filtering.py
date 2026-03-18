#!/usr/bin/env python3
"""
Fix SMC filtering issue by analyzing the exact problem
"""

import sys
import os
import json

# Add drawing_instruction to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'drawing_instruction'))

def analyze_smc_filtering_issue():
    """Analyze the exact SMC filtering issue"""
    
    print("🔍 Analyzing SMC Filtering Issue...")
    print("=" * 60)
    
    try:
        from drawing_instruction.llm_drawing_generator import generate_drawings_with_llm
        
        print("📤 Generating drawings for TCS...")
        
        # Generate drawings using the same method as the API
        result = generate_drawings_with_llm(
            symbol="TCS",
            timeframe="1d",
            use_api=True,
            api_config={
                'base_url': 'http://192.168.0.126:8000',
                'from_date': '2025-01-01',
                'to_date': '2025-12-31',
                'market': 'stock'
            }
        )
        
        print(f"📥 Generation result:")
        print(f"   Total drawings: {result.get('total_drawings', 0)}")
        print(f"   Error: {result.get('error', 'None')}")
        
        drawings = result.get('drawings', [])
        
        print(f"\n🔍 Analyzing all {len(drawings)} drawings:")
        
        # Categorize drawings
        drawing_categories = {
            'smc': [],
            'fvg': [],
            'zones': [],
            'other': []
        }
        
        for i, drawing in enumerate(drawings):
            metadata = drawing.get('metadata', {})
            drawing_type = drawing.get('type', 'unknown')
            text = drawing.get('state', {}).get('text', '')
            
            # Check SMC metadata
            if ('smc_type' in metadata or 
                'order_block_type' in metadata or 
                'structure_type' in metadata or
                'equal_level_type' in metadata):
                drawing_categories['smc'].append({
                    'index': i,
                    'type': drawing_type,
                    'metadata': metadata,
                    'text': text
                })
            # Check FVG metadata
            elif 'fvg_type' in metadata or 'gap_size' in metadata:
                drawing_categories['fvg'].append({
                    'index': i,
                    'type': drawing_type,
                    'metadata': metadata,
                    'text': text
                })
            # Check zone metadata
            elif 'base_candles' in metadata:
                drawing_categories['zones'].append({
                    'index': i,
                    'type': drawing_type,
                    'metadata': metadata,
                    'text': text
                })
            else:
                drawing_categories['other'].append({
                    'index': i,
                    'type': drawing_type,
                    'metadata': metadata,
                    'text': text
                })
        
        print(f"\n📊 Drawing Categories:")
        for category, items in drawing_categories.items():
            print(f"   {category.upper()}: {len(items)}")
        
        # Show SMC drawings in detail
        if drawing_categories['smc']:
            print(f"\n🎯 SMC Drawings Found:")
            for smc in drawing_categories['smc']:
                print(f"   [{smc['index']}] {smc['type']}")
                print(f"       Metadata: {smc['metadata']}")
                print(f"       Text: {smc['text']}")
        else:
            print(f"\n❌ No SMC drawings found!")
            print(f"   This explains why filtering returns 0 SMC drawings")
        
        # Test filtering logic manually
        print(f"\n🧪 Testing Filtering Logic:")
        drawing_types = ['smc']
        filtered_count = 0
        
        for drawing in drawings:
            metadata = drawing.get('metadata', {})
            if ('smc_type' in metadata or 
                'order_block_type' in metadata or 
                'structure_type' in metadata or
                'equal_level_type' in metadata):
                filtered_count += 1
        
        print(f"   Manual filter result: {filtered_count} SMC drawings")
        
        # Save analysis
        analysis_data = {
            'total_drawings': len(drawings),
            'categories': {k: len(v) for k, v in drawing_categories.items()},
            'smc_drawings': drawing_categories['smc'],
            'manual_filter_count': filtered_count
        }
        
        with open('smc_filtering_analysis.json', 'w') as f:
            json.dump(analysis_data, f, indent=2)
        
        print(f"\n💾 Analysis saved to: smc_filtering_analysis.json")
        
        return len(drawing_categories['smc']) > 0
        
    except Exception as e:
        print(f"❌ Error in analysis: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = analyze_smc_filtering_issue()
    
    print(f"\n" + "=" * 60)
    if success:
        print("✅ SMC drawings are being generated correctly")
        print("   The filtering issue may be elsewhere")
    else:
        print("❌ SMC drawings are NOT being generated")
        print("   This is the root cause of the filtering issue")
    print("=" * 60)