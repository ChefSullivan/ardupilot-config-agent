"""
ardupilot_gui_wizard_failsafe.py

Setup Wizard: Failsafe step. Reworded every checkbox as a direct yes/no
question (feedback: the old wording was confusing), and added "Recommended
Failsafe" presets by what the vehicle is actually being used for right
now (testing / manual flying / semi-autonomous / full autonomous mission)
-- see ardupilot_agent/presets.py for the reasoning behind each preset.
Manual checkboxes remain available for fine-tuning after picking a preset.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

from ardupilot_agent.failsafe import (
    FailsafeIntent,
    compute_fs_options,
    describe_fs_options,
    apply_failsafe_intent,
    EKF_ACTION_VALUES,
    EKF_THRESH_PRESETS,
    apply_ekf_failsafe,
)
from ardupilot_agent.params import get_param
from ardupilot_agent.presets import FAILSAFE_PRESETS, PROFILE_OPTIONS

QUESTIONS = {
    "continue_auto_mission_on_radio_loss": "If you lose RC (radio) signal during an automatic "
        "mission, should the vehicle keep flying the mission instead of returning home?",
    "continue_auto_mission_on_gcs_loss": "If you lose the ground station / telemetry link during "
        "an automatic mission, should the vehicle keep flying the mission?",
    "continue_guided_on_radio_loss": "If you lose RC signal while in Guided mode, should the "
        "vehicle keep following ground-station commands instead of returning home?",
    "continue_landing_on_any_failsafe": "If the vehicle is already landing when a failsafe "
        "triggers, should it finish landing instead of aborting to RTL?",
    "continue_pilot_control_on_gcs_loss": "If you lose only the ground-station link while flying "
        "manually, should you keep flying by hand normally?",
    "release_gripper_on_failsafe": "Should the gripper release automatically if any failsafe "
        "triggers?",
}


class WizardFailsafeMixin:
    def _wizard_step_failsafe(self, parent):
        ttk.Label(parent, text="Failsafe Setup", style="StepTitle.TLabel").pack(anchor="w")
        ttk.Label(parent, text=(
            "A failsafe is what the vehicle does automatically when it loses a link (radio or "
            "ground station) mid-flight. Pick a starting point below based on how you're using "
            "the vehicle, then fine-tune with the questions underneath if needed."
        ), wraplength=780, justify="left").pack(anchor="w", pady=(4, 10))

        preset_frame = ttk.LabelFrame(parent, text="Recommended Failsafe presets", padding=6)
        preset_frame.pack(fill="x", pady=(0, 10))

        self.wizard_fs_vars = {key: tk.BooleanVar(value=False) for key in QUESTIONS}
        self.wizard_fs_vars["continue_landing_on_any_failsafe"].set(True)

        # Pre-fill from the Vehicle Profile chosen on the Welcome step, if any.
        profile_label = self.vehicle_profile.get() if hasattr(self, "vehicle_profile") else ""
        profile_key = next((k for k, lbl in PROFILE_OPTIONS if lbl == profile_label), None)
        preset_desc_default = "Pick a preset to see what it does, then Apply Preset to fill in the questions below."
        if profile_key:
            preset = FAILSAFE_PRESETS[profile_key]
            for field_name, value in preset.intent_kwargs.items():
                if field_name in self.wizard_fs_vars:
                    self.wizard_fs_vars[field_name].set(bool(value))
            preset_desc_default = f"Pre-filled from your Vehicle Profile -- {preset.label}: {preset.description}"

        preset_desc_var = tk.StringVar(value=preset_desc_default)
        preview_var = tk.StringVar()

        def update_preview():
            intent = FailsafeIntent(**{k: v.get() for k, v in self.wizard_fs_vars.items()})
            preview_var.set(describe_fs_options(compute_fs_options(intent)))

        def apply_preset(key):
            preset = FAILSAFE_PRESETS[key]
            preset_desc_var.set(f"{preset.label}: {preset.description}")
            for field_name, value in preset.intent_kwargs.items():
                if field_name in self.wizard_fs_vars:
                    self.wizard_fs_vars[field_name].set(bool(value))
            update_preview()

        btn_row = ttk.Frame(preset_frame)
        btn_row.pack(anchor="w")
        for key, preset in FAILSAFE_PRESETS.items():
            ttk.Button(btn_row, text=preset.label, command=lambda k=key: apply_preset(k)).pack(
                side="left", padx=(0, 6), pady=2
            )
        ttk.Label(preset_frame, textvariable=preset_desc_var, wraplength=740, justify="left",
                  foreground="#555").pack(anchor="w", pady=(6, 0))

        q_frame = ttk.LabelFrame(parent, text="Fine-tune (each answered independently)", padding=6)
        q_frame.pack(fill="both", expand=True)
        for key, question in QUESTIONS.items():
            ttk.Checkbutton(q_frame, text=question, variable=self.wizard_fs_vars[key],
                             command=update_preview).pack(anchor="w", pady=2)

        ttk.Label(parent, text="Resulting FS_OPTIONS (technical preview):", foreground="#888").pack(
            anchor="w", pady=(10, 0)
        )
        ttk.Label(parent, textvariable=preview_var, wraplength=780, justify="left").pack(anchor="w", pady=(0, 8))
        update_preview()

        def apply():
            if not self._require_conn():
                return
            intent = FailsafeIntent(**{k: v.get() for k, v in self.wizard_fs_vars.items()})
            if not messagebox.askyesno("Confirm failsafe change",
                                        "Write FS_OPTIONS / FS_GCS_ENABLE / FS_THR_ENABLE to the FC?"):
                return
            self.worker.submit(
                apply_failsafe_intent, self.worker.conn, intent,
                on_done=lambda r: self._record_change(f"Failsafe applied: {describe_fs_options(compute_fs_options(intent))}"),
                on_error=self._on_job_error,
            )

        ttk.Button(parent, text="Apply to FC", command=apply, style="Accent.TButton").pack(anchor="w")

        # -- GPS / position (EKF) failsafe --
        ekf_frame = ttk.LabelFrame(parent, text="GPS / Position (EKF) Failsafe", padding=6)
        ekf_frame.pack(fill="x", pady=(14, 0))
        ttk.Label(ekf_frame, text=(
            "What happens if the vehicle's position estimate becomes unreliable mid-flight "
            "(bad GPS, compass interference, etc). This replaced the old dedicated \"GPS "
            "failsafe\" -- it watches the position/velocity/compass confidence directly rather "
            "than just GPS lock, which catches more real problems."
        ), wraplength=740, justify="left").pack(anchor="w", pady=(0, 6))

        ekf_row = ttk.Frame(ekf_frame)
        ekf_row.pack(anchor="w")
        ttk.Label(ekf_row, text="If it triggers:").grid(row=0, column=0, sticky="w")
        action_var = tk.StringVar()
        action_labels = [f"{v} - {name}" for v, name in sorted(EKF_ACTION_VALUES.items())]
        ttk.Combobox(ekf_row, textvariable=action_var, width=46, state="readonly",
                     values=action_labels).grid(row=0, column=1, padx=6, pady=2)
        ttk.Label(ekf_row, text="Sensitivity:").grid(row=1, column=0, sticky="w")
        thresh_var = tk.StringVar()
        thresh_labels = [f"{v} - {name}" for v, name in sorted(EKF_THRESH_PRESETS.items())]
        ttk.Combobox(ekf_row, textvariable=thresh_var, width=46, state="readonly",
                     values=thresh_labels).grid(row=1, column=1, padx=6, pady=2)

        def read_ekf():
            if not self._require_conn():
                return

            def do_read():
                return int(get_param(self.worker.conn, "FS_EKF_ACTION")), float(get_param(self.worker.conn, "FS_EKF_THRESH"))

            def on_read(result):
                action, thresh = result
                if action in EKF_ACTION_VALUES:
                    action_var.set(f"{action} - {EKF_ACTION_VALUES[action]}")
                closest = min(EKF_THRESH_PRESETS.keys(), key=lambda k: abs(k - thresh))
                thresh_var.set(f"{closest} - {EKF_THRESH_PRESETS[closest]}")

            self.worker.submit(do_read, on_done=on_read, on_error=self._on_job_error)

        def apply_ekf():
            if not self._require_conn():
                return
            if not action_var.get() or not thresh_var.get():
                messagebox.showwarning("Pick both values", "Choose an action and a sensitivity first.")
                return
            action = int(action_var.get().split(" - ")[0])
            thresh = float(thresh_var.get().split(" - ")[0])
            if not messagebox.askyesno("Confirm GPS/EKF failsafe",
                                        f"Write FS_EKF_ACTION={action}, FS_EKF_THRESH={thresh}?"):
                return
            self.worker.submit(
                apply_ekf_failsafe, self.worker.conn, action, thresh,
                on_done=lambda r: self._record_change(
                    f"GPS/EKF failsafe applied: FS_EKF_ACTION={action} ({EKF_ACTION_VALUES[action]}), "
                    f"FS_EKF_THRESH={thresh}"),
                on_error=self._on_job_error,
            )

        ekf_btn_row = ttk.Frame(ekf_frame)
        ekf_btn_row.pack(anchor="w", pady=(8, 0))
        ttk.Button(ekf_btn_row, text="Read Current", command=read_ekf).pack(side="left")
        ttk.Button(ekf_btn_row, text="Apply GPS/EKF Failsafe", style="Accent.TButton", command=apply_ekf).pack(
            side="left", padx=8
        )
