import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import json
import os
import subprocess
import threading
import sys
import urllib.request
import zipfile
import shutil

# Configuration handling
CONFIG_FILENAME = "config.json"
DEFAULT_CONFIG = {
    "yt_dlp_path": "yt-dlp.exe",
    "last_options": {}
}


class YTDLPGui(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("yt-dlp GUI")
        self.config = DEFAULT_CONFIG.copy()
        self.load_config()
        self.create_widgets()

    def load_config(self):
        try:
            config_path = os.path.join(self.script_dir(), CONFIG_FILENAME)
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    self.config.update(json.load(f))
        except Exception as e:
            print(f"Failed to load config: {e}")

    def save_config(self):
        try:
            config_path = os.path.join(self.script_dir(), CONFIG_FILENAME)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            print(f"Failed to save config: {e}")

    def script_dir(self):
        # PyInstaller sets a private attribute on sys pointing to the
        # temporary folder where the bundled files are unpacked.  Pylance
        # doesnt know about that attribute, so we silence the warning.
        if hasattr(sys, "_MEIPASS"):  # type: ignore[attr-defined]
            # when packaged by pyinstaller
            return sys._MEIPASS  # type: ignore[attr-defined]
        return os.path.dirname(os.path.abspath(__file__))

    def find_executable(self, *names):
        for name in names:
            path = shutil.which(name)
            if path:
                return path

        script_dir = self.script_dir()
        for name in names:
            candidate = os.path.join(script_dir, name)
            if os.path.isfile(candidate):
                return candidate
        return None

    def has_ffmpeg(self):
        return self.find_executable("ffmpeg", "ffmpeg.exe") is not None

    def has_js_runtime(self):
        # yt-dlp enables **only** deno by default; other engines (node, bun,
        # quickjs) must be manually activated with --js-runtimes.  Checking for
        # anything else would give false confidence because yt-dlp will still
        # warn that no runtime is available unless deno is installed or you
        # explicitly enable another one.
        return self.find_executable("deno", "deno.exe") is not None

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

        if not self.has_ffmpeg() and fmt in ("best", "mp4", "mkv", "webm"):
            msg = (
                "ffmpeg was not found on your system or next to the GUI. "
                "Without ffmpeg yt-dlp cannot merge separate video+audio streams "
                "and will often fall back to poor pre‑merged files like 360p. "
                "Please install ffmpeg or use the 'Install external deps' button."
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

        # Options area
        options_frame = ttk.LabelFrame(self, text="Common options")
        options_frame.pack(fill="x", padx=5, pady=5)

        self.output_template = tk.StringVar()
        ttk.Label(options_frame, text="Output template:").grid(row=0, column=0, sticky="w")
        ttk.Entry(options_frame, textvariable=self.output_template, width=40).grid(row=0, column=1, sticky="w")

        # format selection dropdown
        self.format_var = tk.StringVar(value="best")
        ttk.Label(options_frame, text="Format:").grid(row=1, column=0, sticky="w")
        formats = ["best", "mp4", "mkv", "webm", "mp3", "wav"]
        ttk.OptionMenu(options_frame, self.format_var, formats[0], *formats).grid(row=1, column=1, sticky="w")

        # resolution selection dropdown
        self.resolution_var = tk.StringVar(value="best")
        ttk.Label(options_frame, text="Resolution:").grid(row=2, column=0, sticky="w")
        resolutions = ["best", "1080", "720", "480", "360", "240"]
        ttk.OptionMenu(options_frame, self.resolution_var, resolutions[0], *resolutions).grid(row=2, column=1, sticky="w")

        # Extra args area
        extra_frame = ttk.LabelFrame(self, text="Extra arguments")
        extra_frame.pack(fill="both", expand=True, padx=5, pady=5)
        self.extra_text = tk.Text(extra_frame, height=5)
        self.extra_text.pack(fill="both", expand=True)

        # Log console
        log_frame = ttk.LabelFrame(self, text="Log")
        log_frame.pack(fill="both", expand=True, padx=5, pady=5)
        self.log_text = tk.Text(log_frame, state="disabled", height=10)
        self.log_text.pack(fill="both", expand=True)

        # load last options if any
        self.apply_last_options()

    def apply_last_options(self):
        opts = self.config.get("last_options", {})
        self.output_template.set(opts.get("output_template", ""))
        self.format_var.set(opts.get("format", "best"))
        self.resolution_var.set(opts.get("resolution", "best"))
        self.extra_text.delete("1.0", "end")
        self.extra_text.insert("1.0", opts.get("extra", ""))

    def collect_options(self):
        opts = []
        if self.output_template.get():
            opts += ["-o", self.output_template.get()]

        fmt = self.format_var.get()
        res = self.resolution_var.get()

        if fmt == "mp4":
            opts += ["-t", "mp4"]
        elif fmt == "mkv":
            opts += ["-t", "mkv"]
        elif fmt == "webm":
            opts += ["--merge-output-format", "webm", "--remux-video", "webm"]
        elif fmt == "mp3":
            opts += ["-t", "mp3"]
        elif fmt == "wav":
            opts += ["-x", "--audio-format", "wav"]

        if res and res != "best" and fmt not in ("mp3", "wav"):
            opts += ["-S", f"res:{res}"]

        extra = self.extra_text.get("1.0", "end").strip()
        if extra:
            opts += extra.split()
        # save for later
        self.config["last_options"] = {
            "output_template": self.output_template.get(),
            "format": self.format_var.get(),
            "resolution": self.resolution_var.get(),
            "extra": extra,
        }
        # persist to disk
        self.save_config()
        return opts

    def on_run(self):
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
        cmd = [self.config.get("yt_dlp_path", "yt-dlp.exe")]
        cmd += self.collect_options()
        cmd.append(url)
        # enforce critical dependencies are present; pop up error and abort if not
        if not self.check_dependencies(url):
            return
        self.log(f"Executing: {' '.join(cmd)}")
        # start process in background and keep reference for cancellation
        self.current_proc = None
        thread = threading.Thread(target=self.run_subprocess, args=(cmd,))
        thread.daemon = True
        thread.start()

    def run_subprocess(self, cmd):
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
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
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def open_settings(self):
        SettingsDialog(self)

    def open_readme(self):
        """Open the yt-dlp GitHub README in the default web browser."""
        import webbrowser
        webbrowser.open("https://github.com/yt-dlp/yt-dlp/blob/master/README.md")

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
        exe_path = self.config.get("yt_dlp_path", "yt-dlp.exe")
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
                messagebox.showinfo("Downloaded", f"yt-dlp.exe saved to:\n{dest}")
            except Exception as e:
                self.log(f"Error downloading yt-dlp.exe: {e}")
                messagebox.showerror("Download error", f"Failed to download yt-dlp.exe:\n{e}")
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
            if not self.has_ffmpeg():
                self.log("ffmpeg not detected; downloading static build...")
                try:
                    ff_url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
                    ff_zip = os.path.join(self.script_dir(), "ffmpeg.zip")
                    urllib.request.urlretrieve(ff_url, ff_zip)
                    with zipfile.ZipFile(ff_zip, 'r') as zf:
                        for member in zf.namelist():
                            if member.endswith("ffmpeg.exe"):
                                zf.extract(member, self.script_dir())
                                src = os.path.join(self.script_dir(), member)
                                dst = os.path.join(self.script_dir(), "ffmpeg.exe")
                                shutil.move(src, dst)
                                break
                    os.remove(ff_zip)
                    self.log("ffmpeg downloaded to script directory")
                    messagebox.showinfo("Dependencies", "ffmpeg downloaded and placed next to GUI.")
                except Exception as ff_e:
                    self.log(f"Error downloading ffmpeg: {ff_e}")
                    # not fatal, just inform
            
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
        ttk.Button(self, text="OK", command=self.on_ok).grid(row=1, column=1, pady=5)

        # dependency installation buttons all in one row
        ttk.Label(self, text="Dependencies:").grid(row=2, column=0, columnspan=3, sticky="w", padx=5, pady=(10,2))
        ttk.Button(self, text="Install/Update yt-dlp", command=self.parent.install_or_update_yt_dlp).grid(row=3, column=0, sticky="w", padx=2, pady=2)
        ttk.Button(self, text="Install external deps", command=self.parent.run_install_deps_script).grid(row=3, column=1, sticky="w", padx=2, pady=2)
        ttk.Button(self, text="Download devscripts folder", command=self.parent.download_devscripts).grid(row=3, column=2, sticky="w", padx=2, pady=2)
        # helpful link for JavaScript runtimes required by YouTube
        ttk.Button(self, text="JS runtime info", command=self.open_js_help).grid(row=4, column=0, columnspan=3, sticky="w", padx=5, pady=(10,2))


    def browse(self):
        path = filedialog.askopenfilename(title="Select yt-dlp executable",
                                           filetypes=[("Executables", "*.exe;*"), ("All files", "*")])
        if path:
            self.path_var.set(path)

    def open_js_help(self):
        import webbrowser
        webbrowser.open("https://github.com/yt-dlp/yt-dlp/wiki/EJS")

    def on_ok(self):
        self.parent.config["yt_dlp_path"] = self.path_var.get()
        self.parent.save_config()
        self.destroy()


if __name__ == "__main__":
    app = YTDLPGui()
    app.mainloop()
