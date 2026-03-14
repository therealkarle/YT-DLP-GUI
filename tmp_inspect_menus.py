import importlib.util, os
src_path = os.path.join(os.path.dirname(__file__), "guiForYT-DLP.py")
spec = importlib.util.spec_from_file_location("gui_module", src_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

app = mod.YTDLPGui()

print('Presets menu items:')
menu = app.preset_menu['menu']
for i in range(menu.index('end') + 1):
    print(' ', menu.entrycget(i, 'label'))

print('\nOutput template menu items:')
menu = app.output_template_menu['menu']
for i in range(menu.index('end') + 1):
    print(' ', menu.entrycget(i, 'label'))

print('\nSB menu items:')
menu = app.sb_preset_menu['menu']
for i in range(menu.index('end') + 1):
    print(' ', menu.entrycget(i, 'label'))

app.destroy()
