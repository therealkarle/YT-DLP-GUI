import tempfile, os, json, sys, importlib.util
# load the GUI module by path since its filename contains a hyphen
spec = importlib.util.spec_from_file_location("gui_module",
    os.path.join(os.path.dirname(__file__), "guiForYT-DLP.py"))
module = importlib.util.module_from_spec(spec)
sys.modules["gui_module"] = module
spec.loader.exec_module(module)
YTDLPGui = module.YTDLPGui

td = tempfile.TemporaryDirectory()
app = YTDLPGui()
app.script_dir = lambda: td.name
# simulate previously saved options including cookies
app.config = {"yt_dlp_path": "yt-dlp.exe", "last_options": {"cookies_file": "foo.txt", "cookies_browser": "chrome"}}
app.apply_last_options()
print("after apply_last_options sb_enabled=", app.sb_enabled_var.get(),
      "frame visible=", app.sb_frame.winfo_ismapped())
print("restored cookies file=", app.cookies_file_var.get(),
      "browser=", app.cookies_browser_var.get())
# toggling off manually should hide the frame
app.sb_enabled_var.set(False)
print("after explicitly setting False sb_enabled=", app.sb_enabled_var.get(),
      "frame visible=", app.sb_frame.winfo_ismapped())
app.toggle_sb_frame()
print("after toggle_sb_frame sb_enabled=", app.sb_enabled_var.get(),
      "frame visible=", app.sb_frame.winfo_ismapped())
app.sb_mark_var.set("")
app.sb_remove_var.set("")
app.sb_title_template.set("")
app.sb_api_var.set("")

# select a non-default preset but do not enable SB; checkbox should remain
app.sb_preset_var.set("Mark+Remove Sponsors")
app.apply_sb_preset()
print("after sb preset chosen sb_enabled=", app.sb_enabled_var.get(),
      "frame visible=", app.sb_frame.winfo_ismapped())

# now explicitly enable and check that preset is still applied
app.sb_enabled_var.set(True)
app.toggle_sb_frame()
print("after enabling sb manually sb_enabled=", app.sb_enabled_var.get(),
      "frame visible=", app.sb_frame.winfo_ismapped())

opts = app.collect_options()
print("opts:", opts)
print("sb_enabled inside collect options=", app.sb_enabled_var.get())
# since cookies_file was supplied in config, it should appear in opts
print("cookies flag present?", "--cookies" in opts)
# now test browser-only behaviour
app.cookies_file_var.set("")
app.cookies_browser_var.set("firefox")
opts2 = app.collect_options()
print("opts2 (browser):", opts2)
print("cookies-from-browser flag present?", "--cookies-from-browser" in opts2)
with open(os.path.join(td.name, "config.json"), encoding="utf-8") as f:
    data = json.load(f)
print("last options:", data.get("last_options"))
