"""
Project Reorganization Script
Moves files to utils/ and database_utility/ folders and updates imports
"""

import os
import shutil
import re

# Define file movements
UTILS_FILES = [
    'bulk_stock_selector.py',
    'stock_symbol_resolver.py',
    'model_config.py',
    'newsapi.py',
    'pdf_generator.py',
    'pdf_text_summarizer.py',
    'scrap_pdf_url.py',
    'sentiment_analyzer_adanos.py',
    'sentiment_analyzer.py',
    'stock_news_analyzer.py',
]

DATABASE_FILES = [
    'database.py',
]

# Files that need import updates
FILES_TO_UPDATE = [
    'agent1.py',
    'app_advanced.py',
    'tools.py',
    'bulk_stock_dashboard.py',
]

# Import mapping (old -> new)
IMPORT_MAPPINGS = {
    # Utils imports
    'from bulk_stock_selector import': 'from utils.bulk_stock_selector import',
    'from stock_symbol_resolver import': 'from utils.stock_symbol_resolver import',
    'from model_config import': 'from utils.model_config import',
    'from newsapi import': 'from utils.newsapi import',
    'from pdf_generator import': 'from utils.pdf_generator import',
    'from pdf_text_summarizer import': 'from utils.pdf_text_summarizer import',
    'from scrap_pdf_url import': 'from utils.scrap_pdf_url import',
    'from sentiment_analyzer_adanos import': 'from utils.sentiment_analyzer_adanos import',
    'from sentiment_analyzer import': 'from utils.sentiment_analyzer import',
    'from stock_news_analyzer import': 'from utils.stock_news_analyzer import',
    
    # Database imports
    'from database import': 'from database_utility.database import',
    'import database': 'import database_utility.database as database',
}


def create_folders():
    """Create utils and database_utility folders if they don't exist"""
    os.makedirs('utils', exist_ok=True)
    os.makedirs('database_utility', exist_ok=True)
    print("✅ Created folders: utils/ and database_utility/")


def move_files():
    """Move files to their respective folders"""
    print("\n📦 Moving files...")
    
    # Move utils files
    for file in UTILS_FILES:
        if os.path.exists(file):
            dest = os.path.join('utils', file)
            shutil.copy2(file, dest)  # Copy instead of move for safety
            print(f"  ✅ Copied {file} -> utils/{file}")
        else:
            print(f"  ⚠️  {file} not found")
    
    # Move database files
    for file in DATABASE_FILES:
        if os.path.exists(file):
            dest = os.path.join('database_utility', file)
            shutil.copy2(file, dest)
            print(f"  ✅ Copied {file} -> database_utility/{file}")
        else:
            print(f"  ⚠️  {file} not found")


def update_imports_in_file(filepath):
    """Update imports in a single file"""
    if not os.path.exists(filepath):
        print(f"  ⚠️  {filepath} not found")
        return
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_content = content
    changes_made = []
    
    # Apply import mappings
    for old_import, new_import in IMPORT_MAPPINGS.items():
        if old_import in content:
            content = content.replace(old_import, new_import)
            changes_made.append(f"{old_import} -> {new_import}")
    
    # Write back if changes were made
    if content != original_content:
        # Create backup
        backup_path = f"{filepath}.backup"
        shutil.copy2(filepath, backup_path)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"  ✅ Updated {filepath}")
        for change in changes_made:
            print(f"     - {change}")
        print(f"     (Backup: {backup_path})")
    else:
        print(f"  ℹ️  {filepath} - No changes needed")


def update_all_imports():
    """Update imports in all relevant files"""
    print("\n🔄 Updating imports...")
    
    for file in FILES_TO_UPDATE:
        update_imports_in_file(file)


def create_migration_summary():
    """Create a summary file of the migration"""
    summary = """# Project Reorganization Summary

## Files Moved

### utils/ folder:
"""
    for file in UTILS_FILES:
        summary += f"- {file}\n"
    
    summary += "\n### database_utility/ folder:\n"
    for file in DATABASE_FILES:
        summary += f"- {file}\n"
    
    summary += """
## Import Changes

All imports have been updated in:
"""
    for file in FILES_TO_UPDATE:
        summary += f"- {file}\n"
    
    summary += """
## Next Steps

1. Test the application:
   ```bash
   streamlit run app_advanced.py
   streamlit run bulk_stock_dashboard.py
   ```

2. If everything works, delete the old files:
   ```bash
   # Delete old utils files
"""
    for file in UTILS_FILES:
        summary += f"   del {file}\n"
    
    summary += """
   # Delete old database files
"""
    for file in DATABASE_FILES:
        summary += f"   del {file}\n"
    
    summary += """
3. Delete backup files:
   ```bash
   del *.backup
   ```

## Rollback (if needed)

If something breaks:
1. Restore from backups:
   ```bash
   copy *.backup *.py
   ```
2. Delete new folders:
   ```bash
   rmdir /s /q utils
   rmdir /s /q database_utility
   ```
"""
    
    with open('REORGANIZATION_SUMMARY.md', 'w', encoding='utf-8') as f:
        f.write(summary)
    
    print("\n📄 Created REORGANIZATION_SUMMARY.md")


def main():
    """Main reorganization function"""
    print("="*60)
    print("PROJECT REORGANIZATION SCRIPT")
    print("="*60)
    print("\nThis script will:")
    print("1. Create utils/ and database_utility/ folders")
    print("2. Copy files to new folders (originals kept for safety)")
    print("3. Update imports in all relevant files")
    print("4. Create backups of modified files")
    print("\n⚠️  IMPORTANT: Test after reorganization!")
    print("="*60)
    
    response = input("\nProceed with reorganization? (yes/no): ")
    if response.lower() not in ['yes', 'y']:
        print("❌ Reorganization cancelled")
        return
    
    print("\n🚀 Starting reorganization...\n")
    
    # Step 1: Create folders
    create_folders()
    
    # Step 2: Move files
    move_files()
    
    # Step 3: Update imports
    update_all_imports()
    
    # Step 4: Create summary
    create_migration_summary()
    
    print("\n" + "="*60)
    print("✅ REORGANIZATION COMPLETE!")
    print("="*60)
    print("\n📋 Next steps:")
    print("1. Review REORGANIZATION_SUMMARY.md")
    print("2. Test the application")
    print("3. If working, delete old files")
    print("4. If broken, restore from .backup files")
    print("\n⚠️  Old files are still in root (for safety)")
    print("   Delete them manually after testing!")
    print("="*60)


if __name__ == "__main__":
    main()
