import importlib.util
import os

src_path = os.path.join(os.path.dirname(__file__), "guiForYT-DLP.py")
spec = importlib.util.spec_from_file_location("gui_module", src_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)  # type: ignore

app = mod.YTDLPGui()
print('preset_dirs:', app.preset_dirs())

print('--- Enumerating preset folder files ---')
for folder in app.preset_dirs():
    try:
        for f in sorted(os.listdir(folder)):
            if not f.lower().endswith('.json'):
                continue
            path = os.path.join(folder, f)
            print('file:', f)
            preset = app._load_preset_file(path)
            print('  loaded:', preset)
    except Exception as e:
        print('  (error listing', folder, e, ')')

print('\n--- menus ---')
print('Presets menu:', list(app.presets.keys()))
print('Output template menu:', list(app.output_template_presets.keys()))
print('SB menu:', list(app.sb_presets.keys()))
