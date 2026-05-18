#!/usr/bin/env python3
"""
Test script to verify chapter functionality in the GUI
"""

import sys
import os
import importlib.util

# Load the GUI module directly from the file name with a dash.
module_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guiForYT-DLP.py")
spec = importlib.util.spec_from_file_location("guiForYT_DLP", module_path)
guiForYT_DLP = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guiForYT_DLP)

try:
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
        'chapter_output_template',
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

    # Test chapter command assembly for both chapter modes
    print("Checking chapter output templates in collect_options()...")
    app.output_dir_var.set("Output")
    app.chapter_output_template.set("%(chapter_number)s_%(chapter_title)s_%(title)s.%(ext)s")
    app.chapters_enabled_var.set(True)
    app.chapters_selection_var.set("all")

    app.chapters_mode_var.set("individual")
    individual_opts = app.collect_options()
    if "-o" not in individual_opts:
        print("ERROR: collect_options() did not emit an output template for individual chapters")
        sys.exit(1)
    individual_template = individual_opts[individual_opts.index("-o") + 1]
    if not individual_template.startswith("chapter:"):
        print(f"ERROR: individual chapter template is missing chapter: prefix: {individual_template}")
        sys.exit(1)
    if "--download-sections" not in individual_opts:
        print("ERROR: individual chapter mode did not emit --download-sections")
        sys.exit(1)
    if individual_opts[individual_opts.index("--download-sections") + 1] != ".*":
        print(f"ERROR: individual chapter mode should use .* for all chapters, got: {individual_opts[individual_opts.index('--download-sections') + 1]}")
        sys.exit(1)
    print(f"Individual chapter template OK: {individual_template}")

    app.chapters_mode_var.set("split")
    split_opts = app.collect_options()
    split_templates = [split_opts[index + 1] for index, value in enumerate(split_opts) if value == "-o" and index + 1 < len(split_opts)]
    chapter_templates = [template for template in split_templates if template.startswith("chapter:")]
    if not chapter_templates:
        print(f"ERROR: split chapter templates are missing chapter: prefix: {split_templates}")
        sys.exit(1)
    if "%(section_number)s" not in chapter_templates[0] or "%(section_title)s" not in chapter_templates[0]:
        print(f"ERROR: split chapter template should use section placeholders, got: {chapter_templates[0]}")
        sys.exit(1)
    if "TEMP_MAIN_FILE.%(ext)s" not in split_templates:
        print(f"ERROR: split mode is missing TEMP_MAIN_FILE output: {split_templates}")
        sys.exit(1)
    print(f"Split chapter template OK: {chapter_templates[0]}")
    
    # Clean up
    root.destroy()
    
    print("\n✅ All tests passed! Chapter functionality is working correctly.")
    
except ImportError as e:
    print(f"ERROR: Could not import GUI: {e}")
    sys.exit(1)
except Exception as e:
    print(f"ERROR: Unexpected error: {e}")
    sys.exit(1)
