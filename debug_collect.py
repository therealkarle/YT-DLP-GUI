import tempfile, os, json
from gui import YTDLPGui

td = tempfile.TemporaryDirectory()
app = YTDLPGui()
app.script_dir = lambda: td.name
app.config = {"yt_dlp_path": "yt-dlp.exe", "last_options": {}}
app.apply_last_options()
print("after apply_last_options sb_enabled=", app.sb_enabled_var.get())
app.sb_enabled_var.set(False)
print("after explicitly setting False sb_enabled=", app.sb_enabled_var.get())
app.toggle_sb_frame()
print("after toggle_sb_frame sb_enabled=", app.sb_enabled_var.get())
app.sb_mark_var.set("")
app.sb_remove_var.set("")
app.sb_title_template.set("")
app.sb_api_var.set("")

app.output_template.set("%(title)s.%(ext)s")
app.format_var.set("mp4")
app.resolution_var.set("1080")
app.preset_var.set("Video 1080p")
app.apply_preset()
print("after apply_preset sb_enabled=", app.sb_enabled_var.get())

opts = app.collect_options()
print("opts:", opts)
print("sb_enabled inside collect options=", app.sb_enabled_var.get())
with open(os.path.join(td.name, "config.json"), encoding="utf-8") as f:
    data = json.load(f)
print("last options:", data.get("last_options"))
