# Xplitter_MiniDAW.py
import os, sys, subprocess, threading, json, math
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
import shutil
import numpy as np
import sounddevice as sd
import soundfile as sf
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

plt.style.use('dark_background')

# -------------------------
# Demucs runner (safe decoding)
# -------------------------
def run_demucs(input_file, output_folder, mode, update_status, progress_callback=None):
    """
    mode: 'all' -> full 4-stem htdemucs
          '2stem' -> two-stem vocals (fast karaoke)
    """
    try:
        update_status("Starting Demucs...")
        if mode == '2stem':
            # two-stem (vocals vs no_vocals)
            cmd = [sys.executable, "-m", "demucs", "--two-stems=vocals", "-n", "htdemucs", "-o", output_folder, input_file]
        else:
            # default 4-stem
            cmd = [sys.executable, "-m", "demucs", "-n", "htdemucs", "-o", output_folder, input_file]

        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

        for raw in process.stdout:
            try:
                line = raw.decode('utf-8', errors='replace').strip()
            except Exception:
                line = "<decode error>"
            update_status(line)
            if progress_callback:
                progress_callback()

        process.wait()
        if process.returncode != 0:
            raise RuntimeError("Demucs failed (see output).")

        demucs_subdir = Path(output_folder) / "htdemucs"
        song = Path(input_file).stem
        result_dir = demucs_subdir / song
        if not result_dir.exists():
            raise RuntimeError("Demucs output folder not found.")

        moved = []

        # Move and rename files to consistent naming scheme
        if mode == '2stem':
            # expected files: vocals.wav and no_vocals.wav
            vocals_src = None
            no_vocals_src = None
            for f in result_dir.glob("*.wav"):
                name = f.stem.lower()
                if name == "vocals":
                    vocals_src = f
                elif name in ("no_vocals", "no-vocals", "novocals"):
                    no_vocals_src = f
                # some models may produce slightly different names; check keywords:
                elif "vocals" in name:
                    vocals_src = f
                elif "no_vocals" in name or "no-vocals" in name or "novocals" in name:
                    no_vocals_src = f

            # rename to <song>_vocals.wav and <song>_instrumental.wav
            if vocals_src:
                dest = Path(output_folder) / f"{song}_vocals.wav"
                shutil.move(str(vocals_src), str(dest))
                moved.append(dest.name)
            if no_vocals_src:
                dest2 = Path(output_folder) / f"{song}_instrumental.wav"
                shutil.move(str(no_vocals_src), str(dest2))
                moved.append(dest2.name)
        else:
            # move all standard wavs and prefix with song_
            for wav in result_dir.glob("*.wav"):
                dest = Path(output_folder) / f"{song}_{wav.name}"
                shutil.move(str(wav), str(dest))
                moved.append(dest.name)

        # cleanup
        try:
            shutil.rmtree(demucs_subdir)
        except Exception:
            pass

        update_status("Done! Generated: " + ", ".join(moved))
        return True, moved

    except Exception as e:
        update_status(f"Error: {e}")
        return False, str(e)

