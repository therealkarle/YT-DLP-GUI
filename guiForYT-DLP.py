import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import json
import os
import platform
import queue
import subprocess
import threading
import sys
import urllib.request
import zipfile
import shutil
import shlex
import tempfile


FFMPEG_RELEASE_API_URLS = [
    "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest",
    "https://api.github.com/repos/yt-dlp/FFmpeg-Builds/releases/latest",
]
HTTP_USER_AGENT = "YT-DLP-GUI/1.0"


# minimal tooltip helper adapted from numerous examples; shows simple text on
# mouse hover.  we use it below for the SponsorBlock category labels.
class ToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tipwindow = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, event=None):
        if self.tipwindow or not self.text:
            return
        x, y, cx, cy = self.widget.bbox("insert") if self.widget.bbox("insert") else (0,0,0,0)
        x = x + self.widget.winfo_rootx() + 20
        y = y + self.widget.winfo_rooty() + 10
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=self.text, justify="left",
                         background="#ffffe0", relief="solid", borderwidth=1,
                         # Pylance expects the font size as an int; using a tuple
                         # with (family, size, style) is the normal Tkinter form
                         # and avoids the earlier type error.
                         font=("tahoma", 8, "normal"))
        label.pack(ipadx=1)

    def hide(self, event=None):
        tw = self.tipwindow
        self.tipwindow = None
        if tw:
            tw.destroy()

# Configuration handling
CONFIG_FILENAME = "config.json"
DEFAULT_CONFIG = {
    "yt_dlp_path": "yt-dlp.exe",
    # whether to ask the user before re-downloading an already existing file
    "ask_overwrite": True,
    # last selected download/output folder (for -o template)
    "last_output_dir": "",
    # directories containing user-defined preset files (JSON)
    # relative paths are resolved relative to the script directory.
    "preset_dirs": ["Presets"],
    "last_options": {
        # previous options saved by collect_options; key names documented in
        # ``collect_options``.  cookies fields added for authentication.
        "cookies_file": "",
        "cookies_browser": "None",
    }
}


