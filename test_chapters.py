#!/usr/bin/env python3
"""
Test script to verify chapter functionality in the GUI
"""

import sys
import os

# Add the current directory to the path so we can import the GUI
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import guiForYT_DLP
    # Import the class directly from the module
    YTDLPGui = guiForYT_DLP.YTDLPGui
    import tkinter as tk
    
    # Test if the GUI can be created without errors
    print("Testing GUI creation...")
    
    # Create a test instance (without showing the window)
    root = tk.Tk()
    root.withdraw()  # Hide the window
    
    app = YTDLPGui()
    
    # Test if chapter-related attributes exist
    print("Checking chapter-related attributes...")
    
    chapter_attrs = [
        'chapters_enabled_var',
        'chapters_checkbox', 
        'chapters_frame',
        'chapters_mode_var',
        'chapters_selection_var',
        'chapters_range_var',
        'chapters_template_var',
        'toggle_chapters_frame'
    ]
    
    missing_attrs = []
    for attr in chapter_attrs:
        if not hasattr(app, attr):
            missing_attrs.append(attr)
    
    if missing_attrs:
        print(f"ERROR: Missing attributes: {missing_attrs}")
        sys.exit(1)
    else:
        print("All chapter attributes found ✓")
    
    # Test if the preset includes chapters
    print("Checking presets...")
    if "Download chapters" in app.PRESETS:
        preset = app.PRESETS["Download chapters"]
        print(f"Chapter preset found: {preset}")
        if preset.get("chapters") == True:
            print("Chapter preset has chapters=True ✓")
        else:
            print("ERROR: Chapter preset missing chapters=True")
            sys.exit(1)
    else:
        print("ERROR: 'Download chapters' preset not found")
        sys.exit(1)
    
    # Test toggle function
    print("Testing toggle function...")
    try:
        app.toggle_chapters_frame()
        print("Toggle function works ✓")
    except Exception as e:
        print(f"ERROR: Toggle function failed: {e}")
        sys.exit(1)
    
    # Clean up
    root.destroy()
    
    print("\n✅ All tests passed! Chapter functionality is working correctly.")
    
except ImportError as e:
    print(f"ERROR: Could not import GUI: {e}")
    sys.exit(1)
except Exception as e:
    print(f"ERROR: Unexpected error: {e}")
    sys.exit(1)
