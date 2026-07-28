"""
ardupilot_gui_wizard_arming.py

Setup Wizard: Arming Checks step. Adds presets by system/mission type
(feedback: "some things don't need many arming checks while others
certainly do -- need to make that understandable") -- see
ardupilot_agent/presets.py for the reasoning behind each preset. Manual
checkboxes remain for fine-tuning after picking one.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

from ardupilot_agent.arming_checks import (
    ARMING_CHECK_BITS,
    ARMING_CHECK_TOOLTIPS,
    NEVER_RECOMMEND_DISABLING,
    read_current as arming_read_current,
    apply as arming_apply,
    describe_value as arming_describe_value,
)
from ardupilot_agent.presets import ARMING_PRESETS, PROFILE_TO_ARMING_PRESET, PROFILE_OPTIONS
from ardupilot_gui_tooltip import attach_tooltip


class WizardArmingMixin:
    def _wizard_step_arming(self, parent):
        ttk.Label(parent, text="Arming Checks Review", style="StepTitle.TLabel").pack(anchor="w")
        ttk.Label(parent, wraplength=780, justify="left", text=(
            'Arming checks are safety checks ArduPilot runs before letting the vehicle arm. '
            'How strict they should be depends on what you\'re doing right now -- pick a preset '
            'below, or set individual checks. Hover over any checkbox for what it checks and '
            'what hardware it applies to. "All" means every check runs; on pre-4.7.0 firmware '
            "it also overrides the individual boxes, so uncheck it first if you want only "
            "specific checks. Never recommended to "
            "disable: " + ", ".join(sorted(NEVER_RECOMMEND_DISABLING)) + "."
        )).pack(anchor="w", pady=(4, 8))

        preset_frame = ttk.LabelFrame(parent, text="Presets by use case", padding=6)
        preset_frame.pack(fill="x", pady=(0, 10))

        grid = ttk.Frame(parent)
        grid.pack(anchor="w", pady=4)
        self.wizard_arming_vars = {}
        self._arming_tooltips = []
        names = list(ARMING_CHECK_BITS.values())
        for i, name in enumerate(names):
            var = tk.BooleanVar(value=(name == "All"))
            self.wizard_arming_vars[name] = var
            cb = ttk.Checkbutton(grid, text=name, variable=var)
            cb.grid(row=i // 3, column=i % 3, sticky="w", padx=8, pady=2)
            tooltip_text = ARMING_CHECK_TOOLTIPS.get(name, "")
            if tooltip_text:
                self._arming_tooltips.append(attach_tooltip(cb, tooltip_text))

        def apply_preset(key):
            preset = ARMING_PRESETS[key]
            preset_desc_var.set(f"{preset.label}: {preset.description}")
            for name, var in self.wizard_arming_vars.items():
                var.set(name in preset.enabled)

        # Pre-fill from the Vehicle Profile chosen on the Welcome step, if any.
        profile_label = self.vehicle_profile.get() if hasattr(self, "vehicle_profile") else ""
        profile_key = next((k for k, lbl in PROFILE_OPTIONS if lbl == profile_label), None)
        preset_desc_default = "Pick a preset to see what it enables/disables and why."
        if profile_key:
            arm_key = PROFILE_TO_ARMING_PRESET[profile_key]
            preset = ARMING_PRESETS[arm_key]
            for name, var in self.wizard_arming_vars.items():
                var.set(name in preset.enabled)
            preset_desc_default = f"Pre-filled from your Vehicle Profile -- {preset.label}: {preset.description}"
        preset_desc_var = tk.StringVar(value=preset_desc_default)

        btn_row = ttk.Frame(preset_frame)
        btn_row.pack(anchor="w")
        for key, preset in ARMING_PRESETS.items():
            ttk.Button(btn_row, text=preset.label, command=lambda k=key: apply_preset(k)).pack(
                side="left", padx=(0, 6), pady=2
            )
        ttk.Label(preset_frame, textvariable=preset_desc_var, wraplength=740, justify="left",
                  foreground="#555").pack(anchor="w", pady=(6, 0))

        def read_current():
            if not self._require_conn():
                return

            def apply_to_ui(enabled_set):
                for name, var in self.wizard_arming_vars.items():
                    var.set(name in enabled_set)

            self.worker.submit(arming_read_current, self.worker.conn, on_done=apply_to_ui, on_error=self._on_job_error)

        def apply():
            if not self._require_conn():
                return
            enabled = {name for name, var in self.wizard_arming_vars.items() if var.get()}
            missing_critical = NEVER_RECOMMEND_DISABLING - enabled if "All" not in enabled else set()
            if missing_critical:
                if not messagebox.askyesno(
                    "This disables checks that are never recommended to disable",
                    "You're about to arm-check WITHOUT: " + ", ".join(sorted(missing_critical)) + ".\n\n"
                    "This is fine for deliberate bench testing (e.g. no RC bound yet, scripted "
                    "motor tests) but this vehicle should NOT fly with these disabled. "
                    "Continue anyway?",
                    icon="warning",
                ):
                    return
            elif not messagebox.askyesno("Confirm arming checks",
                                          f"Write arming checks with {len(enabled)} check(s) enabled?"):
                return
            # arming_apply returns (param_name, value) -- the name matters because
            # Copter 4.7.0+ stores this as ARMING_SKIPCHK, whose bits are inverted
            # relative to ARMING_CHECK. Report whichever was actually written.
            self.worker.submit(arming_apply, self.worker.conn, enabled,
                                on_done=lambda res: self._record_change(arming_describe_value(*res)),
                                on_error=self._on_job_error)

        btn_row2 = ttk.Frame(parent)
        btn_row2.pack(anchor="w", pady=8)
        ttk.Button(btn_row2, text="Read Current", command=read_current).pack(side="left")
        ttk.Button(btn_row2, text="Apply", command=apply, style="Accent.TButton").pack(side="left", padx=8)
