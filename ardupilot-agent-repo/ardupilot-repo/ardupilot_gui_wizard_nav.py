"""
ardupilot_gui_wizard_nav.py

Setup Wizard: Next/Back navigation scaffolding + the Welcome step (now
includes a pre-flight prerequisites checklist, since starting the wizard
before the vehicle is even flashed/bound was a real point of confusion).
Each wizard *step* lives in its own small ardupilot_gui_wizard_*.py mixin
file -- split up purely to keep every source file small enough to survive
a reliable write in this environment. See ardupilot_gui.py for how all the
step mixins combine into the final class.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

from ardupilot_agent.presets import (
    PROFILE_OPTIONS,
    PROFILE_TO_ARMING_PRESET,
    FAILSAFE_PRESETS,
    ARMING_PRESETS,
    build_intent as build_failsafe_intent,
)
from ardupilot_agent.failsafe import apply_failsafe_intent, compute_fs_options, describe_fs_options
from ardupilot_agent.arming_checks import apply as arming_apply, describe_value as arming_describe_value
from ardupilot_gui_theme import DARK, LIGHT


class WizardNavMixin:
    """Navigation scaffolding + step list + Welcome step. self.wizard_steps
    references builder methods that live on the *other* wizard step mixins
    -- resolves once everything is combined into ArduPilotGUI.
    """

    def _init_wizard_state(self):
        self.wizard_steps = [
            ("Welcome", self._wizard_step_welcome),
            ("Frame Class Review", self._wizard_step_frame),
            ("RC Calibration", self._wizard_step_rc),
            ("Flight Modes", self._wizard_step_modes),
            ("Motor Order & Direction", self._wizard_step_motors),
            ("ESC Calibration", self._wizard_step_esc),
            ("Failsafe", self._wizard_step_failsafe),
            ("Arming Checks", self._wizard_step_arming),
            ("Summary", self._wizard_step_summary),
        ]
        self.wizard_index = 0
        self._wizard_leave_hook = None
        self.vehicle_profile = tk.StringVar(value="")
        self._init_wizard_rc_state()
        self._init_wizard_modes_state()

    def _start_wizard_polling(self):
        self._start_wizard_rc_polling()
        self._start_wizard_modes_polling()

    def _build_wizard_tab_if_present(self, nb):
        self._build_wizard_tab(nb)

    def _build_wizard_tab(self, nb):
        tab = ttk.Frame(nb, padding=8)
        nb.add(tab, text="Setup Wizard")

        nav = ttk.Frame(tab)
        nav.pack(fill="x", pady=(0, 8))
        self.wizard_back_btn = ttk.Button(nav, text="< Back", command=self._wizard_back)
        self.wizard_back_btn.pack(side="left")
        self.wizard_step_label_var = tk.StringVar()
        ttk.Label(nav, textvariable=self.wizard_step_label_var, font=("", 11, "bold")).pack(
            side="left", expand=True, padx=12
        )
        self.wizard_next_btn = ttk.Button(nav, text="Next >", command=self._wizard_next, style="Accent.TButton")
        self.wizard_next_btn.pack(side="right")

        jump_var = tk.StringVar()
        jump = ttk.Combobox(nav, textvariable=jump_var, state="readonly", width=22,
                             values=[title for title, _ in self.wizard_steps])
        jump.pack(side="right", padx=8)
        jump.bind("<<ComboboxSelected>>", lambda e: self._wizard_show_step(
            [t for t, _ in self.wizard_steps].index(jump_var.get())
        ))

        # Scrollable wrapper -- some steps (Failsafe with the EKF section,
        # Motor Direction, etc.) are taller than a normal window, and
        # without this the extra content was only reachable by maximizing
        # the window. A canvas + scrollbar makes every step reachable
        # regardless of window size, and the mouse wheel scrolls it too.
        scroll_area = ttk.Frame(tab)
        scroll_area.pack(fill="both", expand=True)
        _palette = DARK if getattr(self, "theme_mode", "dark") == "dark" else LIGHT
        canvas = tk.Canvas(scroll_area, highlightthickness=0, borderwidth=0, background=_palette["bg"])
        vscroll = ttk.Scrollbar(scroll_area, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vscroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        vscroll.pack(side="right", fill="y")
        self._register_dark_widget(canvas, "canvas")

        self.wizard_content = ttk.Frame(canvas)
        content_window = canvas.create_window((0, 0), window=self.wizard_content, anchor="nw")
        self._wizard_canvas = canvas

        def _on_content_configure(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(event):
            canvas.itemconfig(content_window, width=event.width)

        self.wizard_content.bind("<Configure>", _on_content_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        self._wizard_show_step(0)

    def _wizard_show_step(self, index: int):
        index = max(0, min(index, len(self.wizard_steps) - 1))
        if self._wizard_leave_hook is not None:
            try:
                self._wizard_leave_hook()
            except Exception:
                pass
            self._wizard_leave_hook = None
        self.wizard_index = index
        title, builder = self.wizard_steps[index]
        self.wizard_step_label_var.set(f"Step {index + 1} of {len(self.wizard_steps)}: {title}")
        self.wizard_back_btn.configure(state="disabled" if index == 0 else "normal")
        self.wizard_next_btn.configure(text="Restart Wizard" if index == len(self.wizard_steps) - 1 else "Next >")
        for w in self.wizard_content.winfo_children():
            w.destroy()
        builder(self.wizard_content)
        self._wizard_recalc_scrollregion()

    def _wizard_recalc_scrollregion(self):
        """Force an immediate geometry recalculation and reset scroll to
        the top after swapping step content. Without this, a short step
        (e.g. ESC Calibration once its "not needed" verdict comes back)
        could inherit the previous, taller step's scrollregion -- Tk's
        <Configure> event doesn't always fire in time for a same-size or
        shrinking content swap, so relying on it alone left a bogus
        scrollbar that made short pages look like they needed scrolling
        when there was nothing more to see.
        """
        if not hasattr(self, "_wizard_canvas"):
            return
        self._wizard_canvas.update_idletasks()
        self._wizard_canvas.configure(scrollregion=self._wizard_canvas.bbox("all"))
        self._wizard_canvas.yview_moveto(0)

    def _wizard_next(self):
        if self.wizard_index == len(self.wizard_steps) - 1:
            self._wizard_show_step(0)
        else:
            self._wizard_show_step(self.wizard_index + 1)

    def _wizard_back(self):
        self._wizard_show_step(self.wizard_index - 1)

    def _wizard_refresh_current_step(self):
        """Rebuild whichever step is currently showing. Used to fix a real
        bug: the Welcome step's connected/not-connected message was only
        ever drawn once (when the step first builds), so it stayed stale
        and red after a successful connect until the user navigated away
        and back. Called from _on_connected() in ardupilot_gui_core.py.
        """
        if hasattr(self, "wizard_content"):
            self._wizard_show_step(self.wizard_index)

    def _wizard_apply_recommended_now(self, profile_key: str):
        if not self._require_conn():
            return
        if not profile_key:
            messagebox.showwarning("Pick a profile first", "Choose what this vehicle is being used for above.")
            return
        fs_preset = FAILSAFE_PRESETS[profile_key]
        arm_key = PROFILE_TO_ARMING_PRESET[profile_key]
        arm_preset = ARMING_PRESETS[arm_key]
        if not messagebox.askyesno(
            "Apply recommended settings now?",
            f"This writes BOTH of the following to the FC in one go:\n\n"
            f"Failsafe -- {fs_preset.label}:\n{fs_preset.description}\n\n"
            f"Arming Checks -- {arm_preset.label}:\n{arm_preset.description}\n\n"
            "You can still fine-tune either one later on their own wizard steps. Continue?",
        ):
            return

        intent = build_failsafe_intent(profile_key)

        def do_both():
            apply_failsafe_intent(self.worker.conn, intent)
            arming_apply(self.worker.conn, arm_preset.enabled)
            return arm_preset.enabled

        def on_done(enabled):
            self._record_change(
                f"Failsafe applied (Quick Setup, {fs_preset.label}): "
                f"{describe_fs_options(compute_fs_options(intent))}"
            )
            self._record_change(
                f"Arming checks applied (Quick Setup, {arm_preset.label}, {len(enabled)} check(s) enabled)"
            )

        self.worker.submit(do_both, on_done=on_done, on_error=self._on_job_error)

    def _wizard_step_welcome(self, parent):
        ttk.Label(parent, text="ArduPilot First-Time Setup Wizard", style="Title.TLabel").pack(anchor="w")

        compat_frame = ttk.LabelFrame(parent, text="Run this first", padding=8)
        compat_frame.pack(fill="x", pady=(10, 4))
        ttk.Label(compat_frame, text=(
            "Before working through the steps below, run a Compatibility Check. It reads your "
            "connected FC's actual firmware version and confirms every parameter this wizard "
            "relies on still exists on it -- catching a mismatch here up front is a lot less "
            "confusing than a specific step failing partway through for reasons that aren't obvious."
        ), wraplength=740, justify="left").pack(anchor="w", pady=(0, 6))
        ttk.Button(compat_frame, text="Open Compatibility Check", style="Accent.TButton",
                   command=lambda: self._open_compat_tab()).pack(anchor="w")

        profile_frame = ttk.LabelFrame(parent, text="Quick Setup -- what is this vehicle for right now?", padding=8)
        profile_frame.pack(fill="x", pady=(12, 4))
        ttk.Label(profile_frame, text=(
            "Pick one and this pre-fills the Failsafe and Arming Checks steps with a matching "
            "recommended preset -- or apply both right now in one click without visiting either "
            "page. You can always fine-tune both individually later."
        ), wraplength=740, justify="left").pack(anchor="w", pady=(0, 6))
        row = ttk.Frame(profile_frame)
        row.pack(anchor="w")
        profile_combo = ttk.Combobox(row, textvariable=self.vehicle_profile, width=26, state="readonly",
                                      values=[label for _key, label in PROFILE_OPTIONS])
        profile_combo.pack(side="left")

        def label_to_key(label):
            for key, lbl in PROFILE_OPTIONS:
                if lbl == label:
                    return key
            return ""

        ttk.Button(row, text="Apply Recommended Failsafe + Arming Now", style="Accent.TButton",
                   command=lambda: self._wizard_apply_recommended_now(label_to_key(self.vehicle_profile.get()))
                   ).pack(side="left", padx=8)

        profile_desc_var = tk.StringVar(value="")
        ttk.Label(profile_frame, textvariable=profile_desc_var, wraplength=740, justify="left",
                  style="Muted.TLabel").pack(anchor="w", pady=(6, 0))

        def on_profile_selected(_event=None):
            key = label_to_key(self.vehicle_profile.get())
            if not key:
                return
            fs = FAILSAFE_PRESETS[key]
            arm = ARMING_PRESETS[PROFILE_TO_ARMING_PRESET[key]]
            profile_desc_var.set(f"Failsafe -> {fs.label}: {fs.description}\n\nArming -> {arm.label}: {arm.description}")

        profile_combo.bind("<<ComboboxSelected>>", on_profile_selected)

        ttk.Label(parent, text="Before you start", style="StepTitle.TLabel").pack(anchor="w", pady=(16, 2))
        checklist = [
            "ArduPilot firmware is already flashed to the flight controller (this tool "
            "configures parameters -- it does not flash firmware).",
            "The RC receiver is bound to your transmitter and wired to the flight "
            "controller (a receiver that isn't bound yet will show no RC signal in Step 3).",
            "Propellers are OFF, or the vehicle is otherwise physically restrained, for "
            "every step through Motor Order.",
            "The flight battery is disconnected -- everything in this wizard runs over "
            "USB power only, except ESC Calibration, which tells you exactly when to "
            "connect the battery.",
            "Accelerometer and compass calibration are done, or you're OK doing them "
            "right after this wizard (see the note below).",
        ]
        for item in checklist:
            row = ttk.Frame(parent)
            row.pack(anchor="w", fill="x", pady=1)
            ttk.Label(row, text="•", width=2).pack(side="left")
            ttk.Label(row, text=item, wraplength=740, justify="left").pack(side="left")

        ttk.Label(parent, wraplength=780, justify="left", text=(
            "\nThis wizard then walks through: frame class review, RC calibration, flight "
            "mode assignment, motor order & direction, ESC calibration, failsafe setup, and "
            "arming checks -- in the order ArduPilot's own docs recommend.\n\n"
            "Every step that writes to the FC still goes through the same disarm-gated, "
            "verify-after-write pattern as the rest of this toolkit. Nothing here overrides "
            "that.\n\n"
            "Not covered by this wizard: accelerometer and compass calibration. Those require "
            "physically rotating the vehicle through specific orientations while ArduPilot's "
            "own interactive calibration routine watches the IMU/compass data in real time -- "
            "still best done in Mission Planner. Do those first if you haven't, then use this "
            "wizard for the rest."
        )).pack(anchor="w", pady=(8, 4))

        if self.worker.conn is None:
            ttk.Label(parent, text="Not connected yet -- connect above first, then click Next.",
                      foreground="#c0392b").pack(anchor="w", pady=(8, 0))
        else:
            ttk.Label(parent, text="Connected -- click Next to begin.",
                      foreground="#2e8b57").pack(anchor="w", pady=(8, 0))
