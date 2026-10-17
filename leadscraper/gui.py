"""Desktop window for non-technical users. Logic lives in jobs.py; this is layout and threading only."""

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import jobs
from .discover import US_STATES


def open_path(path):
    path = str(path)
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.run(["open", path], check=False)
    else:
        subprocess.run(["xdg-open", path], check=False)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Lead Scraper")
        self.minsize(640, 560)
        self.report_callback_exception = self._on_ui_error
        self.events = queue.Queue()
        self.stop_flag = threading.Event()
        self.worker = None
        self.results_path = None
        self._build()
        self.after(100, self._drain_events)

    def _build(self):
        pad = {"padx": 12, "pady": 4}
        form = ttk.LabelFrame(self, text="1. What are you looking for?")
        form.pack(fill="x", padx=12, pady=(12, 4))
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="Type of business").grid(row=0, column=0, sticky="w", **pad)
        self.category = ttk.Combobox(form, state="readonly", values=list(jobs.CATEGORY_LABELS))
        self.category.current(0)
        self.category.grid(row=0, column=1, sticky="ew", **pad)

        ttk.Label(form, text="State").grid(row=1, column=0, sticky="w", **pad)
        self.area = ttk.Combobox(form, state="readonly", values=US_STATES)
        self.area.set("Texas")
        self.area.grid(row=1, column=1, sticky="ew", **pad)

        ttk.Label(form, text="Max businesses to check").grid(row=2, column=0, sticky="w", **pad)
        self.max_businesses = ttk.Spinbox(form, from_=10, to=1000, increment=10, width=8)
        self.max_businesses.set(100)
        self.max_businesses.grid(row=2, column=1, sticky="w", **pad)

        ttk.Label(form, text="Save results in").grid(row=3, column=0, sticky="w", **pad)
        folder_row = ttk.Frame(form)
        folder_row.grid(row=3, column=1, sticky="ew", **pad)
        folder_row.columnconfigure(0, weight=1)
        self.folder = ttk.Entry(folder_row)
        self.folder.insert(0, str(jobs.default_output_dir()))
        self.folder.grid(row=0, column=0, sticky="ew")
        ttk.Button(folder_row, text="Browse...", command=self._browse).grid(row=0, column=1, padx=(6, 0))

        opts = ttk.LabelFrame(self, text="2. Options")
        opts.pack(fill="x", padx=12, pady=4)
        opts.columnconfigure(1, weight=1)
        ttk.Label(opts, text="Keep leads that have").grid(row=0, column=0, sticky="w", **pad)
        self.confidence = ttk.Combobox(opts, state="readonly", values=list(jobs.CONFIDENCE_LABELS))
        self.confidence.current(1)
        self.confidence.grid(row=0, column=1, sticky="ew", **pad)
        self.personal = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="Include Gmail / Yahoo / Outlook addresses",
                        variable=self.personal).grid(row=1, column=0, columnspan=2, sticky="w", **pad)
        self.chains = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="Include big chains and franchises",
                        variable=self.chains).grid(row=2, column=0, columnspan=2, sticky="w", **pad)

        actions = ttk.Frame(self)
        actions.pack(fill="x", padx=12, pady=8)
        self.start_btn = ttk.Button(actions, text="Find leads", command=self._start)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(actions, text="Stop", command=self.stop_flag.set, state="disabled")
        self.stop_btn.pack(side="left", padx=6)
        self.open_file_btn = ttk.Button(actions, text="Open results", state="disabled",
                                        command=lambda: open_path(self.results_path))
        self.open_file_btn.pack(side="right")
        self.open_folder_btn = ttk.Button(actions, text="Open folder",
                                          command=lambda: open_path(self._folder_path()))
        self.open_folder_btn.pack(side="right", padx=6)

        self.bar = ttk.Progressbar(self, mode="determinate")
        self.bar.pack(fill="x", padx=12)
        self.status = ttk.Label(self, text="Ready.")
        self.status.pack(anchor="w", padx=12, pady=(4, 0))

        log_frame = ttk.Frame(self)
        log_frame.pack(fill="both", expand=True, padx=12, pady=8)
        self.log_box = tk.Text(log_frame, height=10, state="disabled", wrap="word")
        scroll = ttk.Scrollbar(log_frame, command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log_box.pack(side="left", fill="both", expand=True)

    def _browse(self):
        chosen = filedialog.askdirectory(initialdir=self.folder.get() or str(Path.home()))
        if chosen:
            self.folder.delete(0, "end")
            self.folder.insert(0, chosen)

    def _folder_path(self):
        path = Path(self.folder.get())
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _settings(self):
        return jobs.Settings(
            category=jobs.CATEGORY_LABELS[self.category.get()],
            area=self.area.get(),
            max_businesses=self._max_businesses(),
            output_dir=Path(self.folder.get()) if self.folder.get().strip() else None,
            exclude_personal=not self.personal.get(),
            keep_chains=self.chains.get(),
            min_confidence=jobs.CONFIDENCE_LABELS[self.confidence.get()],
        )

    def _max_businesses(self):
        try:
            return int(self.max_businesses.get())
        except ValueError:
            return 0  # fails validation with a clear message

    def _start(self):
        settings = self._settings()
        problem = jobs.validate(settings)
        if problem:
            messagebox.showwarning("Check your entries", problem)
            return
        self.stop_flag.clear()
        self.results_path = None
        self.open_file_btn.config(state="disabled")
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.bar.config(value=0)
        self.status.config(text="Working...")
        self._log_clear()
        self.worker = threading.Thread(target=self._work, args=(settings,), daemon=True)
        self.worker.start()

    def _work(self, settings):
        """Runs off the UI thread; talks to the UI only through the event queue."""
        try:
            path, count = jobs.run_pipeline(
                settings,
                log=lambda m: self.events.put(("log", m)),
                progress=lambda done, total: self.events.put(("progress", (done, total))),
                should_stop=self.stop_flag.is_set,
            )
            self.events.put(("done", (path, count)))
        except RuntimeError:
            self.events.put(("error", "Couldn't reach the business database. Check your internet "
                                      "connection and try again in a minute."))
        except Exception as e:
            self.events.put(("error", f"Something went wrong: {e}"))

    def _drain_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "progress":
                    done, total = payload
                    self.bar.config(maximum=max(total, 1), value=done)
                    self.status.config(text=f"Checked {done} of {total} businesses")
                elif kind == "done":
                    self._finish(*payload)
                elif kind == "error":
                    self._reset_buttons()
                    self.status.config(text="Stopped with an error.")
                    messagebox.showerror("Lead Scraper", payload)
        except queue.Empty:
            pass
        self.after(100, self._drain_events)

    def _finish(self, path, count):
        self._reset_buttons()
        if path and count:
            self.results_path = path
            self.open_file_btn.config(state="normal")
            self.status.config(text=f"Done: {count} leads saved.")
            messagebox.showinfo("Lead Scraper", f"Found {count} leads.\n\nSaved to:\n{path}")
        else:
            self.status.config(text="Done: no leads found.")

    def _reset_buttons(self):
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")

    def _log(self, message):
        self.log_box.config(state="normal")
        self.log_box.insert("end", message + "\n")
        self.log_box.see("end")
        self.log_box.config(state="disabled")

    def _log_clear(self):
        self.log_box.config(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.config(state="disabled")

    def _on_ui_error(self, exc, val, tb):
        # Windowed builds have no console, so surface unexpected errors instead of hiding them.
        messagebox.showerror("Lead Scraper", f"Unexpected error: {val}")


def main():
    App().mainloop()