class YTDLPGui(tk.Tk):
    # some built‑in presets for commonly used combinations; users may later
    # extend this via configuration if needed
    PRESETS = {
        "Default": {},
        "Audio only": {"format": "mp3", "resolution": "best"},
        "Video 1080p": {"format": "mp4", "resolution": "1080"},
    }

    # Presets for the output template (yt-dlp -o / --output).  The default
    # preset is "Custom" which leaves the field blank so the user can type
    # their own template.
    OUTPUT_TEMPLATE_PRESETS = {
        "Custom": "",
        "Title": "%(title)s.%(ext)s",
        "Uploader - Title": "%(uploader)s - %(title)s.%(ext)s",
        "Date - Title": "%(upload_date)s - %(title)s.%(ext)s",
        "Playlist/Title": "%(playlist)s/%(title)s.%(ext)s",
        "Playlist index - Title": "%(playlist_index)s - %(title)s.%(ext)s",
    }

    SB_PRESETS = {
        "None": {},
        # default preset: just remove sponsors
        "Remove sponsors": {"mark": "", "remove": "sponsor"},
        # extended options
        "Mark+Remove Sponsors": {"mark": "sponsor", "remove": "sponsor"},
        "Mark All": {"mark": "all", "remove": ""},
        "Remove selfpromo and sponsor": {"mark": "", "remove": "sponsor,selfpromo"},
        "Custom Template": {"mark": "", "remove": "", "title": "[SB] %(category_names)l"},
    }
    # full list of standard SponsorBlock categories; used by the picker dialog
    SB_CATEGORIES = [
        "sponsor", "selfpromo", "interaction", "intro",
        "outro", "preview", "hook", "filler",
    ]

    def __init__(self):
        super().__init__()
        self.title("yt-dlp GUI")
        self.config = DEFAULT_CONFIG.copy()

        # Developer inspect mode: Ctrl+Click any widget to open the object browser.
        self._inspect_mode = False
        self.bind_all("<Button-1>", self._inspect_click, add="+")

        self.load_config()
        self.ensure_preset_dirs()
        self.load_user_presets()
        self.create_widgets()

        # Log output from worker threads is written to a queue and flushed on the
        # main/UI thread via ``after``. This prevents Tkinter from getting updated
        # from a background thread (which can cause freezes/stalls).
        self._log_queue = queue.Queue()
        self.after(100, self._process_log_queue)

    def _inspect_click(self, event):
        """If inspect mode is enabled, open the object browser for the clicked widget."""
        if not getattr(self, "_inspect_mode", False):
            return
        # Require Ctrl to avoid interfering with normal clicks.
        if not (event.state & 0x4):
            return
        widget = event.widget
        if widget:
            self.open_object_browser(widget)

    def set_inspect_mode(self, enabled: bool):
        self._inspect_mode = bool(enabled)

    def load_config(self):
        try:
            config_path = os.path.join(self.script_dir(), CONFIG_FILENAME)
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    self.config.update(json.load(f))
        except Exception as e:
            print(f"Failed to load config: {e}")

        # Ensure preset_dirs always exists for backward compatibility.
        if "preset_dirs" not in self.config or not isinstance(self.config.get("preset_dirs"), list):
            self.config["preset_dirs"] = ["Presets"]

    def save_config(self):
        try:
            config_path = os.path.join(self.script_dir(), CONFIG_FILENAME)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            print(f"Failed to save config: {e}")

    def script_dir(self):
        if getattr(sys, "frozen", False):
            return os.path.dirname(os.path.abspath(sys.executable))
        return os.path.dirname(os.path.abspath(__file__))

    def resolve_yt_dlp_path(self) -> str:
        """Return the best yt-dlp executable path for this portable GUI.

        * If the config value is an absolute path, return it unchanged.
        * If it is relative, prefer a file next to the GUI script.
        * Otherwise fall back to searching the system PATH.
        """
        configured = self.config.get("yt_dlp_path", "yt-dlp.exe")
        # if it is already absolute, trust it
        if os.path.isabs(configured):
            return configured
        # prefer a local copy next to the GUI script for portability
        local = os.path.join(self.script_dir(), configured)
        if os.path.isfile(local):
            return local
        # fallback to PATH
        found = shutil.which(configured)
        if found:
            return found
        # last resort: return the original value (may be relative)
        return configured

    def yt_dlp_runtime_dir(self) -> str:
        """Return the directory that should be treated as yt-dlp home base.

        This is derived from the executable we are actually going to run.
        If the executable cannot be resolved to an absolute location, we fall
        back to the GUI script directory.
        """
        exe_path = self.resolve_yt_dlp_path()
        if os.path.isabs(exe_path):
            return os.path.dirname(exe_path)

        local_candidate = os.path.join(self.script_dir(), exe_path)
        if os.path.isfile(local_candidate):
            return os.path.dirname(local_candidate)

        return self.script_dir()

    def preset_dirs(self) -> list[str]:
        """Return the list of configured preset directories as absolute paths.

        Relative paths are resolved relative to the script directory. Any
        user-provided environment variables (e.g. %APPDATA%) are expanded.
        """
        dirs = self.config.get("preset_dirs", []) or []
        out = []
        for d in dirs:
            if not isinstance(d, str) or not d.strip():
                continue
            expanded = os.path.expanduser(os.path.expandvars(d))
            if not os.path.isabs(expanded):
                expanded = os.path.join(self.script_dir(), expanded)
            out.append(os.path.normpath(expanded))
        return out

    def ensure_preset_dirs(self):
        """Create configured preset directories if they don't exist."""
        for d in self.preset_dirs():
            try:
                os.makedirs(d, exist_ok=True)
            except Exception:
                # Ignore failures (may be permission issues); we will just
                # skip those directories later.
                pass

    def load_user_presets(self):
        """Load presets from configured preset directories."""
        # Start with built-in presets then merge user presets.
        self.presets = dict(self.PRESETS)
        self.output_template_presets = dict(self.OUTPUT_TEMPLATE_PRESETS)
        self.sb_presets = dict(self.SB_PRESETS)
        self.extra_presets = {"Custom": ""}

        for preset_dir in self.preset_dirs():
            try:
                for fn in os.listdir(preset_dir):
                    if not fn.lower().endswith(".json"):
                        continue
                    path = os.path.join(preset_dir, fn)
                    preset = self._load_preset_file(path)
                    if not preset:
                        continue
                    self._register_preset(preset, source_path=path)
            except Exception:
                # Ignore unreadable directories
                continue

    def _load_preset_file(self, path: str) -> dict | None:
        """Load and normalize a preset file.

        Supports both the new format (with explicit "type") and some older
        variants where only a value was stored.

        Returns a dict with keys: type, name, data.
        """
        try:
            with open(path, "r", encoding="utf-8") as f:
                obj = json.load(f)
        except Exception:
            self.log(f"Skipping invalid preset file: {path}")
            return None

        if isinstance(obj, str):
            return {
                "type": "output_template",
                "name": os.path.splitext(os.path.basename(path))[0],
                "data": obj,
                "path": path,
            }

        if not isinstance(obj, dict):
            self.log(f"Skipping preset with unsupported type in file: {path}")
            return None

        preset_type = obj.get("type")
        if preset_type not in ("full", "output_template", "sponsorblock", "extra"):
            # Try to infer type from the content.
            data_guess = obj.get("data", obj)
            if isinstance(data_guess, str):
                preset_type = "extra"
            elif isinstance(data_guess, dict):
                if any(k in data_guess for k in ("mark", "remove", "title", "api")):
                    preset_type = "sponsorblock"
                else:
                    preset_type = "full"
            else:
                return None

        # Preset name is always derived from the filename.
        name = os.path.splitext(os.path.basename(path))[0]

        data = obj.get("data")
        if data is None:
            # For backwards compatibility, allow old presets that stored
            # the value directly at the top level.
            data = obj

        return {"type": preset_type, "name": name, "data": data, "path": path}

    def _register_preset(self, preset: dict, source_path: str | None = None):
        """Register a loaded preset into the appropriate in-memory preset store."""
        name = preset["name"]
        store = self._preset_store_for_type(preset["type"])

        # Prefer built-in presets over user-defined ones.
        builtin_names = {
            "full": set(self.PRESETS.keys()),
            "output_template": set(self.OUTPUT_TEMPLATE_PRESETS.keys()),
            "sponsorblock": set(self.SB_PRESETS.keys()),
        }.get(preset["type"], set())

        if name in builtin_names:
            name = f"{name} (custom)"

        # Avoid collisions between multiple user presets.
        orig_name = name
        i = 2
        while name in store:
            name = f"{orig_name} ({i})"
            i += 1

        store[name] = preset["data"]
        return name

    def _preset_store_for_type(self, preset_type: str) -> dict:
        if preset_type == "full":
            return self.presets
        if preset_type == "output_template":
            return self.output_template_presets
        if preset_type == "sponsorblock":
            return self.sb_presets
        if preset_type == "extra":
            return self.extra_presets
        return {}

    def _preset_menu_for_type(self, preset_type: str):
        if preset_type == "full":
            return getattr(self, "preset_menu", None)
        if preset_type == "output_template":
            return getattr(self, "output_template_menu", None)
        if preset_type == "sponsorblock":
            return getattr(self, "sb_preset_menu", None)
        if preset_type == "extra":
            return getattr(self, "extra_preset_menu", None)
        return None

    def _refresh_preset_menu(self, preset_type: str):
        """Update the OptionMenu for the given preset type."""
        menu_widget = self._preset_menu_for_type(preset_type)
        if menu_widget is None:
            return
        menu = menu_widget["menu"]
        menu.delete(0, "end")
        store = self._preset_store_for_type(preset_type)
        for name in store.keys():
            menu.add_command(
                label=name,
                command=lambda n=name, t=preset_type: self._on_preset_selected(t, n),
            )

    def _on_preset_selected(self, preset_type: str, name: str):
        if preset_type == "full":
            self.preset_var.set(name)
            self.apply_preset()
        elif preset_type == "output_template":
            self.output_template_preset_var.set(name)
            self.apply_output_template_preset()
        elif preset_type == "sponsorblock":
            self.sb_preset_var.set(name)
            self.apply_sb_preset()

    def save_preset_to_file(self, preset_type: str, data, name: str | None = None):
        """Save a preset to a JSON file, asking the user where to write it."""
        initial_dir = self.preset_dirs()[0] if self.preset_dirs() else self.script_dir()
        prompt = {
            "full": "Save preset",  # in case we later add a full preset saver
            "output_template": "Save output template preset",
            "sponsorblock": "Save SponsorBlock preset",
        }.get(preset_type, "Save preset")
        path = filedialog.asksaveasfilename(
            title=prompt,
            initialdir=initial_dir,
            defaultextension=".json",
            filetypes=[("YT-DLP GUI preset", "*.json")],
        )
        if not path:
            return
        # Ensure the parent directory exists.
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        except Exception:
            pass
        if not name:
            name = os.path.splitext(os.path.basename(path))[0]
        # The preset name is derived from the filename; do not write it into JSON.
        obj = {"type": preset_type, "data": data}
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(obj, f, indent=2)
        except Exception as e:
            messagebox.showerror("Save preset", f"Failed to save preset:\n{e}")
            return

        # If the user saved outside the current preset folders, add it so it is
        # automatically found on refresh (and on next start).
        saved_dir = os.path.normpath(os.path.dirname(path))
        existing = [os.path.normpath(d) for d in self.preset_dirs()]
        if saved_dir not in existing:
            self.config.setdefault("preset_dirs", []).append(saved_dir)
            self.save_config()

        # Register the newly written preset and refresh the dropdown.
        preset = self._load_preset_file(path)
        if preset:
            name = self._register_preset(preset, source_path=path)
        self._refresh_preset_menu(preset_type)
        # Select the newly saved preset so the user can see it immediately.
        if preset_type == "full":
            self.preset_var.set(name)
        elif preset_type == "output_template":
            self.output_template_preset_var.set(name)
        elif preset_type == "sponsorblock":
            self.sb_preset_var.set(name)
        elif preset_type == "extra":
            self.extra_preset_var.set(name)

    def refresh_presets(self):
        """Refresh user presets from the configured preset directories."""
        self.ensure_preset_dirs()
        self.load_user_presets()
        self._refresh_preset_menu("full")
        self._refresh_preset_menu("output_template")
        self._refresh_preset_menu("sponsorblock")
        self._refresh_preset_menu("extra")
        # If the currently selected presets no longer exist, reset to the first one.
        if self.preset_var.get() not in self.presets:
            self.preset_var.set(next(iter(self.presets), ""))
        if self.output_template_preset_var.get() not in self.output_template_presets:
            self.output_template_preset_var.set(next(iter(self.output_template_presets), "Custom"))
        if self.sb_preset_var.get() not in self.sb_presets:
            self.sb_preset_var.set(next(iter(self.sb_presets), "Remove sponsors"))
        if self.extra_preset_var.get() not in self.extra_presets:
            self.extra_preset_var.set(next(iter(self.extra_presets), "Custom"))

    def save_current_preset(self):
        """Save the current full configuration as a user preset."""
        preset_data = {
            "format": self.format_var.get(),
            "resolution": self.resolution_var.get(),
            "format_custom": self.format_custom_var.get(),
            "resolution_custom": self.resolution_custom_var.get(),
            "output_template": self.output_template.get(),
            "output_dir": self.output_dir_var.get(),
            "extra": self.extra_text.get("1.0", "end").strip(),

            # playlist
            "playlist_yes": bool(self.playlist_yes_var.get()),
            "playlist_items": self.playlist_items_var.get(),
            "playlist_random": bool(self.playlist_random_var.get()),
            "playlist_reverse": bool(self.playlist_reverse_var.get()),
            "skip_errors": self.skip_errors_var.get(),

            # cookies
            "cookies_file": self.cookies_file_var.get(),
            "cookies_browser": self.cookies_browser_var.get(),

            # trim
            "trim_enabled": bool(self.trim_enabled_var.get()),
            "trim_start_mode": self.trim_start_mode_var.get(),
            "trim_start": self.trim_start_var.get(),
            "trim_end_mode": self.trim_end_mode_var.get(),
            "trim_end": self.trim_end_var.get(),
        }
        sb = {
            "mark": self.sb_mark_var.get(),
            "remove": self.sb_remove_var.get(),
            "title": self.sb_title_template.get(),
            "api": self.sb_api_var.get(),
            "enabled": bool(self.sb_enabled_var.get()),
        }
        # Always include SB section so it can be applied/deselected.
        preset_data["sb"] = sb
        self.save_preset_to_file("full", preset_data, name=self.preset_var.get())

    def save_output_template_preset(self):
        tmpl = self.output_template.get().strip()
        if not tmpl:
            messagebox.showwarning("Save output template preset", "Output template is empty.")
            return
        # Use the base filename as the preset name by default
        self.save_preset_to_file("output_template", tmpl)

    def save_sponsorblock_preset(self):
        sb = {
            "mark": self.sb_mark_var.get(),
            "remove": self.sb_remove_var.get(),
            "title": self.sb_title_template.get(),
            "api": self.sb_api_var.get(),
        }
        if not any(sb.values()):
            messagebox.showwarning("Save SponsorBlock preset", "SponsorBlock settings are empty.")
            return
        self.save_preset_to_file("sponsorblock", sb)

    def save_extra_preset(self):
        extra = self.extra_text.get("1.0", "end").strip()
        if not extra:
            messagebox.showwarning("Save extra preset", "Extra arguments are empty.")
            return
        self.save_preset_to_file("extra", extra)

    def apply_extra_preset(self, _=None):
        name = self.extra_preset_var.get()
        value = self.extra_presets.get(name, "")
        self.extra_text.delete("1.0", "end")
        self.extra_text.insert("1.0", value)

    def _portable_runtime_paths(self) -> tuple[str, str, str]:
        """Return normalized runtime, temp and cache directories for yt-dlp."""
        runtime_dir = os.path.abspath(self.yt_dlp_runtime_dir())
        temp_dir = os.path.join(runtime_dir, "yt-dlp-temp")
        cache_dir = os.path.join(runtime_dir, "yt-dlp-cache")

        for path in (temp_dir, cache_dir):
            try:
                os.makedirs(path, exist_ok=True)
            except Exception:
                # yt-dlp can still attempt creation; we avoid hard-failing UI.
                pass

        return runtime_dir, temp_dir, cache_dir

    def _to_portable_subdir(self, raw_value: str, runtime_dir: str, default: str = "Output") -> str:
        """Normalize an output folder value into a portable subdirectory.

        * If the value is empty, return a sensible default.
        * If the value points inside the runtime_dir, return it relative to runtime_dir.
        * Otherwise, keep the absolute path so the user can select folders anywhere.
        """
        value = os.path.expanduser(os.path.expandvars((raw_value or "").strip()))
        if not value:
            return default

        if os.path.isabs(value):
            try:
                rel = os.path.relpath(value, runtime_dir)
                if not rel.startswith("..") and not os.path.isabs(rel):
                    value = rel
                else:
                    value = os.path.normpath(value)
            except Exception:
                value = os.path.normpath(value)

        value = value.replace("\\", "/").strip("/")
        return value or default

    def _args_have_path_type(self, args: list[str], path_type: str) -> bool:
        """Return whether args already contain -P/--paths for a given type."""
        i = 0
        while i < len(args):
            arg = args[i]
            spec = None
            if arg in ("-P", "--paths") and i + 1 < len(args):
                spec = args[i + 1]
                i += 1
            elif arg.startswith("--paths="):
                spec = arg.split("=", 1)[1]

            if spec is not None:
                if path_type == "home":
                    if ":" not in spec or spec.startswith("home:"):
                        return True
                elif spec.startswith(f"{path_type}:"):
                    return True
            i += 1
        return False

    def _args_have_cache_option(self, args: list[str]) -> bool:
        return (
            "--cache-dir" in args
            or "--no-cache-dir" in args
            or any(a.startswith("--cache-dir=") for a in args)
        )

    def ensure_portable_runtime_args(self, args: list[str], include_home: bool = True) -> list[str]:
        """Prepend portability flags unless already explicitly set by user."""
        runtime_dir, temp_dir, cache_dir = self._portable_runtime_paths()
        runtime_norm = runtime_dir.replace("\\", "/")
        temp_norm = temp_dir.replace("\\", "/")
        cache_norm = cache_dir.replace("\\", "/")

        prefix: list[str] = []
        if "--ignore-config" not in args:
            prefix.append("--ignore-config")
        if not self._args_have_cache_option(args):
            prefix += ["--cache-dir", cache_norm]
        if include_home and not self._args_have_path_type(args, "home"):
            prefix += ["-P", f"home:{runtime_norm}"]
        if not self._args_have_path_type(args, "temp"):
            prefix += ["-P", f"temp:{temp_norm}"]

        return prefix + args

    def ffmpeg_dir(self):
        return os.path.join(self.script_dir(), "ffmpeg")

    def ffmpeg_bin_dir(self):
        return os.path.join(self.ffmpeg_dir(), "bin")

    def local_ffmpeg_location(self):
        bin_dir = self.ffmpeg_bin_dir()
        ffmpeg_path = os.path.join(bin_dir, "ffmpeg.exe")
        ffprobe_path = os.path.join(bin_dir, "ffprobe.exe")
        if os.path.isfile(ffmpeg_path) and os.path.isfile(ffprobe_path):
            return bin_dir
        return None

    def find_executable(self, *names):
        local_dirs = [self.ffmpeg_bin_dir(), self.script_dir()]
        for name in names:
            for local_dir in local_dirs:
                candidate = os.path.join(local_dir, name)
                if os.path.isfile(candidate):
                    return candidate

        for name in names:
            path = shutil.which(name)
            if path:
                return path
        return None

    def has_ffmpeg(self):
        return self.find_executable("ffmpeg", "ffmpeg.exe") is not None

    def has_ffprobe(self):
        """Return True if an ffprobe executable can be located.

        yt-dlp requires *both* ffmpeg and ffprobe for many postprocessing
        features (SponsorBlock, chapters, subtitles, etc).  The GUI used
        to test only for ``ffmpeg`` which meant the bundled downloader would
        leave the installation incomplete.  As a result SponsorBlock would
        later fail with "ffprobe not found" even though a working ffmpeg
        binary existed locally.  Detecting both lets us warn the user earlier
        and ensures the managed local installation remains complete.
        """
        return self.find_executable("ffprobe", "ffprobe.exe") is not None

    def has_js_runtime(self):
        # yt-dlp enables **only** deno by default; other engines (node, bun,
        # quickjs) must be manually activated with --js-runtimes.  Checking for
        # anything else would give false confidence because yt-dlp will still
        # warn that no runtime is available unless deno is installed or you
        # explicitly enable another one.
        return self.find_executable("deno", "deno.exe") is not None

    def get_ffmpeg_windows_arch(self):
        machine = platform.machine().lower()
        if "arm" in machine and "64" in machine:
            return "winarm64"
        elif machine in ("x86", "i386", "i686") or sys.maxsize <= 2 ** 32:
            return "win32"
        return "win64"

    def get_ffmpeg_asset_candidates(self):
        arch = self.get_ffmpeg_windows_arch()
        return [
            f"ffmpeg-master-latest-{arch}-gpl-shared.zip",
            f"ffmpeg-master-latest-{arch}-gpl.zip",
        ]

    def _download_json(self, url):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": HTTP_USER_AGENT,
            },
        )
        with urllib.request.urlopen(request) as response:
            return json.load(response)

    def resolve_ffmpeg_release_asset(self):
        candidates = self.get_ffmpeg_asset_candidates()
        last_error = None
        for api_url in FFMPEG_RELEASE_API_URLS:
            try:
                release_data = self._download_json(api_url)
            except Exception as exc:
                last_error = exc
                self.log(f"Error loading FFmpeg release metadata from {api_url}: {exc}")
                continue

            assets = {asset.get("name", ""): asset for asset in release_data.get("assets", [])}
            for asset_name in candidates:
                asset = assets.get(asset_name)
                if asset and asset.get("browser_download_url"):
                    return {
                        "name": asset_name,
                        "browser_download_url": asset["browser_download_url"],
                        "source": api_url,
                    }

        if last_error is not None:
            raise RuntimeError(f"Failed to resolve FFmpeg release asset: {last_error}")
        raise FileNotFoundError(
            "No matching full GPL FFmpeg ZIP asset was found for this Windows architecture."
        )

    def _find_file_in_tree(self, root_dir, filename):
        for current_root, _, files in os.walk(root_dir):
            if filename in files:
                return os.path.join(current_root, filename)
        return None

    def _find_ffmpeg_build_root(self, root_dir):
        for current_root, dirnames, files in os.walk(root_dir):
            if "ffmpeg.exe" in files and "ffprobe.exe" in files:
                return current_root
            if "bin" not in dirnames:
                continue
            bin_dir = os.path.join(current_root, "bin")
            if os.path.isfile(os.path.join(bin_dir, "ffmpeg.exe")) and os.path.isfile(os.path.join(bin_dir, "ffprobe.exe")):
                return current_root
        return None

    def _extract_ffmpeg_archive(self, archive_path, target_dir):
        archive_name = os.path.basename(archive_path).lower()
        if not archive_name.endswith(".zip"):
            raise ValueError(f"Unsupported ffmpeg archive format: {archive_name}")

        with zipfile.ZipFile(archive_path, "r") as archive:
            archive.extractall(target_dir)

        build_root = self._find_ffmpeg_build_root(target_dir)
        if not build_root:
            raise FileNotFoundError("ffmpeg.exe and ffprobe.exe were not found in the downloaded FFmpeg build")
        return build_root

    def _replace_directory(self, source_dir, target_dir):
        backup_dir = None
        if os.path.exists(target_dir):
            backup_dir = target_dir + ".backup"
            if os.path.exists(backup_dir):
                shutil.rmtree(backup_dir)
            os.replace(target_dir, backup_dir)

        try:
            os.replace(source_dir, target_dir)
        except Exception:
            if backup_dir and os.path.exists(backup_dir) and not os.path.exists(target_dir):
                os.replace(backup_dir, target_dir)
            raise
        else:
            if backup_dir and os.path.exists(backup_dir):
                shutil.rmtree(backup_dir)

    def _remove_legacy_ffmpeg_binaries(self):
        for filename in ("ffmpeg.exe", "ffprobe.exe", "ffplay.exe"):
            legacy_path = os.path.join(self.script_dir(), filename)
            if os.path.isfile(legacy_path):
                os.remove(legacy_path)

    def _install_ffmpeg_archive(self, archive_path):
        with tempfile.TemporaryDirectory(dir=self.script_dir(), prefix="ffmpeg-install-") as work_dir:
            extract_dir = os.path.join(work_dir, "extract")
            os.makedirs(extract_dir, exist_ok=True)
            build_root = self._extract_ffmpeg_archive(archive_path, extract_dir)
            staged_dir = os.path.join(work_dir, "ffmpeg")
            shutil.move(build_root, staged_dir)
            self._replace_directory(staged_dir, self.ffmpeg_dir())

        self._remove_legacy_ffmpeg_binaries()
        install_bin_dir = self.local_ffmpeg_location()
        if not install_bin_dir:
            raise FileNotFoundError("FFmpeg installation completed but the local bin directory is incomplete")
        return install_bin_dir

    def check_dependencies(self, url):
        """Return True if all required dependencies appear available.

        If something critical is missing, show a hard error dialog and return
        False so the download is not attempted. We still log the state for
        debugging. This method targets the two common problems seen in the
        bug report: missing *ffmpeg* (needed to merge and thus to get high-
        quality output) and missing a JS runtime (causes YouTube to hide many
        formats; the warning from yt-dlp itself is often not obvious enough).
        """
        fmt = self.format_var.get()
        problems = []

        # missing ffmpeg is the classic problem; warn for any format that
        # might need merging.  we also add a second check for ffprobe so that
        # users activating SponsorBlock or other post‑processing features are
        # alerted early instead of seeing the cryptic yt-dlp error later.
        if not self.has_ffmpeg() and fmt in ("best", "mp4", "mkv", "webm"):
            msg = (
                "ffmpeg was not found on your system or in the local ffmpeg folder next to the GUI. "
                "Without ffmpeg yt-dlp cannot merge separate video+audio streams "
                "and will often fall back to poor pre‑merged files like 360p. "
                "Please install ffmpeg from 'Manage dependencies...'."
            )
            self.log("Warning: " + msg)
            problems.append(msg)

        if not self.has_ffprobe():
            # this warning is intentionally broad; ffprobe is used by many
            # postprocessing helpers such as SponsorBlock, so we surface it
            # regardless of the URL or format.
            msg = (
                "ffprobe was not found on your system or in the local ffmpeg folder next to the GUI. "
                "Many yt-dlp features (SponsorBlock, chapters, metadata, etc.) "
                "require ffprobe to determine the video duration. "
                "Please install ffmpeg (which includes ffprobe) from "
                "'Manage dependencies...'."
            )
            self.log("Warning: " + msg)
            problems.append(msg)

        if ("youtube.com" in url or "youtu.be" in url) and not self.has_js_runtime():
            msg = (
                "No supported JavaScript runtime was detected. yt-dlp enables only "
                "deno by default, and YouTube extraction without any runtime is "
                "deprecated; that often results in a single 360p format. "
                "Install deno (or another engine and pass --js-runtimes) and see "
                "https://github.com/yt-dlp/yt-dlp/wiki/EJS for details."
            )
            self.log("Warning: " + msg)
            problems.append(msg)

        if problems:
            # show a custom dialog so we can display a clickable link and
            # color it; askyesno cannot provide that formatting.
            proceed = self._ask_dependency_dialog(problems)
            if not proceed:
                return False
        return True

    # keep old name for backward compatibility with tests (if any)
    warn_about_missing_dependencies = check_dependencies

    def _ask_dependency_dialog(self, problems):
        """Pop up a modal dialog showing *problems* and ask to proceed.

        A hyperlink to the EJS wiki is included and styled as blue/underlined.
        """
        dlg = tk.Toplevel(self)
        dlg.title("Missing dependencies")
        dlg.transient(self)
        dlg.grab_set()

        msg = "\n\n".join(problems)
        lbl = tk.Label(dlg, text=msg, justify="left", wraplength=400)
        lbl.pack(padx=10, pady=(10, 0))

        # hyperlink label
        link = tk.Label(dlg, text="https://github.com/yt-dlp/yt-dlp/wiki/EJS",
                        fg="blue", cursor="hand2")
        link.pack(padx=10, pady=(0, 10))
        link.bind("<Button-1>", lambda e: __import__("webbrowser").open(link.cget("text")))

        btn_frame = ttk.Frame(dlg)
        btn_frame.pack(pady=(0, 10))
        result = {"proceed": False}
        def do_proceed():
            result["proceed"] = True
            dlg.destroy()
        def do_cancel():
            dlg.destroy()
        ttk.Button(btn_frame, text="Proceed anyway", command=do_proceed).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Cancel", command=do_cancel).pack(side="left", padx=5)

        self.wait_window(dlg)
        return result["proceed"]

    def _ask_demo_url(self):
        """Ask the user if they'd like to download a demo video when no URL is
        provided.  Returns True if the user wants to proceed, False otherwise.

        The dialog contains a clickable, highlighted link to the demo video so
        they can easily copy it or open it in a browser.
        """
        dlg = tk.Toplevel(self)
        dlg.title("Demo-Video")
        dlg.transient(self)
        dlg.grab_set()

        msg = (
            "No URL provided.\n\n"
            'Would you like to download a demo video from my channel "The Real Karle"?'
        )
        lbl = tk.Label(dlg, text=msg, justify="left", wraplength=400)
        lbl.pack(padx=10, pady=(10, 0))

        link_text = "https://www.youtube.com/watch?v=QuAaxY7xDwg&t=9s"
        link = tk.Label(dlg, text=link_text, fg="blue", cursor="hand2")
        link.pack(padx=10, pady=(0, 10))
        link.bind("<Button-1>", lambda e: __import__("webbrowser").open(link_text))

        btn_frame = ttk.Frame(dlg)
        btn_frame.pack(pady=(0, 10))
        result = {"proceed": False}
        def do_proceed():
            result["proceed"] = True
            dlg.destroy()
        def do_cancel():
            dlg.destroy()
        ttk.Button(btn_frame, text="Ja", command=do_proceed).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Nein", command=do_cancel).pack(side="left", padx=5)

        self.wait_window(dlg)
        return result["proceed"]

    def _confirm_overwrite(self, url: str, opts: list | None = None) -> bool:
        """Determine the filename yt-dlp would write and confirm if it exists.

        ``opts`` may be provided as the same list of command-line options that
        will later be passed to yt-dlp (excluding the URL).  Passing the
        options ensures that format/resolution/output-template selections are
        taken into account; previously we built a minimal command here which
        sometimes produced a different filename than the real run.  The list
        may be mutated by this helper: if the user elects to "Download
        anyway" we append ``--force-overwrites`` so the eventual command will
        actually overwrite the existing file.

        Returns ``True`` if the download should proceed.  If the file already
        exists on disk the user is asked with a two‑button dialog; ``False``
        is returned when the user declines.  Any errors while invoking
        yt-dlp simply log the problem and allow the download to continue so
        the helper is non‑intrusive.

        This helper is skipped for playlists since :option:`--get-filename`
        only reports the first entry, and we don't want to repeatedly prompt
        before each item.
        """
        # configuration overrides the check entirely
        if not self.config.get("ask_overwrite", True):
            return True

        # if the caller didn't supply option flags, fall back to recomputing
        # them here.  doing it once in the caller and passing them is preferred
        # because ``collect_options`` saves the config, and we don't want to
        # write twice for a single button press.
        if opts is None:
            opts = self.collect_options()

        # build the command used only for filename determination
        exe_path = self.resolve_yt_dlp_path()
        check_cmd = [exe_path, "--get-filename"]
        # ``opts`` may already contain ``-o``; that is fine
        check_cmd.extend(opts)
        check_cmd.append(url)

        try:
            proc = subprocess.run(
                check_cmd,
                capture_output=True,
                text=True,
                cwd=self.yt_dlp_runtime_dir(),
            )
            if proc.returncode != 0:
                # something went wrong; let yt-dlp handle the normal run
                return True
            filename = proc.stdout.strip().splitlines()[0]
            if not filename:
                return True
            if not os.path.isabs(filename):
                filename = os.path.join(self.yt_dlp_runtime_dir(), filename)
            if os.path.exists(filename):
                self.log(f"Existing file detected: {filename}")
                # custom dialog so we can control the button text
                dlg = tk.Toplevel(self)
                dlg.title("File exists")
                dlg.transient(self)
                dlg.grab_set()

                msg = f"The file '{os.path.basename(filename)}' already exists."
                lbl = tk.Label(dlg, text=msg, justify="left", wraplength=400)
                lbl.pack(padx=10, pady=(10, 0))

                btn_frame = ttk.Frame(dlg)
                btn_frame.pack(pady=(0, 10))
                result = {"proceed": False}
                def do_download():
                    result["proceed"] = True
                    dlg.destroy()
                def do_cancel():
                    dlg.destroy()
                ttk.Button(btn_frame, text="Download anyway", command=do_download).pack(side="left", padx=5)
                ttk.Button(btn_frame, text="Cancel", command=do_cancel).pack(side="left", padx=5)

                self.wait_window(dlg)
                if result["proceed"]:
                    # if the user explicitly wants to continue, make sure we
                    # tell yt-dlp to overwrite the existing file; the default
                    # behaviour is to skip already-downloaded content.
                    if opts is not None and "--force-overwrites" not in opts:
                        opts.append("--force-overwrites")
                return result["proceed"]
        except Exception as e:
            self.log(f"Error checking existing file: {e}")
        return True

    def show_sb_info(self, event=None):
        """Open the SponsorBlock categories wiki directly in the browser.

        Clicking the info icon will no longer pop up a dialog; instead the
        URL is opened straight away.
        """
        link = "https://wiki.sponsor.ajay.app/w/Types"
        # use the standard library webbrowser module to open the link
        __import__("webbrowser").open(link)

    def _show_category_dialog(self, target_var: tk.StringVar):
        """Modal dialog letting the user pick one or more SB categories.

        The chosen items are written back as a comma‑separated string into
        *target_var*.
        """
        dlg = tk.Toplevel(self)
        dlg.title("Choose categories")
        dlg.transient(self)
        dlg.grab_set()

        vars: dict[str, tk.BooleanVar] = {}
        current = target_var.get().split(",") if target_var.get() else []
        for cat in self.SB_CATEGORIES:
            v = tk.BooleanVar(value=cat in current)
            vars[cat] = v
            ttk.Checkbutton(dlg, text=cat, variable=v).pack(anchor="w")

        btn_frame = ttk.Frame(dlg)
        btn_frame.pack(pady=5)

        def select_all():
            for v in vars.values():
                v.set(True)

        def select_none():
            for v in vars.values():
                v.set(False)

        ttk.Button(btn_frame, text="All", command=select_all).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="None", command=select_none).pack(side="left", padx=2)

        def on_ok():
            chosen = [c for c, v in vars.items() if v.get()]
            target_var.set(",".join(chosen))
            dlg.destroy()

        ttk.Button(btn_frame, text="OK", command=on_ok).pack(side="left", padx=2)

        self.wait_window(dlg)

    def browse_cookies(self):
        path = filedialog.askopenfilename(title="Select cookies file",
                                           filetypes=[("Text files", "*.txt;*.cookies;*"), ("All files", "*")])
        if path:
            self.cookies_file_var.set(path)

    def browse_output_dir(self):
        runtime_dir = self.yt_dlp_runtime_dir()
        # Start browsing from the last selection (if available), otherwise from the
        # GUI script folder (more user-friendly than the internal runtime folder).
        initial_dir = self.script_dir()
        raw_selected_output = self.output_dir_var.get().strip()
        if raw_selected_output:
            candidate = os.path.join(runtime_dir, self._to_portable_subdir(raw_selected_output, runtime_dir))
            if os.path.isdir(candidate):
                initial_dir = candidate

        path = filedialog.askdirectory(title="Select output folder", initialdir=initial_dir)
        if path:
            # When the user chooses a folder via the dialog, store the absolute path.
            self.output_dir_var.set(path)
            # ensure the folder exists so yt-dlp can write into it
            try:
                os.makedirs(path, exist_ok=True)
            except Exception:
                pass

    def search_output_dir(self):
        """Open the normal folder selection dialog pre-seeded with the output folder.

        This uses the built-in file dialog (Explorer on Windows) so the user can
        search/navigate and then click "Select Folder".
        """
        runtime_dir = self.yt_dlp_runtime_dir()

        raw_selected_output = self.output_dir_var.get().strip()
        initial_dir = self.script_dir()
        if raw_selected_output:
            abs_current = os.path.join(runtime_dir, self._to_portable_subdir(raw_selected_output, runtime_dir))
            if os.path.isdir(abs_current):
                initial_dir = abs_current

        path = filedialog.askdirectory(title="Select output folder", initialdir=initial_dir)
        if path:
            # When the user chooses a folder via the dialog, store the absolute path.
            self.output_dir_var.set(path)
            # ensure the folder exists so yt-dlp can write into it
            try:
                os.makedirs(path, exist_ok=True)
            except Exception:
                pass

    def create_widgets(self):
        # URL entry and run button
        top_frame = ttk.Frame(self)
        top_frame.pack(fill="x", padx=5, pady=5)

        ttk.Label(top_frame, text="URL:").pack(side="left")
        self.url_var = tk.StringVar()
        ttk.Entry(top_frame, textvariable=self.url_var, width=50).pack(side="left", padx=5)
        ttk.Button(top_frame, text="Run", command=self.on_run).pack(side="left", padx=5)
        ttk.Button(top_frame, text="Cancel", command=self.on_cancel).pack(side="left", padx=5)
        ttk.Button(top_frame, text="Settings", command=self.open_settings).pack(side="left", padx=5)
        ttk.Button(top_frame, text="Readme", command=self.open_readme).pack(side="left", padx=5)
        self.raw_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(top_frame, text="Raw command", variable=self.raw_var,
                        command=self.toggle_raw_mode).pack(side="left", padx=5)

        # Options area
        options_frame = ttk.LabelFrame(self, text="Common options")
        options_frame.pack(fill="x", padx=5, pady=5)

        # preset dropdown sits at the top of common options and allows quick
        # one‑click configuration of other fields
        self.preset_var = tk.StringVar(value=list(self.presets.keys())[0])
        ttk.Label(options_frame, text="Preset:").grid(row=0, column=0, sticky="w")
        preset_names = list(self.presets.keys())
        self.preset_menu = ttk.OptionMenu(options_frame, self.preset_var, preset_names[0], *preset_names,
                                          command=self.apply_preset)
        self.preset_menu.grid(row=0, column=1, sticky="w")
        ttk.Button(options_frame, text="Save preset...", command=self.save_current_preset).grid(row=0, column=2, sticky="w")
        ttk.Button(options_frame, text="Refresh presets", command=self.refresh_presets).grid(row=0, column=3, sticky="w")

        self.output_template = tk.StringVar()
        self.output_template_preset_var = tk.StringVar(value="Custom")
        ttk.Label(options_frame, text="Output template:").grid(row=1, column=0, sticky="w")
        ttk.Entry(options_frame, textvariable=self.output_template, width=30).grid(row=1, column=1, sticky="w")
        self.output_template_menu = ttk.OptionMenu(
            options_frame,
            self.output_template_preset_var,
            "Custom",
            *list(self.output_template_presets.keys()),
            command=self.apply_output_template_preset,
        )
        self.output_template_menu.grid(row=1, column=2, sticky="w")
        ttk.Button(options_frame, text="Save output template preset...", command=self.save_output_template_preset).grid(row=1, column=3, sticky="w")

        self.output_dir_var = tk.StringVar()
        ttk.Label(options_frame, text="Output folder:").grid(row=2, column=0, sticky="w")
        ttk.Entry(options_frame, textvariable=self.output_dir_var, width=30).grid(row=2, column=1, sticky="w")
        ttk.Button(options_frame, text="Browse...", command=self.browse_output_dir).grid(row=2, column=2, sticky="w")
        ttk.Button(options_frame, text="Search...", command=self.search_output_dir).grid(row=2, column=3, sticky="w")

        # format selection dropdown (video and audio formats are visually separated)
        # and allow entering a custom format string.
        self.format_var = tk.StringVar(value="best")
        self.format_custom_var = tk.StringVar()
        ttk.Label(options_frame, text="Format:").grid(row=3, column=0, sticky="w")
        format_menu = ttk.OptionMenu(options_frame, self.format_var, "best")
        format_menu.grid(row=3, column=1, sticky="w")
        # Build menu so we can add non-selectable headers and a custom entry option
        format_menu_menu = format_menu["menu"]
        format_menu_menu.delete(0, "end")
        format_menu_menu.add_command(label="Video formats", state="disabled")
        for v in ["best", "mp4", "mkv", "webm"]:
            format_menu_menu.add_command(label=v, command=lambda v=v: self.format_var.set(v))
        format_menu_menu.add_separator()
        format_menu_menu.add_command(label="Audio formats", state="disabled")
        for v in ["mp3", "wav"]:
            format_menu_menu.add_command(label=v, command=lambda v=v: self.format_var.set(v))
        format_menu_menu.add_separator()
        format_menu_menu.add_command(label="Custom...", command=lambda: self.format_var.set("Custom"))

        self.format_custom_entry = ttk.Entry(options_frame, textvariable=self.format_custom_var,
                                            width=20, state="disabled")
        self.format_custom_entry.grid(row=2, column=2, sticky="w", padx=(5, 0))

        def _update_format_custom(*_args):
            state = "normal" if self.format_var.get() == "Custom" else "disabled"
            self.format_custom_entry.configure(state=state)
        self.format_var.trace_add("write", _update_format_custom)

        # resolution selection dropdown (add 4k/1440 and allow custom value)
        self.resolution_var = tk.StringVar(value="best")
        self.resolution_custom_var = tk.StringVar()
        ttk.Label(options_frame, text="Resolution:").grid(row=4, column=0, sticky="w")
        resolutions = ["best", "4k", "1440", "1080", "720", "480", "360", "240", "Custom"]
        resolution_menu = ttk.OptionMenu(options_frame, self.resolution_var, resolutions[0], *resolutions)
        resolution_menu.grid(row=4, column=1, sticky="w")
        self.resolution_custom_entry = ttk.Entry(options_frame, textvariable=self.resolution_custom_var,
                                                width=20, state="disabled")
        self.resolution_custom_entry.grid(row=4, column=2, sticky="w", padx=(5, 0))

        def _update_resolution_custom(*_args):
            state = "normal" if self.resolution_var.get() == "Custom" else "disabled"
            self.resolution_custom_entry.configure(state=state)
        self.resolution_var.trace_add("write", _update_resolution_custom)

        # authentication options (cookies)
        # users frequently need to supply a cookies file or pull from a browser
        self.cookies_file_var = tk.StringVar()
        ttk.Label(options_frame, text="Cookies file:").grid(row=5, column=0, sticky="w")
        ttk.Entry(options_frame, textvariable=self.cookies_file_var, width=40).grid(row=5, column=1, sticky="w")
        ttk.Button(options_frame, text="Browse...", command=self.browse_cookies).grid(row=5, column=2, sticky="w")

        self.cookies_browser_var = tk.StringVar(value="None")
        lbl_browser = ttk.Label(options_frame, text="Cookies from browser:")
        lbl_browser.grid(row=6, column=0, sticky="w")
        ToolTip(lbl_browser, "Ignored if a cookies file is provided above.")
        browsers = ["None", "chrome", "firefox", "edge", "safari"]
        ttk.OptionMenu(options_frame, self.cookies_browser_var, browsers[0], *browsers).grid(row=6, column=1, sticky="w")

        # ---------- playlist options ----------
        playlist_frame = ttk.LabelFrame(self, text="Playlist options")
        playlist_frame.pack(fill="x", padx=5, pady=5)

        self.playlist_yes_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(playlist_frame, text="Download playlist when available",
                        variable=self.playlist_yes_var).grid(row=0, column=0, sticky="w", padx=5, pady=2)

        ttk.Label(playlist_frame, text="Items (e.g. 1:5,10,-3):").grid(row=1, column=0, sticky="w", padx=5)
        self.playlist_items_var = tk.StringVar()
        ttk.Entry(playlist_frame, textvariable=self.playlist_items_var, width=30).grid(row=1, column=1, sticky="w", padx=5)

        self.playlist_random_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(playlist_frame, text="Random order",
                        variable=self.playlist_random_var).grid(row=2, column=0, sticky="w", padx=5, pady=2)
        self.playlist_reverse_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(playlist_frame, text="Reverse order",
                        variable=self.playlist_reverse_var).grid(row=2, column=1, sticky="w", padx=5, pady=2)

        ttk.Label(playlist_frame, text="Skip after errors:").grid(row=3, column=0, sticky="w", padx=5)
        self.skip_errors_var = tk.StringVar()
        ttk.Entry(playlist_frame, textvariable=self.skip_errors_var, width=5).grid(row=3, column=1, sticky="w", padx=5)

        # trim checkbox and fields will be placed just above the extra
        # arguments section so they stay together visually
        self.trim_enabled_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self, text="Enable Trim",
                        variable=self.trim_enabled_var,
                        command=self.toggle_trim_frame).pack(fill="x", padx=5, pady=2)

        trim_frame = ttk.LabelFrame(self, text="Trim")
        self.trim_frame = trim_frame

        ttk.Label(trim_frame, text="Start:").grid(row=0, column=0, sticky="w", padx=5, pady=2)
        self.trim_start_mode_var = tk.StringVar(value="Timestamp")
        ttk.OptionMenu(trim_frame, self.trim_start_mode_var, "Timestamp", "Timestamp", "Relative").grid(row=0, column=1, sticky="w")
        self.trim_start_var = tk.StringVar()
        ttk.Entry(trim_frame, textvariable=self.trim_start_var, width=20).grid(row=0, column=2, sticky="w", padx=5)

        ttk.Label(trim_frame, text="End:").grid(row=1, column=0, sticky="w", padx=5, pady=2)
        self.trim_end_mode_var = tk.StringVar(value="Timestamp")
        ttk.OptionMenu(trim_frame, self.trim_end_mode_var, "Timestamp", "Timestamp", "Relative").grid(row=1, column=1, sticky="w")
        self.trim_end_var = tk.StringVar()
        ttk.Entry(trim_frame, textvariable=self.trim_end_var, width=20).grid(row=1, column=2, sticky="w", padx=5)

        # sponsorblock checkbox and fields will be placed just above the extra
        # arguments section so they stay together visually
        self.sb_enabled_var = tk.BooleanVar(value=False)
        self.sb_checkbox = ttk.Checkbutton(self, text="Enable SponsorBlock",
                                          variable=self.sb_enabled_var,
                                          command=self.toggle_sb_frame)
        self.sb_checkbox.pack(fill="x", padx=5, pady=2)

        sb_frame = ttk.LabelFrame(self, text="SponsorBlock")
        self.sb_frame = sb_frame
        # preset selector for SponsorBlock
        # start with the user-visible default preset rather than "None"
        default_preset = "Remove sponsors"
        self.sb_preset_var = tk.StringVar(value=default_preset)
        ttk.Label(sb_frame, text="SB preset:").grid(row=0, column=0, sticky="w", padx=5)
        sb_preset_names = list(self.sb_presets.keys())
        self.sb_preset_menu = ttk.OptionMenu(sb_frame, self.sb_preset_var, default_preset, *sb_preset_names,
                                             command=self.apply_sb_preset)
        self.sb_preset_menu.grid(row=0, column=1, sticky="w", padx=5)
        ttk.Button(sb_frame, text="Save SponsorBlock preset...", command=self.save_sponsorblock_preset).grid(row=0, column=2, sticky="w", padx=5)

        lbl_mark = ttk.Label(sb_frame, text="Mark categories:")
        lbl_mark.grid(row=1, column=0, sticky="w", padx=5)
        ToolTip(lbl_mark, "Click the info icon to open SponsorBlock categories in your browser")
        info_mark = tk.Label(sb_frame, text="ℹ️", fg="blue", cursor="hand2")
        info_mark.grid(row=1, column=2, sticky="w")
        info_mark.bind("<Button-1>", lambda e: self.show_sb_info())
        self.sb_mark_var = tk.StringVar()
        sb_mark_entry = ttk.Entry(sb_frame, textvariable=self.sb_mark_var,
                                  width=30)
        sb_mark_entry.grid(row=1, column=1, sticky="w", padx=5)
        ToolTip(sb_mark_entry, "Edit categories as comma-separated plain text (e.g. sponsor,selfpromo) or use the picker button")
        ttk.Button(sb_frame, text="…", width=3,
                   command=lambda: self._show_category_dialog(self.sb_mark_var)).grid(row=1, column=3, sticky="w")

        lbl_remove = ttk.Label(sb_frame, text="Remove categories:")
        lbl_remove.grid(row=2, column=0, sticky="w", padx=5)
        ToolTip(lbl_remove, "Click the info icon to open SponsorBlock categories in your browser")
        info_remove = tk.Label(sb_frame, text="ℹ️", fg="blue", cursor="hand2")
        info_remove.grid(row=2, column=2, sticky="w")
        info_remove.bind("<Button-1>", lambda e: self.show_sb_info())
        self.sb_remove_var = tk.StringVar()
        sb_remove_entry = ttk.Entry(sb_frame, textvariable=self.sb_remove_var,
                                    width=30)
        sb_remove_entry.grid(row=2, column=1, sticky="w", padx=5)
        ToolTip(sb_remove_entry, "Edit categories as comma-separated plain text (e.g. sponsor,selfpromo) or use the picker button")
        ttk.Button(sb_frame, text="…", width=3,
                   command=lambda: self._show_category_dialog(self.sb_remove_var)).grid(row=2, column=3, sticky="w")
        ttk.Label(sb_frame, text="Chapter title template:").grid(row=3, column=0, sticky="w", padx=5)
        self.sb_title_template = tk.StringVar()
        ttk.Entry(sb_frame, textvariable=self.sb_title_template, width=40).grid(row=3, column=1, sticky="w", padx=5)
        ttk.Label(sb_frame, text="API URL (optional):").grid(row=4, column=0, sticky="w", padx=5)
        self.sb_api_var = tk.StringVar()
        ttk.Entry(sb_frame, textvariable=self.sb_api_var, width=40).grid(row=4, column=1, sticky="w", padx=5)
        # hidden until enabled
        
        # Extra args area
        extra_frame = ttk.LabelFrame(self, text="Extra arguments")
        # keep reference for tests/layout checks
        self.extra_frame = extra_frame
        extra_frame.pack(fill="both", expand=True, padx=5, pady=5)

        # Extras preset controls (specialized presets only for the extra field)
        extras_preset_frame = ttk.Frame(extra_frame)
        extras_preset_frame.pack(fill="x", padx=5, pady=(5, 0))
        ttk.Label(extras_preset_frame, text="Extra preset:").pack(side="left")
        self.extra_preset_var = tk.StringVar(value="Custom")
        self.extra_preset_menu = ttk.OptionMenu(
            extras_preset_frame,
            self.extra_preset_var,
            "Custom",
            *list(getattr(self, 'extra_presets', {'Custom': ''}).keys()),
            command=self.apply_extra_preset,
        )
        self.extra_preset_menu.pack(side="left", padx=(5, 0))
        ttk.Button(extras_preset_frame, text="Save extra preset...", command=self.save_extra_preset).pack(side="left", padx=5)

        self.extra_text = tk.Text(extra_frame, height=5)
        self.extra_text.pack(fill="both", expand=True)

        # Log console (also used for raw command input when enabled)
        log_frame = ttk.LabelFrame(self, text="Log")
        log_frame.pack(fill="both", expand=True, padx=5, pady=5)

        # Add a scrollbar so users can quickly scroll through the log output.
        self.log_text = tk.Text(log_frame, state="disabled", height=10, wrap="word")
        log_scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scrollbar.set)

        log_scrollbar.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)

        # load last options if any
        self.apply_last_options()

    def apply_last_options(self):
        # keep output template blank by default; users often expect an empty
        # field and the command‑line tool already uses its own default when
        # nothing is provided.  We deliberately do *not* restore a previously
        # saved template.
        self.output_template.set("")

        # leave the output folder field blank on startup.
        # (we still use the last saved folder internally when running ytdlp,
        # but we don't prefill the UI field automatically.)
        self.output_dir_var.set("")

        opts = self.config.get("last_options", {})
        # restore format selection; preserve custom input if present
        fmt = opts.get("format", "best")
        if fmt == "Custom":
            self.format_var.set("Custom")
            self.format_custom_var.set(opts.get("format_custom", ""))
        else:
            self.format_var.set(fmt)
            self.format_custom_var.set(opts.get("format_custom", ""))

        # restore resolution selection; preserve custom input if present
        res = opts.get("resolution", "best")
        if res == "Custom":
            self.resolution_var.set("Custom")
            self.resolution_custom_var.set(opts.get("resolution_custom", ""))
        else:
            self.resolution_var.set(res)
            self.resolution_custom_var.set(opts.get("resolution_custom", ""))

        self.extra_text.delete("1.0", "end")
        self.extra_text.insert("1.0", opts.get("extra", ""))
        # authentication values
        self.cookies_file_var.set(opts.get("cookies_file", ""))
        cb = opts.get("cookies_browser", "None")
        if cb:
            self.cookies_browser_var.set(cb)
        # preserve last-used preset if available
        preset = opts.get("preset")
        if preset in self.presets:
            self.preset_var.set(preset)
            # adjust other fields to match
            self.apply_preset()
        # sponsorblock state and presets
        # we intentionally **do not** restore the saved enabled flag.  the
        # GUI should always open with SponsorBlock disabled so the checkbox is
        # always off at start; users check it only when they actually want to
        # use the feature.  retaining the old flag would keep it on if they
        # previously had it enabled, which is exactly the behaviour the user
        # reported and that we want to avoid.
        self.sb_enabled_var.set(False)
        # frame is left hidden by default; no need to call toggle_sb_frame().

        sbp = opts.get("sb_preset")
        # migrate old default if present
        if sbp == "Mark+Remove Sponsors":
            sbp = "Remove sponsors"
        if sbp in self.SB_PRESETS:
            self.sb_preset_var.set(sbp)
            # do not apply the preset automatically – the section is off.
            # values will be filled once the user enables SponsorBlock.
        else:
            # if nothing saved, make sure we still show the sensible default
            self.sb_preset_var.set("Remove sponsors")

        # restore trim values but keep the feature disabled by default
        self.trim_start_var.set(opts.get("trim_start", ""))
        self.trim_start_mode_var.set(opts.get("trim_start_mode", "Timestamp"))
        self.trim_end_var.set(opts.get("trim_end", ""))
        self.trim_end_mode_var.set(opts.get("trim_end_mode", "Timestamp"))

    def toggle_trim_frame(self):
        """Show or hide the Trim options frame when the checkbox changes."""
        # Keep ordering consistent: Trim should always appear above SponsorBlock.
        self._repack_optional_frames()

    def toggle_sb_frame(self):
        """Show or hide the SponsorBlock options frame based on the checkbox.

        The checkbox is linked to :attr:`sb_enabled_var`.  When unchecked we
        simply forget the frame so the whole section collapses; when checked we
        repack it immediately before the extra‑arguments area so it appears
        directly under the checkbox instead of at the bottom of the window.

        As a usability nicety, when the user enables SponsorBlock and no remove
        categories have been set yet we default to removing "sponsor" entries.
        """
        if self.sb_enabled_var.get():
            # set a sensible default if nothing specified yet
            if not self.sb_remove_var.get():
                self.sb_remove_var.set("sponsor")
            # select a matching preset if currently the first ("None") entry
            first = list(self.SB_PRESETS.keys())[0]
            if self.sb_preset_var.get() == first:
                # default to the simple "Remove sponsors" preset
                self.sb_preset_var.set("Remove sponsors")
                self.apply_sb_preset()

        self._repack_optional_frames()

    def _repack_optional_frames(self):
        """Ensure Trim and SponsorBlock frames are packed in the desired order.

        The order should always be:
            Trim (if enabled)
            SponsorBlock (if enabled)
            Extra arguments
        """
        self.trim_frame.pack_forget()
        self.sb_frame.pack_forget()

        if self.trim_enabled_var.get():
            # Ensure trim section is directly under the trim checkbox.
            self.trim_frame.pack(fill="x", padx=5, pady=5, before=self.sb_checkbox)
        if self.sb_enabled_var.get():
            self.sb_frame.pack(fill="x", padx=5, pady=5, before=self.extra_frame)

    def _normalize_trim_value(self, mode: str, value: str, is_end: bool) -> str | None:
        """Normalize a trim value based on mode.

        * Timestamp mode: return the raw trimmed string.
        * Relative mode: interpret the value as seconds. For end values,
          return a negative number (e.g. '-16' for 16 seconds from the end).

        Returns None if the input is empty or otherwise invalid.
        """
        val = (value or "").strip()
        if not val:
            return None
        if mode == "Relative":
            if not val.isdigit():
                return None
            return f"-{val}" if is_end else val
        return val

    def apply_preset(self, _=None):
        """Apply the currently selected preset by updating other controls.

        Called automatically when the preset drop‑down changes.  Only a few
        properties are handled for now; additional fields can be added easily.
        """
        p = self.preset_var.get()
        settings = self.presets.get(p, {})
        fmt = settings.get("format")
        if fmt is not None:
            self.format_var.set(fmt)
            # clear any custom text since the preset overrides it
            self.format_custom_var.set("")
        res = settings.get("resolution")
        if res is not None:
            self.resolution_var.set(res)
            # clear any custom text since the preset overrides it
            self.resolution_custom_var.set("")
        # optionally apply other preset fields beyond format/resolution
        # (allows user-defined presets to include additional settings).
        # Apply general fields from the preset, if present.
        if "output_template" in settings:
            self.output_template.set(settings.get("output_template", ""))
            self.output_template_preset_var.set("Custom")

        if "output_dir" in settings:
            self.output_dir_var.set(settings.get("output_dir", ""))

        if "extra" in settings:
            self.extra_text.delete("1.0", "end")
            self.extra_text.insert("1.0", settings.get("extra", ""))

        # Playlist settings
        if "playlist_yes" in settings:
            self.playlist_yes_var.set(bool(settings.get("playlist_yes")))
        if "playlist_items" in settings:
            self.playlist_items_var.set(settings.get("playlist_items", ""))
        if "playlist_random" in settings:
            self.playlist_random_var.set(bool(settings.get("playlist_random")))
        if "playlist_reverse" in settings:
            self.playlist_reverse_var.set(bool(settings.get("playlist_reverse")))
        if "skip_errors" in settings:
            self.skip_errors_var.set(settings.get("skip_errors", ""))

        # Cookies
        if "cookies_file" in settings:
            self.cookies_file_var.set(settings.get("cookies_file", ""))
        if "cookies_browser" in settings:
            self.cookies_browser_var.set(settings.get("cookies_browser", "None"))

        # Trim settings
        if "trim_enabled" in settings:
            self.trim_enabled_var.set(bool(settings.get("trim_enabled")))
        if "trim_start_mode" in settings:
            self.trim_start_mode_var.set(settings.get("trim_start_mode", "Timestamp"))
        if "trim_start" in settings:
            self.trim_start_var.set(settings.get("trim_start", ""))
        if "trim_end_mode" in settings:
            self.trim_end_mode_var.set(settings.get("trim_end_mode", "Timestamp"))
        if "trim_end" in settings:
            self.trim_end_var.set(settings.get("trim_end", ""))

        # SponsorBlock settings
        sb_settings = settings.get("sb")
        if isinstance(sb_settings, dict):
            self.sb_mark_var.set(sb_settings.get("mark", ""))
            self.sb_remove_var.set(sb_settings.get("remove", ""))
            self.sb_title_template.set(sb_settings.get("title", ""))
            self.sb_api_var.set(sb_settings.get("api", ""))
            # if the preset explicitly disables SB, leave it off
            self.sb_enabled_var.set(bool(sb_settings.get("enabled", True)))
            self.sb_preset_var.set("Custom Template")
        self._repack_optional_frames()

    def apply_output_template_preset(self, _=None):
        """Apply a user-facing output template preset to the output field."""
        name = self.output_template_preset_var.get()
        template = self.output_template_presets.get(name, "")
        # always update the entry so the user can still edit it after selecting
        # a preset.
        self.output_template.set(template)

    def apply_sb_preset(self, _=None):
        """Set SponsorBlock fields according to the selected SB_PRESETS entry.

        This updates the mark/remove/title/api values from the named preset.
        **It does not change the enabled checkbox.**  users commonly want to
        examine presets without immediately turning the feature on; letting
        the checkbox stay off keeps SponsorBlock “default off” while still
        providing a convenient way to fill in the fields.
        """
        name = self.sb_preset_var.get()
        settings = self.sb_presets.get(name, {})

        def fmt(val):
            if isinstance(val, (list, tuple)):
                return ",".join(val)
            return val or ""

        self.sb_mark_var.set(fmt(settings.get("mark", "")))
        self.sb_remove_var.set(fmt(settings.get("remove", "")))
        self.sb_title_template.set(settings.get("title", ""))
        self.sb_api_var.set(settings.get("api", ""))
        # do not toggle sb_enabled_var here; the user must explicitly check the
        # box to activate SponsorBlock.  this keeps the default state off even
        # when a non‑None preset is selected.

    def collect_options(self):
        opts = []
        current_preset = self.preset_var.get()

        # Build a portable runtime context for yt-dlp so no user/appdata config
        # and no system temp folders influence the run.
        runtime_dir, _temp_dir, _cache_dir = self._portable_runtime_paths()
        opts += self.ensure_portable_runtime_args([])

        raw_selected_output = self.output_dir_var.get().strip()
        if raw_selected_output:
            output_subdir = self._to_portable_subdir(raw_selected_output, runtime_dir)
        else:
            # Default output folder must always be "Output" when the field is
            # blank; we do not automatically reuse a previously saved folder.
            output_subdir = self._to_portable_subdir("", runtime_dir)

        # If the chosen output folder is absolute, respect it; otherwise place it
        # relative to the yt-dlp runtime directory.
        if os.path.isabs(output_subdir):
            output_dir = output_subdir
        else:
            output_dir = os.path.join(runtime_dir, output_subdir)

        try:
            os.makedirs(output_dir, exist_ok=True)
        except Exception:
            pass

        # Build output template relative to yt-dlp home path (-P home:<runtime>).
        output_template_input = self.output_template.get().strip()
        template_rel = output_template_input if output_template_input else "%(title)s.%(ext)s"

        expanded_template = os.path.expanduser(os.path.expandvars(template_rel))
        if os.path.isabs(expanded_template):
            try:
                rel_template = os.path.relpath(expanded_template, runtime_dir)
                if not rel_template.startswith("..") and not os.path.isabs(rel_template):
                    template_rel = rel_template
                else:
                    template_rel = os.path.basename(expanded_template)
            except Exception:
                template_rel = os.path.basename(expanded_template)

        template_rel = (template_rel or "%(title)s.%(ext)s").replace("\\", "/").lstrip("/")
        out_prefix = output_subdir.replace("\\", "/").strip("/")
        if out_prefix and not template_rel.startswith(f"{out_prefix}/"):
            template_rel = f"{out_prefix}/{template_rel}"

        opts += ["-o", template_rel]

        # remember selection for next run only when the user explicitly chose it
        if raw_selected_output:
            self.config["last_output_dir"] = output_subdir

        fmt = self.format_var.get()
        res = self.resolution_var.get()

        # allow the user to type any yt-dlp format selector when "Custom" is chosen
        if fmt == "Custom":
            fmt_custom = self.format_custom_var.get().strip()
            if fmt_custom:
                opts += ["-f", fmt_custom]
        else:
            # container-style selection for common video formats
            if fmt in ("mp4", "mkv", "webm"):
                opts += ["--merge-output-format", fmt]
            elif fmt == "mp3":
                opts += ["-x", "--audio-format", "mp3"]
            elif fmt == "wav":
                opts += ["-x", "--audio-format", "wav"]

        # allow the user to provide a custom resolution string
        if res == "Custom":
            res_value = self.resolution_custom_var.get().strip()
        else:
            res_value = res

        if res_value and res_value != "best" and fmt not in ("mp3", "wav"):
            opts += ["-S", f"res:{res_value}"]

        extra = self.extra_text.get("1.0", "end").strip()
        if extra:
            opts += extra.split()

        ffmpeg_location = self.local_ffmpeg_location()
        if not ffmpeg_location:
            ffloc = self.find_executable("ffmpeg", "ffmpeg.exe")
            if ffloc:
                ffmpeg_location = os.path.dirname(ffloc)
        if ffmpeg_location:
            opts += ["--ffmpeg-location", ffmpeg_location]

        # authentication options: cookies file wins over browser selection
        if self.cookies_file_var.get():
            opts += ["--cookies", self.cookies_file_var.get()]
        elif self.cookies_browser_var.get() and self.cookies_browser_var.get() != "None":
            opts += ["--cookies-from-browser", self.cookies_browser_var.get()]

        # playlist flags
        if self.playlist_yes_var.get():
            opts.append("--yes-playlist")
        if self.playlist_items_var.get():
            opts += ["--playlist-items", self.playlist_items_var.get()]
        if self.playlist_random_var.get():
            opts.append("--playlist-random")
        if self.playlist_reverse_var.get():
            opts.append("--playlist-reverse")
        if self.skip_errors_var.get():
            opts += ["--skip-playlist-after-errors", self.skip_errors_var.get()]

        # sponsorblock flags - only apply when the feature is enabled
        if self.sb_enabled_var.get():
            if self.sb_mark_var.get():
                opts += ["--sponsorblock-mark", self.sb_mark_var.get()]
            if self.sb_remove_var.get():
                opts += ["--sponsorblock-remove", self.sb_remove_var.get()]
            if self.sb_title_template.get():
                opts += ["--sponsorblock-chapter-title", self.sb_title_template.get()]
            if self.sb_api_var.get():
                opts += ["--sponsorblock-api", self.sb_api_var.get()]

        # trim flags - only apply when the feature is enabled and we have values
        if self.trim_enabled_var.get():
            start = self._normalize_trim_value(self.trim_start_mode_var.get(), self.trim_start_var.get(), is_end=False)
            end = self._normalize_trim_value(self.trim_end_mode_var.get(), self.trim_end_var.get(), is_end=True)
            if start or end:
                if start and end:
                    section = f"*{start}-{end}"
                elif start:
                    section = f"*{start}-inf"
                else:
                    section = f"*0-{end}"
                opts += ["--download-sections", section]

        # save for later (only basic fields).  we intentionally omit the
        # output template so that it remains blank on the next start.
        self.config["last_options"] = {
            "format": self.format_var.get(),
            "format_custom": self.format_custom_var.get(),
            "resolution": self.resolution_var.get(),
            "resolution_custom": self.resolution_custom_var.get(),
            "extra": extra,
            "cookies_file": self.cookies_file_var.get(),
            "cookies_browser": self.cookies_browser_var.get(),
            "trim_start": self.trim_start_var.get(),
            "trim_start_mode": self.trim_start_mode_var.get(),
            "trim_end": self.trim_end_var.get(),
            "trim_end_mode": self.trim_end_mode_var.get(),
        }
        # we do not record ``sb_enabled`` – the app always starts with
        # SponsorBlock turned off.  remembering a preset is still useful so
        # the user can switch on SB and immediately have their preferred
        # values filled.
        sbp_cur = self.sb_preset_var.get()
        if sbp_cur and sbp_cur != list(self.SB_PRESETS.keys())[0]:
            self.config["last_options"]["sb_preset"] = sbp_cur
        # also remember the main preset if it's not the default
        if current_preset and current_preset != list(self.PRESETS.keys())[0]:
            self.config["last_options"]["preset"] = current_preset
        # persist to disk
        self.save_config()
        return opts

    # NOTE: the original implementation of ``on_run`` is duplicated later
    # with support for raw-command editing.  keep only the newer version to
    # avoid the Pylance ``reportRedeclaration`` warning.
    #
    # The old definition has been left physically earlier in the file; remove
    # it entirely so that only the later method exists.

    def run_subprocess(self, cmd):
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=self.yt_dlp_runtime_dir(),
            )
            self.current_proc = proc
            # stdout is guaranteed when we pass PIPE, but the type stubs mark it
            # as Optional[TextIO].  Assert to keep Pylance happy.
            assert proc.stdout is not None
            for line in proc.stdout:
                self.log(line.rstrip())
            proc.wait()
            self.log(f"Process exited with {proc.returncode}")
        except Exception as e:
            self.log(f"Error running command: {e}")
        finally:
            self.current_proc = None

    def log(self, message):
        """Log a message to the UI log panel.

        This method is safe to call from worker threads by enqueueing the
        message; the UI thread periodically flushes the queue.
        """
        try:
            self._log_queue.put_nowait(message)
        except Exception:
            # If something goes wrong (e.g. called before init finishes),
            # fall back to a best-effort direct update.
            try:
                self.log_text.configure(state="normal")
                self.log_text.insert("end", message + "\n")
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
            except Exception:
                pass

    def _process_log_queue(self):
        """Flush queued log messages into the log widget on the main thread."""
        # Drain the queue (non-blocking) to minimize GUI churn.
        messages = []
        while True:
            try:
                messages.append(self._log_queue.get_nowait())
            except queue.Empty:
                break

        if messages:
            self.log_text.configure(state="normal")
            self.log_text.insert("end", "\n".join(messages) + "\n")
            # Keep log size bounded to avoid excessive slowdown.
            max_lines = 2000
            line_count = int(self.log_text.index("end-1c").split(".")[0])
            if line_count > max_lines:
                # Remove the oldest lines.
                remove_lines = line_count - max_lines
                self.log_text.delete("1.0", f"{remove_lines + 1}.0")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")

        # Reschedule the next flush.  Always keep this running for the lifetime
        # of the window.
        try:
            self.after(100, self._process_log_queue)
        except Exception:
            pass

    def open_settings(self):
        SettingsDialog(self)

    def open_readme(self):
        """Open the yt-dlp GitHub README in the default web browser."""
        import webbrowser
        webbrowser.open("https://github.com/yt-dlp/yt-dlp/blob/master/README.md")

    def open_object_browser(self, obj=None):
        """Launch the objbrowser GUI to inspect *obj*.

        If *obj* is None, we inspect the main `yt_dlp` module.

        Note: running objbrowser starts a Qt event loop, which will block the
        Tk mainloop until the object browser window is closed.
        """
        try:
            import objbrowser  # noqa: F401
        except Exception as e:
            messagebox.showerror(
                "Object Browser not available",
                "The 'objbrowser' package could not be imported.\n"
                "Install it with:\n\n"
                "    pip install objbrowser pyside6\n\n"
                f"Error: {e}"
            )
            return

        if obj is None:
            try:
                import yt_dlp
                obj = yt_dlp
            except Exception:
                obj = None

        try:
            # Run objbrowser in-process so we can inspect arbitrary Python objects.
            objbrowser.browse(obj)
        except Exception as e:
            messagebox.showerror("Object Browser", f"Failed to start object browser:\n{e}")

    def toggle_raw_mode(self):
        """Enable or disable raw-command editing in the log field."""
        if self.raw_var.get():
            # allow editing, clear previous log content to start fresh
            self.log_text.configure(state="normal")
            self.log_text.delete("1.0", "end")
            self.log_text.insert("1.0", "# type command-line arguments here (e.g. -o output.mp4 https://...)")
        else:
            # back to log-only mode
            self.log_text.configure(state="disabled")

    def on_run(self):
        # ``url`` is referenced later even when raw mode is enabled; define it
        # upfront so that Pylance knows it always exists and we avoid the
        # "possibly unbound" warning.  similarly, create an empty ``cmd`` list
        # now so that even if a future edit accidentally moves the assignment
        # inside a conditional we won't crash with an UnboundLocalError.
        url: str = ""
        cmd: list = []

        if self.raw_var.get():
            # run exactly what the user typed in the log field
            command_line = self.log_text.get("1.0", "end").strip()
            # ignore comment marker lines
            if not command_line or command_line.startswith("#"):
                messagebox.showwarning("No command", "Please enter yt-dlp command arguments in the log field.")
                return
            args = shlex.split(command_line)
            args = self.ensure_portable_runtime_args(args)
            exe_path = self.resolve_yt_dlp_path()
            cmd = [exe_path] + args
        else:
            url = self.url_var.get().strip()
            if not url:
                # no URL supplied, offer the user a demo video link instead
                if self._ask_demo_url():
                    # user agreed, prepopulate the field so logs/commands are clear
                    url = "https://www.youtube.com/watch?v=QuAaxY7xDwg&t=9s"
                    self.url_var.set(url)
                else:
                    # nothing to do
                    return
            # build the base command after url logic so it's always initialized
            # gather options once so we can use them for the filename check as
            # well as the actual command; ``collect_options`` also persists the
            # settings.
            opts = self.collect_options()
            # if the output file already exists, ask before re-downloading.
            # skip this check for playlists since ``--get-filename`` only
            # reports the first entry and the user would still need to confirm
            # each item manually.
            if not self.playlist_yes_var.get():
                if not self._confirm_overwrite(url, opts):
                    # user declined; abort run
                    return
            # build the final command after the overwrite check so that any
            # mutation of ``opts`` (e.g. adding --force-overwrites) is included
            exe_path = self.resolve_yt_dlp_path()
            cmd = [exe_path]
            cmd += opts
            cmd.append(url)
        # enforce critical dependencies are present; pop up error and abort if not
        if self.raw_var.get():
            if not self.check_dependencies(""):
                return
        else:
            if not self.check_dependencies(url):
                return
        self.log(f"Executing: {' '.join(cmd)}")
        # start process in background and keep reference for cancellation
        self.current_proc = None
        thread = threading.Thread(target=self.run_subprocess, args=(cmd,))
        thread.daemon = True
        thread.start()

    def on_cancel(self):
        if self.current_proc and self.current_proc.poll() is None:
            self.log("Terminating process...")
            try:
                self.current_proc.terminate()
            except Exception as e:
                self.log(f"Error terminating process: {e}")
        else:
            self.log("No running process to cancel.")

    # dependency helpers
    def install_or_update_yt_dlp(self):
        """Install or update yt-dlp itself.

        This is run in a background thread so the UI remains responsive.
        """
        exe_path = self.resolve_yt_dlp_path()
        def worker():
            if os.path.isfile(exe_path):
                self.log(f"Updating yt-dlp using executable: {exe_path}")
                try:
                    subprocess.check_call([exe_path, "-U"])
                    self.log("yt-dlp executable updated successfully.")
                    messagebox.showinfo("Success", "yt-dlp updated via executable.")
                except Exception as e:
                    self.log(f"Executable update failed: {e}")
                    self._pip_install_yt_dlp()
            else:
                self._pip_install_yt_dlp()
        threading.Thread(target=worker, daemon=True).start()

    def _pip_install_yt_dlp(self):
        deps = ["yt-dlp"]
        self.log(f"Installing Python package yt-dlp: {', '.join(deps)}")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-U"] + deps)
            self.log("Python package yt-dlp installed/updated successfully.")
            messagebox.showinfo("Success", "yt-dlp installed via pip.")
        except Exception as e:
            self.log(f"Error installing yt-dlp via pip: {e}")
            messagebox.showerror("Installation error", f"Failed to install yt-dlp:\n{e}")

    def pip_install(self, packages: list[str]):
        """Install or update arbitrary Python packages in a background thread.

        ``packages`` is a list of names that will be passed to ``pip install -U``.
        The output is logged and a message box is shown on success or failure.
        """
        def worker():
            self.log(f"Installing Python packages: {', '.join(packages)}")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", "-U"] + packages)
                self.log("Python packages installed/updated successfully.")
                messagebox.showinfo("Success", f"Installed/updated packages: {', '.join(packages)}")
            except Exception as e:
                self.log(f"Error installing Python packages {packages}: {e}")
                messagebox.showerror("Installation error", f"Failed to install packages:\n{e}")
        threading.Thread(target=worker, daemon=True).start()

    def download_yt_dlp_exe(self):
        """Fetch the latest yt-dlp.exe from GitHub releases and save it next to the script."""
        url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
        dest = os.path.join(self.script_dir(), "yt-dlp.exe")
        def worker():
            self.log(f"Downloading yt-dlp executable from {url}")
            try:
                import urllib.request
                urllib.request.urlretrieve(url, dest)
                self.log(f"Downloaded yt-dlp.exe to {dest}")
                # Prefer the downloaded local copy for portability
                self.config["yt_dlp_path"] = "yt-dlp.exe"
                self.save_config()
                messagebox.showinfo("Downloaded", f"yt-dlp.exe saved to:\n{dest}")
            except Exception as e:
                self.log(f"Error downloading yt-dlp.exe: {e}")
                messagebox.showerror("Download error", f"Failed to download yt-dlp.exe:\n{e}")
        threading.Thread(target=worker, daemon=True).start()

    def _download_ffmpeg_binaries_worker(self):
        """Download the latest full FFmpeg build into a local ffmpeg directory."""
        archive_path = None
        try:
            asset = self.resolve_ffmpeg_release_asset()
            self.log(f"Selected FFmpeg asset {asset['name']} from {asset['source']}")
            with tempfile.TemporaryDirectory(dir=self.script_dir(), prefix="ffmpeg-download-") as work_dir:
                archive_path = os.path.join(work_dir, asset["name"])
                self.log(f"Downloading FFmpeg from {asset['browser_download_url']}")
                urllib.request.urlretrieve(asset["browser_download_url"], archive_path)
                install_bin_dir = self._install_ffmpeg_archive(archive_path)
            self.log(f"FFmpeg installed to {install_bin_dir}")
            messagebox.showinfo(
                "Dependencies",
                f"FFmpeg was installed into:\n{self.ffmpeg_dir()}\n\nThe GUI will now prefer this local full build.",
            )
            return True
        except Exception as ff_e:
            self.log(f"Error downloading FFmpeg: {ff_e}")
            messagebox.showerror("Download error", f"Failed to download FFmpeg:\n{ff_e}")
            return False

    def download_ffmpeg_binaries(self):
        """Download FFmpeg without running the full dependency script."""
        def worker():
            self._download_ffmpeg_binaries_worker()

        threading.Thread(target=worker, daemon=True).start()

    def download_devscripts(self):
        """Download the `devscripts` directory from the yt-dlp repository.

        The directory is extracted into <script_dir>/devscripts and the archive is
        cleaned up. If a previous copy exists, it is replaced.
        """
        archive_url = "https://github.com/yt-dlp/yt-dlp/archive/refs/heads/master.zip"
        temp_zip = os.path.join(self.script_dir(), "yt-dlp-master.zip")
        def worker():
            self.log(f"Downloading devscripts archive from {archive_url}")
            try:
                urllib.request.urlretrieve(archive_url, temp_zip)
                self.log("Archive downloaded")
                with zipfile.ZipFile(temp_zip, 'r') as z:
                    members = [m for m in z.namelist() if m.startswith("yt-dlp-master/devscripts/")]
                    z.extractall(self.script_dir(), members)
                src = os.path.join(self.script_dir(), "yt-dlp-master", "devscripts")
                dst = os.path.join(self.script_dir(), "devscripts")
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                shutil.move(src, dst)
                # cleanup
                shutil.rmtree(os.path.join(self.script_dir(), "yt-dlp-master"))
                os.remove(temp_zip)
                self.log("devscripts directory extracted")
                messagebox.showinfo("Devscripts", "devscripts folder downloaded and ready.")
            except Exception as e:
                self.log(f"Error fetching devscripts: {e}")
                messagebox.showerror("Download error", f"Failed to fetch devscripts:\n{e}")
        threading.Thread(target=worker, daemon=True).start()

    def run_install_deps_script(self):
        """Download and execute the yt-dlp/devscripts/install_deps.py script.

        The output of the script is streamed to our log window. If the script
        exits with a non-zero status, the stderr/stdout are shown in the error
        dialog to help troubleshooting.
        """
        raw_url = "https://raw.githubusercontent.com/yt-dlp/yt-dlp/master/devscripts/install_deps.py"
        dest = os.path.join(self.script_dir(), "install_deps.py")
        toml_url = "https://raw.githubusercontent.com/yt-dlp/yt-dlp/master/pyproject.toml"
        toml_dest = os.path.join(self.script_dir(), "pyproject.toml")
        def worker():
            self.log(f"Fetching install_deps script from {raw_url}")
            try:
                urllib.request.urlretrieve(raw_url, dest)
                self.log(f"Saved install_deps.py to {dest}")
            except Exception as e:
                self.log(f"Error downloading install_deps script: {e}")
                messagebox.showerror("Download error", f"Failed to download install_deps.py:\n{e}")
                return
            # also fetch pyproject.toml so the script can find project metadata
            self.log(f"Fetching pyproject.toml from {toml_url}")
            try:
                urllib.request.urlretrieve(toml_url, toml_dest)
                self.log(f"Saved pyproject.toml to {toml_dest}")
            except Exception as e:
                self.log(f"Error downloading pyproject.toml: {e}")
                # not fatal, script may still work with remote lookup

            # run script and capture output
            self.log("Running install_deps.py")
            try:
                proc = subprocess.Popen(
                    [sys.executable, dest, toml_dest],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    cwd=self.script_dir(),
                )
                assert proc.stdout is not None
                for line in proc.stdout:
                    self.log(line.rstrip())
                proc.wait()
                if proc.returncode == 0:
                    self.log("install_deps.py finished successfully")
                    messagebox.showinfo("Dependencies", "External dependencies installed/updated.")
                else:
                    self.log(f"install_deps.py returned non-zero exit status {proc.returncode}")
                    messagebox.showerror("Execution error",
                                         f"install_deps.py failed with status {proc.returncode}."
                                         " See log for details.")
                    # if the failure looks like missing devscripts, offer pip fallback
                    if proc.returncode != 0:
                        self.log("Running pip fallback for default extras")
                        try:
                            subprocess.check_call([sys.executable, "-m", "pip", "install", "-U", "yt-dlp[default]"])
                            self.log("Pip fallback installed yt-dlp[default]")
                            messagebox.showinfo("Dependencies", "Installed default Python extras via pip.")
                        except Exception as pip_e:
                            self.log(f"Pip fallback also failed: {pip_e}")
            except Exception as e:
                self.log(f"Error running install_deps.py: {e}")
                messagebox.showerror("Execution error", f"install_deps.py failed:\n{e}")
            # after the script runs attempt to install ffmpeg if missing
            if not self.has_ffmpeg() or not self.has_ffprobe():
                self.log("Local FFmpeg not detected; downloading a full build...")
                self._download_ffmpeg_binaries_worker()
            
        threading.Thread(target=worker, daemon=True).start()


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Settings")
        self.parent = parent
        self.create_widgets()

    def create_widgets(self):
        ttk.Label(self, text="Path to yt-dlp executable:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.path_var = tk.StringVar(value=self.parent.config.get("yt_dlp_path", ""))
        ttk.Entry(self, textvariable=self.path_var, width=50).grid(row=0, column=1, sticky="w", padx=5, pady=5)
        ttk.Button(self, text="Browse...", command=self.browse).grid(row=0, column=2, padx=5, pady=5)

        # new setting for overwrite confirmation
        self.ask_overwrite_var = tk.BooleanVar(value=self.parent.config.get("ask_overwrite", True))
        ttk.Checkbutton(self, text="Ask before overwriting existing files",
                        variable=self.ask_overwrite_var).grid(row=1, column=0, columnspan=3, sticky="w", padx=5, pady=(0,5))

        # preset directories (user-defined preset JSON files)
        ttk.Label(self, text="Preset directories:").grid(row=2, column=0, sticky="w", padx=5, pady=(10,0))
        self.preset_dirs_listbox = tk.Listbox(self, height=4, selectmode="single", exportselection=False)
        self.preset_dirs_listbox.grid(row=3, column=0, columnspan=2, sticky="we", padx=5)
        ttk.Button(self, text="Add...", command=self.add_preset_dir).grid(row=3, column=2, sticky="w", padx=5)
        ttk.Button(self, text="Remove", command=self.remove_preset_dir).grid(row=4, column=2, sticky="w", padx=5)
        self._populate_preset_dirs_listbox()

        # dependency management entry point
        ttk.Button(self, text="Dependencies", command=self.open_dependencies).grid(row=5, column=0, columnspan=3, sticky="w", padx=5, pady=(10,5))
        # developer tools are hidden in a separate dialog
        ttk.Button(self, text="Developer options...", command=self.open_developer_options).grid(row=6, column=0, columnspan=3, sticky="w", padx=5, pady=(0,5))
        ttk.Button(self, text="OK", command=self.on_ok).grid(row=7, column=1, pady=5)

    def _populate_preset_dirs_listbox(self):
        self.preset_dirs_listbox.delete(0, "end")
        for d in self.parent.config.get("preset_dirs", []):
            self.preset_dirs_listbox.insert("end", d)

    def add_preset_dir(self):
        path = filedialog.askdirectory(title="Select preset directory")
        if not path:
            return
        dirs = list(self.parent.config.get("preset_dirs", []))
        if path in dirs:
            return
        dirs.append(path)
        self.parent.config["preset_dirs"] = dirs
        self._populate_preset_dirs_listbox()

    def remove_preset_dir(self):
        selection = self.preset_dirs_listbox.curselection()
        if not selection:
            return
        idx = selection[0]
        dirs = list(self.parent.config.get("preset_dirs", []))
        if 0 <= idx < len(dirs):
            dirs.pop(idx)
        self.parent.config["preset_dirs"] = dirs
        self._populate_preset_dirs_listbox()

    def browse(self):
        path = filedialog.askopenfilename(title="Select yt-dlp executable",
                                           filetypes=[("Executables", "*.exe;*"), ("All files", "*")])
        if path:
            self.path_var.set(path)

    def open_developer_options(self):
        DeveloperDialog(self.parent)

    def open_dependencies(self):
        """Open a dialog that lists all known dependencies and their status."""
        DependenciesDialog(self.parent)

    def open_js_help(self):
        import webbrowser
        webbrowser.open("https://github.com/yt-dlp/yt-dlp/wiki/EJS")

    def on_ok(self):
        self.parent.config["yt_dlp_path"] = self.path_var.get()
        self.parent.config["ask_overwrite"] = bool(self.ask_overwrite_var.get())
        # persist preset directories
        self.parent.config["preset_dirs"] = list(self.preset_dirs_listbox.get(0, "end"))
        self.parent.save_config()

        # refresh presets if the directories changed
        self.parent.ensure_preset_dirs()
        self.parent.load_user_presets()
        self.parent._refresh_preset_menu("full")
        self.parent._refresh_preset_menu("output_template")
        self.parent._refresh_preset_menu("sponsorblock")

        self.destroy()


class DeveloperDialog(tk.Toplevel):
    """Dialog containing developer tools and shortcuts."""

    def __init__(self, parent: YTDLPGui):
        super().__init__(parent)
        self.title("Developer options")
        self.parent = parent
        self.create_widgets()

    def create_widgets(self):
        ttk.Label(self, text="Developer tools").grid(row=0, column=0, columnspan=2, sticky="w", padx=5, pady=5)

        self.inspect_mode_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            self,
            text="Ctrl+Click to inspect widgets",
            variable=self.inspect_mode_var,
            command=lambda: self.parent.set_inspect_mode(self.inspect_mode_var.get()),
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=5, pady=5)

        ttk.Button(self, text="Open object browser", command=self.parent.open_object_browser).grid(
            row=2, column=0, columnspan=2, sticky="w", padx=5, pady=5
        )
        ttk.Button(self, text="Close", command=self.destroy).grid(row=3, column=0, columnspan=2, pady=(10, 5))