# -------------------------
# Stem container
# -------------------------
class Stem:
    def __init__(self, path: Path, max_plot_points=2000):
        self.path = path
        self.data, self.sr = sf.read(str(path), dtype='float32')
        if self.data.ndim == 1:
            self.data = self.data[:, np.newaxis]
        self.muted = False
        self.length = self.data.shape[0]
        # precompute downsampled plot data for speed
        step = max(1, self.length // max_plot_points)
        self.plot_data = self.data[::step, 0]
        self.plot_len = len(self.plot_data)

# -------------------------
# GUI / MiniDAW
# -------------------------
class MiniDAW:
    def __init__(self, root):
        self.root = root
        root.title("Xplitter MiniDAW")
        root.configure(bg="#222222")

        # state
        self.stems = []            # list[Stem]
        self.stream = None
        self.playing = False
        self.play_pos = 0         # in samples
        self.after_id = None
        self.zoom = 1.0

        # Top frame: file, split mode dropdown, GO (replaces old Extract button)
        top = tk.Frame(root, bg="#222222", padx=10, pady=6)
        top.pack(fill='x')

        self.file_var = tk.StringVar(master=root)
        self.status_var = tk.StringVar(master=root, value="Select an audio file to begin.")

        tk.Label(top, text="Audio File:", bg="#222222", fg="white").grid(row=0, column=0, sticky="w")
        tk.Entry(top, textvariable=self.file_var, width=56, bg="#333333", fg="white", insertbackground="white").grid(row=1, column=0, columnspan=2, sticky="w")
        tk.Button(top, text="Browse...", command=self.browse, bg="#555555", fg="white").grid(row=1, column=2, sticky="w")

        # Split mode dropdown (replaces old extract button)
        tk.Label(top, text="Split Mode:", bg="#222222", fg="white").grid(row=0, column=3, padx=(20,4), sticky="w")
        self.split_mode = tk.StringVar(master=root, value="all")  # 'all' or '2stem'
        split_combo = ttk.Combobox(top, textvariable=self.split_mode, state="readonly", width=22)
        split_combo['values'] = ("all", "vocals_and_instrumental")
        # friendly labels
        split_combo_map = {"all": "Split All (vocals, drums, bass, other)",
                           "vocals_and_instrumental": "Vocals & Instrumental (karaoke)"}
        # show friendly label by setting values to friendly text, but keep internal var as keys
        split_combo['values'] = tuple(split_combo_map[k] for k in split_combo_map)
        # map displayed -> internal
        self._split_display_to_key = {v: k for k, v in split_combo_map.items()}
        split_combo.current(0)
        split_combo.grid(row=1, column=3, padx=(20,4), sticky="w")

        # GO button
        go_btn = tk.Button(top, text="GO", command=lambda: self.start_split(mode_key=self._split_display_to_key[split_combo.get()]),
                           bg="#009688", fg="white")
        go_btn.grid(row=1, column=4, padx=(4,0))

        # status / progress
        self.output_dir = Path(os.getcwd()).resolve()
        tk.Label(top, text=f"Output Folder: {self.output_dir}", bg="#222222", fg="white").grid(row=2, column=0, columnspan=3, sticky="w", pady=(6,0))
        self.split_button_placeholder = None  # not used but kept for compatibility
        self.progress = ttk.Progressbar(top, orient="horizontal", length=360, mode="determinate")
        self.progress.grid(row=2, column=3, columnspan=2, sticky="e", padx=(0,10))
        tk.Label(top, textvariable=self.status_var, bg="#222222", fg="white").grid(row=3, column=0, columnspan=5, sticky="w", pady=(8,0))

        # global controls
        controls = tk.Frame(root, bg="#222222", pady=6)
        controls.pack(fill='x')
        self.play_btn = tk.Button(controls, text="Play All", command=self.toggle_play, bg="#009688", fg="white")
        self.play_btn.pack(side="left", padx=6)
        tk.Button(controls, text="Stop All", command=self.stop_all, bg="#E91E63", fg="white").pack(side="left", padx=6)
        tk.Button(controls, text="Save Session", command=self.save_session, bg="#FF9800", fg="white").pack(side="right", padx=6)
        tk.Button(controls, text="Load Session", command=self.load_session, bg="#FF9800", fg="white").pack(side="right", padx=6)

        # waveforms area (scrollable)
        self.canvas = tk.Canvas(root, bg="#222222")
        self.vscroll = tk.Scrollbar(root, orient="vertical", command=self.canvas.yview)
        self.stems_frame = tk.Frame(self.canvas, bg="#222222")
        self.stems_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.stems_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.vscroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vscroll.pack(side="right", fill="y")

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # -------------------------
    # Browse file
    # -------------------------
    def browse(self):
        f = filedialog.askopenfilename(title="Select audio file",
                                       filetypes=[("Audio","*.wav *.mp3 *.flac *.ogg *.m4a")])
        if f:
            self.file_var.set(f)
            self.set_status("Ready: " + os.path.basename(f))

    # -------------------------
    # status helpers
    # -------------------------
    def set_status(self, text):
        self.root.after(0, lambda: self.status_var.set(text))

    def step_progress(self):
        self.root.after(0, lambda: self.progress.step(5))

    # -------------------------
    # Start splitting (worker thread)
    # -------------------------
    def start_split(self, mode_key='all'):
        src = self.file_var.get().strip()
        if not src:
            messagebox.showwarning("No file", "Please select an audio file.")
            return
        if not Path(src).exists():
            messagebox.showerror("Error", "File not found.")
            return

        # clear UI, stop any playback
        self.stop_all()
        for w in self.stems_frame.winfo_children():
            w.destroy()
        self.stems = []
        self.progress['value'] = 0
        self.set_status("Starting extraction...")

        def worker():
            ok, moved = run_demucs(src, str(self.output_dir), '2stem' if mode_key == 'vocals_and_instrumental' else 'all',
                                   update_status=self.set_status, progress_callback=self.step_progress)
            # callback in main thread
            self.root.after(0, lambda: self.on_split_done(ok, moved))

        threading.Thread(target=worker, daemon=True).start()

    def on_split_done(self, ok, moved_files):
        self.progress['value'] = 100
        if not ok:
            messagebox.showerror("Extraction failed", str(moved_files))
            return
        # load moved_files (they are filenames)
        # only load the files we moved (pattern: <song>_*.wav)
        files = moved_files
        # show in UI
        self.load_stems(files)
        self.set_status("Extraction finished.")
        messagebox.showinfo("Done", "Extraction finished and loaded into session.")

    # -------------------------
    # Load stems into UI; creates Matplotlib canvases and binds events
    # -------------------------
    def load_stems(self, filenames):
        max_points = 2000
        for fname in filenames:
            path = Path(self.output_dir) / fname
            if not path.exists():
                continue
            s = Stem(path, max_plot_points=max_points)
            self.stems.append(s)

            # frame
            frame = tk.Frame(self.stems_frame, bg="#222222", pady=6)
            frame.pack(fill="x", padx=6, pady=3)

            # waveform plot
            fig, ax = plt.subplots(figsize=(8, 1.2))
            x = np.arange(s.plot_len)
            ax.plot(x, s.plot_data, color='steelblue', linewidth=0.6)
            cursor_line, = ax.plot([0, 0], [s.plot_data.min(), s.plot_data.max()], color='red', linewidth=1)
            ax.set_xticks([]); ax.set_yticks([]); fig.tight_layout()
            canvas = FigureCanvasTkAgg(fig, master=frame)
            canvas.draw()
            widget = canvas.get_tk_widget()
            widget.pack(side="left", fill="x", expand=True)

            # keep references
            s.fig, s.ax, s.canvas, s.cursor_line = fig, ax, canvas, cursor_line
            s.plot_x = x  # used for snapping
            s.plot_len = s.plot_len

            # bind Matplotlib events (use canvas.mpl_connect)
            s.cid_press = canvas.mpl_connect('button_press_event', lambda e, st=s: self.on_press(e, st))
            s.cid_motion = canvas.mpl_connect('motion_notify_event', lambda e, st=s: self.on_motion(e, st))
            s.cid_release = canvas.mpl_connect('button_release_event', lambda e, st=s: self.on_release(e, st))
            s.cid_scroll = canvas.mpl_connect('scroll_event', lambda e, st=s: self.on_scroll(e, st))

            # controls: title and mute icon (visible on dark bg)
            ctrl = tk.Frame(frame, bg="#222222")
            ctrl.pack(side="right", padx=6)
            tk.Label(ctrl, text=path.name, bg="#222222", fg="white").pack()
            mute_btn = tk.Button(ctrl, text="🔊", bg="#333333", fg="white",
                                 command=lambda st=s: self.toggle_mute(st), width=4)
            mute_btn.pack(pady=4)
            s.mute_btn = mute_btn

        # start cursor updater
        self.start_cursor_loop()

    # -------------------------
    # Matplotlib event handlers (dragging & zoom)
    # -------------------------
    def on_press(self, event, stem):
        # only left-click inside axes
        if event.inaxes != stem.ax:
            return
        # pause playback (user wants to seek)
        self.playing = False
        self.play_btn.config(text="Play All")
        # set drag flag on stem
        stem._dragging = True
        # call drag once
        self._seek_to_event(event, stem)

    def on_motion(self, event, stem):
        if not getattr(stem, "_dragging", False):
            return
        self._seek_to_event(event, stem)

    def on_release(self, event, stem):
        stem._dragging = False

    def _seek_to_event(self, event, stem):
        if event.inaxes != stem.ax:
            return
        x = event.xdata
        if x is None:
            return
        # snap to nearest plotted pixel index
        idx = int(round(x))
        idx = max(0, min(idx, stem.plot_len - 1))
        # convert plotted index -> sample index
        sample = int(idx * (stem.length / stem.plot_len))
        self.play_pos = sample
        # update all cursor lines to new position
        self._update_all_cursors()

    def on_scroll(self, event, stem):
        # zoom centered on mouse x
        step = getattr(event, 'step', None)
        if step is None:
            # older mpl uses button attribute for scroll direction
            step = 1 if getattr(event, 'button', None) == 'up' else -1
        factor = 1.2 if step > 0 else 0.8
        self._zoom_at(event, factor)

    def _zoom_at(self, event, factor):
        # adjust zoom and xlim for all stems
        if not self.stems:
            return
        self.zoom *= factor
        for s in self.stems:
            ax = s.ax
            # current limits in data coords (plotted index)
            x0, x1 = ax.get_xlim()
            mx = event.xdata if event.inaxes == ax and event.xdata is not None else (x0 + x1) / 2.0
            width = (x1 - x0) * (1.0 / factor)
            new_x0 = mx - (mx - x0) * (1.0 / factor)
            new_x1 = new_x0 + width
            # clamp
            new_x0 = max(0, new_x0)
            new_x1 = min(s.plot_len - 1, new_x1)
            ax.set_xlim(new_x0, new_x1)
            s.fig.canvas.draw_idle()

    # -------------------------
    # mute toggle
    # -------------------------
    def toggle_mute(self, stem):
        stem.muted = not stem.muted
        stem.mute_btn.config(text="🔇" if stem.muted else "🔊")

    # -------------------------
    # audio mixing callback
    # -------------------------
    def audio_callback(self, outdata, frames, time, status):
        if not self.playing or not self.stems:
            outdata[:] = np.zeros((frames, 2), dtype='float32') if self.stems else np.zeros((frames, 1), dtype='float32')
            return
        start = self.play_pos
        end = start + frames
        # assume same sample rate & channels for all stems
        channels = self.stems[0].data.shape[1]
        mix = np.zeros((frames, channels), dtype='float32')
        for s in self.stems:
            if s.muted:
                continue
            chunk = s.data[start:end]
            if chunk.shape[0] < frames:
                # pad with zeros
                chunk = np.pad(chunk, ((0, frames - chunk.shape[0]), (0, 0)))
            mix += chunk
        # advance play_pos
        self.play_pos += frames
        if self.play_pos >= self.stems[0].length:
            # reached end -> stop & reset
            self.playing = False
            self.play_pos = 0
            self.play_btn.config(text="Play All")
        outdata[:] = mix

    def toggle_play(self):
        if not self.stems:
            return
        if not self.playing:
            self.playing = True
            if self.stream is None:
                sr = self.stems[0].sr
                channels = self.stems[0].data.shape[1]
                self.stream = sd.OutputStream(samplerate=sr, channels=channels, callback=self.audio_callback)
                self.stream.start()
            self.play_btn.config(text="Pause All")
        else:
            self.playing = False
            self.play_btn.config(text="Play All")

    def stop_all(self):
        self.playing = False
        self.play_pos = 0
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
        self.play_btn.config(text="Play All")
        self._update_all_cursors()

    # -------------------------
    # cursor redraw helpers
    # -------------------------
    def _update_all_cursors(self):
        if not self.stems:
            return
        ratio = self.play_pos / self.stems[0].length if self.stems[0].length > 0 else 0.0
        for s in self.stems:
            pos = int(round(ratio * (s.plot_len - 1)))
            s.cursor_line.set_xdata([pos, pos])
            s.fig.canvas.draw_idle()

    def start_cursor_loop(self):
        if self.after_id is None:
            self.after_id = self.root.after(50, self._cursor_loop)

    def _cursor_loop(self):
        self._update_all_cursors()
        self.after_id = self.root.after(50, self._cursor_loop)

    # -------------------------
    # Save / Load session
    # -------------------------
    def save_session(self):
        if not self.stems:
            messagebox.showwarning("No stems", "No stems in session to save.")
            return
        session = {
            "stems": [s.path.name for s in self.stems],
            "mute": [s.muted for s in self.stems],
            "cursor": self.play_pos
        }
        file = filedialog.asksaveasfilename(title="Save session", defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not file:
            return
        with open(file, "w", encoding="utf-8") as fh:
            json.dump(session, fh, indent=2)
        messagebox.showinfo("Saved", "Session saved")

    def load_session(self):
        file = filedialog.askopenfilename(title="Load session", filetypes=[("JSON", "*.json")])
        if not file:
            return
        with open(file, "r", encoding="utf-8") as fh:
            session = json.load(fh)
        # clear
        for w in self.stems_frame.winfo_children():
            w.destroy()
        self.stems = []
        self.play_pos = session.get("cursor", 0)
        for name, muted in zip(session.get("stems", []), session.get("mute", [])):
            p = Path(self.output_dir) / name
            if p.exists():
                self.load_stems([name])  # reuse loader for each file
        self.set_status("Session loaded")

    # -------------------------
    # cleanup
    # -------------------------
    def on_close(self):
        try:
            self.playing = False
            if self.stream:
                self.stream.stop()
                self.stream.close()
            if self.after_id:
                self.root.after_cancel(self.after_id)
        except Exception:
            pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = MiniDAW(root)
    root.geometry("1200x800")
    root.mainloop()
