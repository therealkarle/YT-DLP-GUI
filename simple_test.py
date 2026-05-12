#!/usr/bin/env python3
"""
Simple test to verify chapter functionality was added correctly
"""

import sys
import os

# Add the current directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_chapter_functionality():
    """Test if chapter functionality was added to the GUI file"""
    
    gui_file = os.path.join(os.path.dirname(__file__), "guiForYT-DLP.py")
    
    if not os.path.exists(gui_file):
        print("ERROR: guiForYT-DLP.py not found")
        return False
    
    # Read the GUI file and check for chapter-related code
    with open(gui_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for chapter-related additions
    checks = [
        ("Download chapters preset", '"Download chapters": {"format": "mp4", "resolution": "best", "chapters": True}'),
        ("Chapter checkbox", 'self.chapters_checkbox = ttk.Checkbutton'),
        ("Chapter frame", 'self.chapters_frame = chapters_frame'),
        ("Chapter variables", 'self.chapters_enabled_var = tk.BooleanVar'),
        ("Toggle function", 'def toggle_chapters_frame(self):'),
        ("Chapter logic in collect_options", 'if self.chapters_enabled_var.get():'),
        ("Chapter preset application", 'if "chapters" in settings:'),
    ]
    
    print("Testing chapter functionality implementation...")
    all_passed = True
    
    for check_name, check_string in checks:
        if check_string in content:
            print(f"✓ {check_name} - Found")
        else:
            print(f"✗ {check_name} - NOT FOUND")
            all_passed = False
    
    # Check if the _repack_optional_frames method was updated
    if "self.chapters_frame.pack_forget()" in content:
        print("✓ _repack_optional_frames updated for chapters")
    else:
        print("✗ _repack_optional_frames NOT updated for chapters")
        all_passed = False
    
    if all_passed:
        print("\n✅ All chapter functionality tests passed!")
        return True
    else:
        print("\n❌ Some tests failed")
        return False

if __name__ == "__main__":
    success = test_chapter_functionality()
    sys.exit(0 if success else 1)