class DependenciesDialog(tk.Toplevel):
    """Dialog showing status of various yt-dlp dependencies.

    The user can see whether each dependency is currently available and invoke
    installation/update actions.  The implementation aims to mirror the
    information in the yt-dlp README's "Dependencies" section without
    duplicating the entire text.  External binaries are checked with helper
    methods from the main GUI class, while Python packages and extras are
    inspected via import tests or by parsing ``pyproject.toml`` if present.
    """

    STATUS_INSTALLED_COLOR = "#0a7d24"
    STATUS_MISSING_COLOR = "#b42318"

    def __init__(self, parent: YTDLPGui):
        super().__init__(parent)
        self.title("Dependencies")
        self.parent = parent
        self.deps = []  # will hold info about each dependency row
        self.create_widgets()

    def create_widgets(self):
        # gather dependency definitions
        def add_entry(name, check_fn, action_fn, button_text="Install/Update", include_in_install_all=True):
            status = "Installed" if check_fn() else "Missing"
            status_var = tk.StringVar(value=status)
            row = len(self.deps)
            ttk.Label(self, text=name).grid(row=row, column=0, sticky="w", padx=5, pady=2)
            status_label = tk.Label(
                self,
                textvariable=status_var,
                fg=self._status_color(status),
                anchor="w",
            )
            status_label.grid(row=row, column=1, sticky="w", padx=5, pady=2)
            btn = ttk.Button(self, text=button_text,
                             command=lambda cf=check_fn, av=status_var, af=action_fn: self._run_action(cf, av, af))
            btn.grid(row=row, column=2, padx=5, pady=2)
            self.deps.append({
                "check": check_fn,
                "status_var": status_var,
                "status_label": status_label,
                "action": action_fn,
                "include_in_install_all": include_in_install_all,
            })

        # simple checks
        add_entry("yt-dlp executable",
                  lambda: os.path.isfile(self.parent.resolve_yt_dlp_path()),
                  self.parent.install_or_update_yt_dlp)

        add_entry("yt-dlp Python package",
                  lambda: self._is_pkg_installed("yt_dlp"),
                  lambda: self.parent.pip_install(["yt-dlp"]))

        add_entry("ffmpeg/ffprobe binaries",
                  lambda: self.parent.has_ffmpeg() and self.parent.has_ffprobe(),
                  self.parent.download_ffmpeg_binaries,
                  button_text="Download local build")

        add_entry("devscripts folder",
                  lambda: os.path.isdir(os.path.join(self.parent.script_dir(), "devscripts")),
                  self.parent.download_devscripts,
                  button_text="Download")

        add_entry("JavaScript runtime (deno/node/bun/quickjs)",
                  self.parent.has_js_runtime,
                  lambda: __import__("webbrowser").open("https://github.com/yt-dlp/yt-dlp/wiki/EJS"),
                  button_text="Open guide",
                  include_in_install_all=False)

        # extras defined in pyproject.toml, if available
        extras = self.load_pyproject_extras(self.parent.script_dir())
        for group, deps_list in extras.items():
            # skip the build/dev groups
            if group in ("build", "dev", "test", "static-analysis", "pyinstaller"):
                continue
            display = f"Python extras [{group}]"
            add_entry(display,
                      lambda deps=deps_list: self._check_any_pkg(deps),
                      lambda grp=group: self.parent.pip_install([f"yt-dlp[{grp}]"]))

        # control buttons
        controls_row = len(self.deps)
        ttk.Button(self, text="Install dependencies", command=self.parent.run_install_deps_script).grid(
            row=controls_row,
            column=0,
            sticky="w",
            padx=5,
            pady=(10,5),
        )
        ttk.Button(self, text="Install missing", command=self.install_missing).grid(
            row=controls_row,
            column=1,
            padx=5,
            pady=(10,5),
        )
        ttk.Button(self, text="Install/Update All", command=self.install_all).grid(
            row=controls_row,
            column=2,
            sticky="e",
            padx=5,
            pady=(10,5),
        )
        ttk.Button(self, text="Refresh status", command=self.refresh_statuses).grid(
            row=controls_row + 1,
            column=0,
            sticky="w",
            padx=5,
            pady=(0,5),
        )

    def _status_color(self, status: str) -> str:
        return self.STATUS_INSTALLED_COLOR if status == "Installed" else self.STATUS_MISSING_COLOR

    def _refresh_status(self, check_fn, status_var, status_label):
        installed = check_fn()
        status = "Installed" if installed else "Missing"
        status_var.set(status)
        status_label.configure(fg=self._status_color(status))

    def refresh_statuses(self):
        for entry in self.deps:
            self._refresh_status(entry["check"], entry["status_var"], entry["status_label"])

    def _run_action(self, check_fn, status_var, action_fn):
        action_fn()
        status_label = next(entry["status_label"] for entry in self.deps if entry["status_var"] is status_var)
        self._schedule_status_refresh(check_fn, status_var, status_label)

    def _schedule_status_refresh(self, check_fn, status_var, status_label):
        for delay_ms in (0, 1000, 3000):
            self.after(
                delay_ms,
                lambda cf=check_fn, sv=status_var, sl=status_label: self._refresh_status(cf, sv, sl),
            )

    def install_all(self):
        for entry in self.deps:
            if not entry["include_in_install_all"]:
                continue
            self._run_action(entry["check"], entry["status_var"], entry["action"])

    def install_missing(self):
        """Run install/update actions only for entries currently marked "Missing"."""
        for entry in self.deps:
            if entry["status_var"].get() == "Missing" and entry.get("include_in_install_all", True):
                self._run_action(entry["check"], entry["status_var"], entry["action"])

    def _is_pkg_installed(self, pkg_name: str) -> bool:
        try:
            __import__(pkg_name)
            return True
        except ImportError:
            return False

    def _check_any_pkg(self, deps_list: list[str]) -> bool:
        """Return True if at least one of the given requirement strings is importable.

        The strings may contain version specifiers or environment markers; only
        the bare package name is considered.
        """
        for pkg in deps_list:
            # strip off extras, version, and markers
            name = pkg.split(";")[0].strip()
            name = name.split(">=")[0].split("<")[0]
            name = name.split("==")[0].split("!=")[0]
            name = name.replace("-", "_")
            if name and self._is_pkg_installed(name):
                return True
        return False

    @staticmethod
    def load_pyproject_extras(script_dir: str) -> dict:
        """Parse ``pyproject.toml`` and return the optional-dependencies mapping.

        If parsing fails or the file is not found, an empty dict is returned.
        """
        extras = {}
        try:
            import tomllib
        except ImportError:
            tomllib = None
        path = os.path.join(script_dir, "pyproject.toml")
        if tomllib and os.path.isfile(path):
            try:
                with open(path, "rb") as f:
                    data = tomllib.load(f)
                extras = data.get("project", {}).get("optional-dependencies", {}) or {}
            except Exception:
                pass
        return extras


if __name__ == "__main__":
    app = YTDLPGui()
    app.mainloop()
