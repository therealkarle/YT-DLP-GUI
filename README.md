# yt-dlp GUI (Windows / Cross-platform)

A simple graphical frontend for **yt-dlp** (https://github.com/yt-dlp/yt-dlp).

This GUI is primarily developed for Windows but should work on any system with **Python 3.10+** and **Tkinter** installed.

---

## 🚀 Quickstart

1. **Download the original yt-dlp** (recommended)
   - Visit: https://github.com/yt-dlp/yt-dlp/releases
   - Download the appropriate `yt-dlp.exe` (Windows) and place it in the same folder as this GUI (`guiForYT-DLP.py`).

2. **Start the GUI**
   - Double-click `guiForYT-DLP.py` (if `.py` is associated with Python)
   - Or open a terminal in the folder and run:
     ```powershell
     python guiForYT-DLP.py
     ```

3. **Get downloading**
   - Enter a video/playlist URL
   - Choose format / resolution / output folder
   - Click **Download**

---

## 🧩 Installation (Detailed)

### Requirements

- **Python 3.10 or newer**
- **Tkinter** (usually bundled with Python)
- **yt-dlp** (as `yt-dlp.exe` or installed as a Python package)
- **ffmpeg** (required for many postprocessing operations like merging, conversions, and SponsorBlock)

### 1) Install Python + Tkinter

- Download Python: https://www.python.org/downloads/
- Make sure to enable *Add Python to PATH* during installation.

### 2) Install yt-dlp

#### Option A: Download yt-dlp executable (recommended for Windows)

- Download `yt-dlp.exe` from:
  https://github.com/yt-dlp/yt-dlp/releases/latest
- Place `yt-dlp.exe` in the same folder as `guiForYT-DLP.py`.

#### Option B: Install yt-dlp via pip

If you prefer pip:

```powershell
python -m pip install -U yt-dlp
```

> Note: The GUI prefers a local `yt-dlp.exe` next to `guiForYT-DLP.py`, but it will also use `yt-dlp` installed via pip if no local executable is found.

---

## ⚙️ Dependencies & Installation

This GUI includes a built-in **Dependencies** dialog that:

- checks whether `yt-dlp` (exe or Python package) is available
- checks whether `ffmpeg` / `ffprobe` are available
- checks for a JS runtime (`deno`, `node`, `bun`, `quickjs`) which yt-dlp uses for sites like YouTube
- lets you download/install missing pieces automatically

### Install ffmpeg quickly

1. Open the GUI
2. Click **Dependencies**
3. Click **Download local build** (installs ffmpeg + ffprobe into the GUI folder)

### Install Python dependencies

In the **Dependencies** dialog you can also install Python extras like `yt-dlp[default]` and other optional dependency sets.

If you prefer manual installation, run:

```powershell
python -m pip install -U yt-dlp[default]
```

---

## 🧭 Usage

### Basic steps

1. **Paste a URL** (video / playlist)
2. **Choose format** (e.g. `mp4`, `mp3`, `best`)
3. **Choose resolution** (e.g. `1080`, `720`, `best`)
4. **Select output folder** (optional)
5. Click **Download**

> Tip: For playlist URLs, yt-dlp will download the whole playlist unless you specify playlist item filters.

### Advanced usage

- The **Settings** dialog lets you:
  - change the `yt-dlp.exe` path
  - control whether the GUI asks before overwriting existing files
- The **Dependencies** dialog lets you install or update tools and Python extras

---

## � Advanced features

### Output template

The **Output template** field controls how yt-dlp names downloaded files. The GUI provides presets, or you can type your own template using yt-dlp placeholders.

Common placeholders:

- `%(title)s` — video title
- `%(ext)s` — file extension
- `%(uploader)s` — channel/uploader name
- `%(playlist_index)s` — video index in the playlist
- `%(playlist)s` — playlist title

Examples:

- `%(title)s.%(ext)s` → `Cool Video.mp4`
- `%(uploader)s - %(title)s.%(ext)s` → `Creator - Cool Video.mp4`
- `%(playlist)s/%(playlist_index)s - %(title)s.%(ext)s` → stores playlist entries in a playlist folder

### Cookies / authentication

Some sites require logged-in sessions. Use one of the following:

- **Cookies file**: select a cookies file you exported from your browser.
- **Cookies from browser**: choose a browser (Chrome/Firefox/Edge/Safari) and the GUI will use yt-dlp's `--cookies-from-browser` support.

If both are set, the cookies file takes priority.

### SponsorBlock (remove/mark sections)

SponsorBlock allows yt-dlp to remove or mark video segments (sponsors, intros, outros, …) using the SponsorBlock API.

In the GUI:

- Enable **SponsorBlock**
- Pick one of the presets (e.g. "Remove sponsors") or customize categories
- Optionally customize the chapter title format and API URL

This is translated to yt-dlp flags like `--sponsorblock-mark`, `--sponsorblock-remove`, and `--sponsorblock-chapter-title`.

### Trim (download part of a video)

The **Trim** section uses yt-dlp’s `--download-sections` to download only part of a video.

- Enter a **Start** and/or **End** timestamp (e.g. `00:01:30` or `1:30`).
- You can also use relative values (e.g. `+1:30`).

If only Start is set, the GUI will use `--download-sections "*START-inf"`. If only End is set, it uses `--download-sections "*0-END"`.

### Extra arguments / Raw command

The **Extra arguments** box lets you pass additional yt-dlp options (space-separated), e.g.:

- `--no-mtime --retries 10`
- `--embed-subs --write-auto-sub`

Enable **Raw command** to type the full argument list directly into the log area. This is useful if you need complete control over the `yt-dlp` command line.

### Playlist options

The playlist section controls yt-dlp playlist behavior:

- **Download playlist when available** (`--yes-playlist`)
- **Items** (`--playlist-items 1:5,10,-3`) to select specific entries
- **Random order** (`--playlist-random`)
- **Reverse order** (`--playlist-reverse`)
- **Skip after errors** (`--skip-playlist-after-errors`)

---

## �🛠️ Troubleshooting / Tips

- **ffmpeg not found**: Ensure `ffmpeg.exe` and `ffprobe.exe` are either in the same folder as `guiForYT-DLP.py` or available on your `PATH`.
- **YouTube downloads only show 360p / slow formats**: Install a JS runtime (`deno`, `node`, etc.). yt-dlp needs a runtime to properly detect formats on YouTube.
- **Portable usage**: Settings are stored in `config.json` next to the script.

---

## 📌 Useful links

- yt-dlp project: https://github.com/yt-dlp/yt-dlp
- yt-dlp Wiki (EJS / JS runtimes): https://github.com/yt-dlp/yt-dlp/wiki/EJS

---

## Cuton-Presets

Cuton‑Presets sind JSON‑Dateien, die Voreinstellungen für verschiedene Bereiche der GUI speichern (z. B. vollständige Presets, Output‑Template, SponsorBlock und Extra‑Argumente). Standardmäßig werden Presets im Ordner `Presets/` im Skript‑Verzeichnis abgelegt; weitere Ordner können in den Einstellungen unter "Preset directories" hinzugefügt werden.

- Typen:
  - `full` — speichert alle GUI‑Einstellungen (Format, Auflösung, Output‑Template, Output‑Ordner, Playlist‑Optionen, Cookies, Trim/Cut (Start/End), SponsorBlock, Extra‑Args usw.).
  - `output_template` — speichert nur die Output‑Template‑Zeichenkette.
  - `sponsorblock` — speichert SponsorBlock‑Konfigurationen (z. B. entfernen/markieren, Kategorien, API‑URL).
  - `extra` — speichert nur den Inhalt der "Extra arguments"‑Textbox.

- Dateiformat:
  - Jede Preset‑Datei ist JSON und enthält nur die Felder `type` und `data` (das Feld `name` wird nicht mehr verwendet). Der in der GUI angezeigte Preset‑Name wird aus dem Dateinamen (ohne `.json`) abgeleitet.
  - Beispiel (vollständiges Preset mit Trim/Cut):

```json
{
  "type": "full",
  "data": {
    "format": "mp4",
    "resolution": "1080",
    "output_template": "%(title)s.%(ext)s",
    "output_dir": "my-output",
    "extra_args": "--no-mtime",
    "playlist": { "yes": true, "items": "1:5" },
    "trim": { "enabled": true, "start": "00:00:30", "end": "00:05:00" },
    "sponsorblock": { "enabled": true, "remove": ["sponsor"] }
  }
}
```

- Verwendung:
  - Preset speichern: Einstellungen setzen und auf „Save Preset“ (für vollständige Presets) oder den jeweiligen „Save … Preset“‑Button neben Output‑Template / SponsorBlock / Extra klicken.
  - Preset anwenden: aus dem entsprechenden Dropdown auswählen.
  - Presets verwalten: Einstellungen → Preset directories zum Hinzufügen/Entfernen von Ordnern nutzen. `Refresh Presets` aktualisiert die Listen in der GUI.
  - Hinweis: Altes JSON‑Format wird beim Laden weiterhin erkannt; beim Speichern neuer Presets wird das Feld `name` nicht geschrieben.

## ❤️ Thanks

This project is built on top of the amazing yt-dlp project. If you find it useful, consider starring the upstream repository ⭐ and supporting the maintainers.
