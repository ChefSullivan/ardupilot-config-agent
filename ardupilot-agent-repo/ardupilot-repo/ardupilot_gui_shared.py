"""
ardupilot_gui_shared.py

Log panel + shared plumbing (connection guard, error handling, the result
queue poller) used by every tab and by the Setup Wizard. Split into its
own file purely to keep each GUI source file a manageable size.
"""
from __future__ import annotations

import queue
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional


class SharedPlumbingMixin:
    def _record_change(self, description: str):
        """Append a timestamped entry to self.change_log (shown on the
        Setup Wizard's Summary step) and echo it to the live log panel.
        Every apply-handler across every wizard step and the Parameters
        tab should call this instead of self._log() directly, so the
        Summary step can show a complete, verifiable list of what actually
        changed on the FC this session.
        """
        import time as _time
        if not hasattr(self, "change_log"):
            self.change_log = []
        entry = f"[{_time.strftime('%H:%M:%S')}] {description}"
        self.change_log.append(entry)
        self._log(entry + "\n")

    def _register_dark_widget(self, widget, kind: str = "listbox"):
        """Track a plain (non-ttk) Text/Listbox widget so the light/dark
        theme toggle can reconfigure its colors directly -- ttk.Style
        changes don't reach non-ttk widgets, and option_add only affects
        widgets created after it's set.
        """
        if not hasattr(self, "_dark_widgets"):
            self._dark_widgets = []
        self._dark_widgets.append((widget, kind))

    def _build_log(self):
        frame = ttk.LabelFrame(self.root, text="Log", padding=4)
        frame.pack(fill="both", expand=False, padx=8, pady=8)
        self.log_text = tk.Text(frame, height=8, state="disabled", wrap="word")
        self.log_text.pack(fill="both", expand=True)
        self.log_text.tag_configure("error", foreground="#c0392b")
        self._register_dark_widget(self.log_text, "text")

    def _log(self, text: str, tag: Optional[str] = None):
        if not text:
            return
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, text, tag or ())
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def _require_conn(self) -> bool:
        if self.worker.conn is None:
            messagebox.showwarning("Not connected", "Connect to the flight controller first.")
            return False
        return True

    def _on_job_error(self, e: Exception):
        self._log(f"ERROR: {e}\n", tag="error")
        messagebox.showerror("Operation failed", str(e))

    def _poll_results(self):
        try:
            while True:
                item = self.results_get_nowait()
                if item is None:
                    break
                kind = item[0]
                if kind == "log":
                    self._log(item[1])
                elif kind == "done":
                    _, callback, result = item
                    callback(result)
                elif kind == "safety_error":
                    _, callback, exc = item
                    self._log(f"SAFETY ABORT: {exc}\n", tag="error")
                    messagebox.showerror("Safety abort", str(exc))
                    callback(exc)
                elif kind == "error":
                    # Only the job's own on_error callback runs here -- do
                    # NOT also fire self._on_job_error unconditionally.
                    # Background polling jobs (e.g. the armed-state check
                    # that runs every few seconds) intentionally use a
                    # quiet handler; forcing self._on_job_error on every
                    # failure meant a single dropped connection (e.g. the
                    # COM port re-enumerating after a reboot) produced a
                    # fresh error dialog + log line every poll cycle
                    # forever instead of failing once, quietly.
                    _, callback, exc = item
                    callback(exc)
        finally:
            self.root.after(100, self._poll_results)

    def results_get_nowait(self):
        try:
            return self.worker.results.get_nowait()
        except queue.Empty:
            return None
