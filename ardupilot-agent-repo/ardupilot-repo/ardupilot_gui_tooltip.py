"""
ardupilot_gui_tooltip.py

Minimal hover-tooltip helper for plain tkinter/ttk widgets. Tkinter has no
built-in tooltip widget -- this is the standard small-Toplevel-on-hover
pattern, kept in its own file since several steps/tabs want it.
"""
from __future__ import annotations

import tkinter as tk


class ToolTip:
    def __init__(self, widget, text: str, wraplength: int = 360):
        self.widget = widget
        self.text = text
        self.wraplength = wraplength
        self._tip: tk.Toplevel | None = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _show(self, _event=None):
        if self._tip is not None or not self.text:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self._tip = tk.Toplevel(self.widget)
        self._tip.wm_overrideredirect(True)
        try:
            self._tip.wm_attributes("-topmost", True)
        except tk.TclError:
            pass
        self._tip.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            self._tip, text=self.text, justify="left", wraplength=self.wraplength,
            background="#ffffe0", foreground="#1c1c22", relief="solid", borderwidth=1,
            font=("Segoe UI", 9), padx=6, pady=4,
        )
        label.pack()

    def _hide(self, _event=None):
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None


def attach_tooltip(widget, text: str) -> ToolTip:
    """Create and return a ToolTip -- caller should keep a reference (e.g.
    append to a list on self) so it isn't garbage-collected while the
    widget is still alive.
    """
    return ToolTip(widget, text)
