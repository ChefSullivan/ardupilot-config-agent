"""
ardupilot_gui_theme.py

Light/dark visual theme for the desktop GUI, plus small per-tab accent
colors so the Setup Wizard, Parameters, Motor Map, and Failsafe tabs are
easier to tell apart at a glance. Pure ttk.Style configuration -- no
external theming library, no change to any widget's actual behavior.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

# Accent color is an ArduPilot-inspired warm orange -- matching the ArduPilot
# logo/branding's orange -- rather than the generic blue from the previous
# version. Note: this is a faithful approximation, not a pixel-verified
# brand swatch (no CSS/asset access was available to extract the exact hex
# values from ardupilot.org) -- easy to swap ACCENT below if you have the
# exact brand hex on hand.
_ACCENT = "#E8720C"
_ACCENT_DARK_BG = "#F08A2E"  # slightly lighter for readability against dark backgrounds

DARK = {
    "bg": "#1c1c20", "bg_alt": "#28282d", "fg": "#eceff1", "fg_muted": "#b7b7c2",
    "accent": _ACCENT_DARK_BG, "entry_bg": "#2b2b31", "select_bg": "#3d3226",
    "log_bg": "#141416", "log_fg": "#dcdce0", "error": "#ff6b6b", "ok": "#4fd68c",
}
LIGHT = {
    "bg": "#f5f4f2", "bg_alt": "#ffffff", "fg": "#1c1c22", "fg_muted": "#5a5a66",
    "accent": _ACCENT, "entry_bg": "#ffffff", "select_bg": "#fbe3cc",
    "log_bg": "#ffffff", "log_fg": "#1c1c22", "error": "#c0392b", "ok": "#2e8b57",
}

# Purely visual per-tab accents (used for the colored strip under each tab
# label) so the tabs read as distinct at a glance.
TAB_ACCENTS = {
    "Setup Wizard": "#4f8cff",
    "Parameters": "#c77dff",
    "Motor Map": "#ff9f43",
    "Failsafe": "#ff6b6b",
}


def apply_theme(root: tk.Tk, palette: dict) -> None:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    root.configure(background=palette["bg"])
    style.configure(".", background=palette["bg"], foreground=palette["fg"],
                     fieldbackground=palette["entry_bg"])
    style.configure("TFrame", background=palette["bg"])
    style.configure("TLabelframe", background=palette["bg"], foreground=palette["fg"])
    style.configure("TLabelframe.Label", background=palette["bg"], foreground=palette["fg"])
    style.configure("TLabel", background=palette["bg"], foreground=palette["fg"])
    style.configure("TCheckbutton", background=palette["bg"], foreground=palette["fg"])
    style.configure("TRadiobutton", background=palette["bg"], foreground=palette["fg"])
    style.configure("TButton", background=palette["bg_alt"], foreground=palette["fg"],
                     padding=(10, 6), font=("Segoe UI", 10))
    style.map("TButton", background=[("active", palette["select_bg"])])

    # Primary/accent button style -- used for the one main call-to-action
    # per step (Next, Apply, Connect) so the eye lands on it first instead
    # of every button looking identical.
    style.configure("Accent.TButton", background=palette["accent"], foreground="#ffffff",
                     padding=(12, 7), font=("Segoe UI", 10, "bold"))
    style.map("Accent.TButton", background=[("active", palette["accent"])])
    style.configure("TEntry", fieldbackground=palette["entry_bg"], foreground=palette["fg"])
    style.configure("TCombobox", fieldbackground=palette["entry_bg"], foreground=palette["fg"],
                     background=palette["bg_alt"])
    style.map("TCombobox", fieldbackground=[("readonly", palette["entry_bg"])])
    style.configure("TSpinbox", fieldbackground=palette["entry_bg"], foreground=palette["fg"])
    style.configure("Horizontal.TProgressbar", background=palette["accent"],
                     troughcolor=palette["entry_bg"])
    style.configure("TNotebook", background=palette["bg"], borderwidth=0)
    style.configure("TNotebook.Tab", background=palette["bg_alt"], foreground=palette["fg_muted"],
                     padding=(14, 8), font=("Segoe UI", 10))
    style.map("TNotebook.Tab",
              background=[("selected", palette["accent"])],
              foreground=[("selected", "#ffffff")])

    # Section headers (step titles) and app title get a consistent,
    # larger font instead of every label defaulting to the same size.
    style.configure("Title.TLabel", background=palette["bg"], foreground=palette["fg"],
                     font=("Segoe UI", 15, "bold"))
    style.configure("StepTitle.TLabel", background=palette["bg"], foreground=palette["fg"],
                     font=("Segoe UI", 12, "bold"))
    style.configure("Muted.TLabel", background=palette["bg"], foreground=palette["fg_muted"],
                     font=("Segoe UI", 9))
    style.configure("TLabelframe", background=palette["bg"], relief="groove", borderwidth=1)
    style.configure("TLabelframe.Label", background=palette["bg"], foreground=palette["accent"],
                     font=("Segoe UI", 10, "bold"))

    root.option_add("*Listbox.background", palette["entry_bg"])
    root.option_add("*Listbox.foreground", palette["fg"])
    root.option_add("*Listbox.selectBackground", palette["select_bg"])
    root.option_add("*Text.background", palette["log_bg"])
    root.option_add("*Text.foreground", palette["log_fg"])
    root.option_add("*Text.insertBackground", palette["log_fg"])


def apply_dark(root: tk.Tk) -> None:
    apply_theme(root, DARK)


def apply_light(root: tk.Tk) -> None:
    apply_theme(root, LIGHT)


def retheme_tk_widget(widget, palette: dict, kind: str) -> None:
    """Directly reconfigure a plain (non-ttk) Text/Listbox widget that
    already existed before a theme toggle -- option_add only affects
    widgets created *after* it's set, so long-lived widgets (the log
    panel, search results list, motor tables) need this on every toggle.
    """
    try:
        if kind == "text":
            widget.configure(background=palette["log_bg"], foreground=palette["log_fg"],
                              insertbackground=palette["log_fg"])
        elif kind == "canvas":
            widget.configure(background=palette["bg"])
        else:
            widget.configure(background=palette["entry_bg"], foreground=palette["fg"],
                              selectbackground=palette["select_bg"])
    except tk.TclError:
        pass
