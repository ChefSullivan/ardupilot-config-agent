"""
ardupilot_gui_wizard_summary.py

Setup Wizard: Summary step. Lists every change actually applied to the FC
during this session (self.change_log, appended to by _record_change() in
ardupilot_gui_shared.py from every apply-handler across every step and the
Parameters tab), so the user can verify what happened and jump back with
the step dropdown/Back button to fix anything before trusting the vehicle.
"""
from __future__ import annotations

from tkinter import ttk


class WizardSummaryMixin:
    def _wizard_step_summary(self, parent):
        ttk.Label(parent, text="Summary", style="Title.TLabel").pack(anchor="w")
        ttk.Label(parent, wraplength=780, justify="left", text=(
            "Nothing on this page is a \"commit\" step -- every change below was already "
            "written to the flight controller live, the moment you clicked each step's Apply "
            "button. This page is just a record of what happened, not a pending queue. "
            "\"Restart Wizard\" below only takes you back to Step 1 -- it doesn't undo or "
            "re-apply anything.\n\n"
            "That's the sequence: frame class, RC calibration, flight modes, motor order & "
            "direction, ESC calibration, failsafe, and arming checks.\n\n"
            "Still worth doing outside this tool: accelerometer calibration, compass "
            "calibration, and a first controlled flight in Stabilize before trusting any "
            "GPS-dependent mode.\n\n"
            "You can revisit any step with Back or the step dropdown at the top, or jump to "
            "the Parameters / Motor Map / Failsafe tabs directly for one-off changes later."
        )).pack(anchor="w", pady=(8, 12))

        ttk.Label(parent, text="Changes applied this session", font=("", 11, "bold")).pack(anchor="w")
        log = getattr(self, "change_log", [])
        if not log:
            ttk.Label(parent, text="No changes have been applied yet in this session.",
                      foreground="#888").pack(anchor="w", pady=(4, 8))
        else:
            frame = ttk.Frame(parent)
            frame.pack(fill="both", expand=True, pady=(4, 8))
            import tkinter as tk
            text = tk.Text(frame, height=14, wrap="word")
            text.insert("1.0", "\n".join(log))
            text.configure(state="disabled")
            text.pack(fill="both", expand=True)
            self._register_dark_widget(text, "text")

        ttk.Button(parent, text="Restart Wizard", command=lambda: self._wizard_show_step(0)).pack(anchor="w")
