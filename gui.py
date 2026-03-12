import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import json
import os
import subprocess
import threading
import sys

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
        if hasattr(sys, "_MEIPASS"):
            # when packaged by pyinstaller
            return sys._MEIPASS
        return os.path.dirname(os.path.abspath(__file__))

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

        # Options area
        options_frame = ttk.LabelFrame(self, text="Common options")
        options_frame.pack(fill="x", padx=5, pady=5)

        self.output_template = tk.StringVar()
        ttk.Label(options_frame, text="Output template:").grid(row=0, column=0, sticky="w")
        ttk.Entry(options_frame, textvariable=self.output_template, width=40).grid(row=0, column=1, sticky="w")

        # format selection dropdown
        self.format_var = tk.StringVar()
        ttk.Label(options_frame, text="Format:").grid(row=1, column=0, sticky="w")
        formats = ["mp4", "mkv", "webm", "mp3", "wav", "best"]
        ttk.OptionMenu(options_frame, self.format_var, formats[0], *formats).grid(row=1, column=1, sticky="w")

        # resolution selection dropdown
        self.resolution_var = tk.StringVar()
        ttk.Label(options_frame, text="Resolution:").grid(row=2, column=0, sticky="w")
        resolutions = ["1080", "720", "480", "360", "240", "best"]
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
        self.format_var.set(opts.get("format", ""))
        self.resolution_var.set(opts.get("resolution", "best"))
        self.extra_text.delete("1.0", "end")
        self.extra_text.insert("1.0", opts.get("extra", ""))

    def collect_options(self):
        opts = []
        if self.output_template.get():
            opts += ["-o", self.output_template.get()]
        if self.format_var.get():
            opts += ["-f", self.format_var.get()]
        if self.resolution_var.get():
            # yt-dlp uses "-f bestvideo[height<=...]+bestaudio" for resolution; simple approach with "-S" sorting
            res = self.resolution_var.get()
            if res != "best":
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
            messagebox.showwarning("Input required", "Please enter a URL to download.")
            return
        cmd = [self.config.get("yt_dlp_path", "yt-dlp.exe")]
        cmd += self.collect_options()
        cmd.append(url)
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

    def on_cancel(self):
        if self.current_proc and self.current_proc.poll() is None:
            self.log("Terminating process...")
            try:
                self.current_proc.terminate()
            except Exception as e:
                self.log(f"Error terminating process: {e}")
        else:
            self.log("No running process to cancel.")


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

    def browse(self):
        path = filedialog.askopenfilename(title="Select yt-dlp executable",
                                           filetypes=[("Executables", "*.exe;*"), ("All files", "*")])
        if path:
            self.path_var.set(path)

    def on_ok(self):
        self.parent.config["yt_dlp_path"] = self.path_var.get()
        self.parent.save_config()
        self.destroy()


if __name__ == "__main__":
    app = YTDLPGui()
    app.mainloop()
