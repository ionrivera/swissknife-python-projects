import os
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

class VideoToMP3ConverterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Enhanced Video to MP3 Converter (FFmpeg)")
        self.root.geometry("700x500")
        self.root.resizable(False, False)

        self.file_paths = []  # store selected files
        self.bitrate = tk.StringVar(value="192k")
        self.sample_rate = tk.StringVar(value="44100")
        self.delete_original = tk.BooleanVar(value=False)

        # File selection
        tk.Label(root, text="Select Video Files to Convert:").pack(pady=5)
        path_frame = tk.Frame(root)
        path_frame.pack(pady=5)
        self.file_entry = tk.Entry(path_frame, width=60)
        self.file_entry.pack(side=tk.LEFT, padx=5)
        tk.Button(path_frame, text="Browse", command=self.browse_files).pack(side=tk.LEFT)

        # Options: bitrate, sample rate
        options_frame = tk.Frame(root)
        options_frame.pack(pady=5)

        tk.Label(options_frame, text="Bitrate (e.g., 192k):").grid(row=0, column=0, padx=5)
        tk.Entry(options_frame, textvariable=self.bitrate, width=8).grid(row=0, column=1)

        tk.Label(options_frame, text="Sample Rate (e.g., 44100):").grid(row=0, column=2, padx=5)
        tk.Entry(options_frame, textvariable=self.sample_rate, width=10).grid(row=0, column=3)

        # Checkbox to delete original
        tk.Checkbutton(root, text="Delete original videos after conversion", variable=self.delete_original).pack()

        # Convert button
        tk.Button(root, text="Convert Videos to MP3", command=self.start_conversion_thread, bg="green", fg="white", width=30).pack(pady=10)

        # Progress bar
        self.progress = ttk.Progressbar(root, orient="horizontal", length=500, mode="determinate")
        self.progress.pack(pady=5)

        # Log area
        tk.Label(root, text="Conversion Log:").pack()
        self.log_area = scrolledtext.ScrolledText(root, height=12, width=85)
        self.log_area.pack(padx=10, pady=5)

    def browse_files(self):
        file_types = [("Video files", "*.mp4 *.mkv"), ("All files", "*.*")]
        selected_files = filedialog.askopenfilenames(title="Select Video Files", filetypes=file_types)
        if selected_files:
            self.file_paths = list(selected_files)
            # Show selected file names in entry (just first + count if many)
            display_text = ", ".join(os.path.basename(f) for f in self.file_paths[:3])
            if len(self.file_paths) > 3:
                display_text += f" ... (+{len(self.file_paths)-3} more)"
            self.file_entry.delete(0, tk.END)
            self.file_entry.insert(0, display_text)

    def log(self, message):
        self.log_area.insert(tk.END, message + '\n')
        self.log_area.see(tk.END)
        self.root.update()

    def start_conversion_thread(self):
        thread = threading.Thread(target=self.convert_videos)
        thread.start()

    def convert_videos(self):
        if not self.file_paths:
            messagebox.showerror("Error", "No video files selected.")
            return

        self.progress["maximum"] = len(self.file_paths)
        self.progress["value"] = 0
        self.log(f"[*] Starting conversion for {len(self.file_paths)} file(s)...")

        for i, full_path in enumerate(self.file_paths, 1):
            filename = os.path.basename(full_path)
            mp3_path = os.path.splitext(full_path)[0] + ".mp3"

            command = [
                "ffmpeg", "-i", full_path,
                "-vn",
                "-ab", self.bitrate.get(),
                "-ar", self.sample_rate.get(),
                "-y", mp3_path
            ]

            try:
                result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

                if result.returncode == 0:
                    self.log(f"[✓] Converted: {filename}")
                    if self.delete_original.get():
                        os.remove(full_path)
                        self.log(f"    Deleted original: {filename}")
                else:
                    self.log(f"[X] Error converting {filename}:\n    {result.stderr.splitlines()[-1]}")

            except Exception as e:
                self.log(f"[X] Exception while converting {filename}: {e}")

            self.progress["value"] = i
            self.root.update_idletasks()

        self.log("[✓] All conversions completed!")

# Run the app
if __name__ == "__main__":
    root = tk.Tk()
    app = VideoToMP3ConverterApp(root)
    root.mainloop()
