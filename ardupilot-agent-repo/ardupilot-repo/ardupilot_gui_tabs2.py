"""
ardupilot_gui_tabs2.py

Motor Map and Failsafe standalone tabs, split into their own mixin purely
to keep each GUI source file a manageable size. See ardupilot_gui.py for
how the pieces combine.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

from ardupilot_agent.motor_test import (
    diagnose_one_instance,
    compute_servo_function_fixes,
    apply_servo_function_fixes,
    request_servo_output_stream,
    MotorMapEntry,
)
from ardupilot_agent.frame_reference import FRAME_EXPECTED_LAYOUTS
from ardupilot_agent.failsafe import (
    FailsafeIntent,
    compute_fs_options,
    describe_fs_options,
    apply_failsafe_intent,
)

STANDARD_QUAD_CORNERS = ["front-right", "rear-left", "front-left", "rear-right"]


class MotorFailsafeTabsMixin:
    # -- Motor Map tab ------------------------------------------------------

    def _build_motor_tab(self, nb):
        tab = ttk.Frame(nb, padding=8)
        nb.add(tab, text="Motor Map")

        ttk.Label(tab, text=(
            "Tests one motor at a time and watches SERVO_OUTPUT_RAW to find the true\n"
            "instance->channel mapping. Use throttle >=15-20% so a working motor doesn't\n"
            "look dead below MOT_SPIN_MIN. Props off recommended for early runs."
        ), justify="left").pack(anchor="w", pady=(0, 8))

        cfg = ttk.Frame(tab)
        cfg.pack(fill="x", pady=4)
        ttk.Label(cfg, text="Motor count:").grid(row=0, column=0, sticky="w")
        self.motor_count_var = tk.IntVar(value=4)
        ttk.Spinbox(cfg, from_=2, to=8, textvariable=self.motor_count_var, width=5).grid(row=0, column=1, padx=4)

        ttk.Label(cfg, text="Test throttle %:").grid(row=0, column=2, sticky="w", padx=(12, 0))
        self.motor_throttle_var = tk.IntVar(value=20)
        ttk.Spinbox(cfg, from_=15, to=40, textvariable=self.motor_throttle_var, width=5).grid(row=0, column=3, padx=4)

        ttk.Label(cfg, text="Frame type:").grid(row=0, column=4, sticky="w", padx=(12, 0))
        self.frame_var = tk.StringVar(value=list(FRAME_EXPECTED_LAYOUTS.keys())[0] if FRAME_EXPECTED_LAYOUTS else "")
        ttk.Combobox(cfg, textvariable=self.frame_var, width=16,
                     values=list(FRAME_EXPECTED_LAYOUTS.keys())).grid(row=0, column=5, padx=4)

        self.start_motor_btn = ttk.Button(tab, text="Start Diagnosis", command=self._start_motor_map)
        self.start_motor_btn.pack(anchor="w", pady=6)

        self.motor_prompt_var = tk.StringVar(value="")
        ttk.Label(tab, textvariable=self.motor_prompt_var, font=("", 10, "bold")).pack(anchor="w", pady=4)

        self.corner_btns_frame = ttk.Frame(tab)
        self.corner_btns_frame.pack(anchor="w", pady=4)

        self.motor_table = tk.Listbox(tab, height=8)
        self.motor_table.pack(fill="both", expand=True, pady=8)
        self._register_dark_widget(self.motor_table, "listbox")

        self.apply_fixes_btn = ttk.Button(tab, text="Apply SERVOx_FUNCTION Fixes (reboots FC)", style="Accent.TButton",
                                           command=self._apply_motor_fixes, state="disabled")
        self.apply_fixes_btn.pack(anchor="w")
        self._pending_fixes = {}

    def _start_motor_map(self):
        if not self._require_conn():
            return
        self.motor_count = self.motor_count_var.get()
        self.motor_throttle = self.motor_throttle_var.get()
        self.motor_frame_key = self.frame_var.get()
        self.motor_entries = []
        self.motor_index = 1
        self.motor_table.delete(0, tk.END)
        self.apply_fixes_btn.configure(state="disabled")
        self.start_motor_btn.configure(state="disabled")
        self.worker.submit(request_servo_output_stream, self.worker.conn,
                            on_done=lambda r: self._test_next_motor(), on_error=self._on_job_error)

    def _test_next_motor(self):
        if self.motor_index > self.motor_count:
            self._finish_motor_map()
            return
        self.motor_prompt_var.set(f"Testing motor instance {self.motor_index}...")
        self.worker.submit(
            diagnose_one_instance, self.worker.conn, self.motor_index,
            throttle_pct=self.motor_throttle,
            on_done=self._on_motor_sample, on_error=self._on_motor_error,
        )

    def _on_motor_error(self, e: Exception):
        self.start_motor_btn.configure(state="normal")
        self.motor_prompt_var.set("")
        messagebox.showerror("Motor test failed", str(e))

    def _on_motor_sample(self, sample):
        self._current_channel = sample.channel
        self.motor_prompt_var.set(
            f"Motor instance {self.motor_index} spun output channel {sample.channel}. "
            f"Which physical corner spun?"
        )
        for w in self.corner_btns_frame.winfo_children():
            w.destroy()

        if self.motor_count == 4:
            for corner in STANDARD_QUAD_CORNERS:
                ttk.Button(self.corner_btns_frame, text=corner,
                           command=lambda c=corner: self._corner_selected(c)).pack(side="left", padx=4)
        else:
            entry_var = tk.StringVar()
            ttk.Entry(self.corner_btns_frame, textvariable=entry_var, width=20).pack(side="left", padx=4)
            ttk.Button(self.corner_btns_frame, text="Confirm",
                       command=lambda: self._corner_selected(entry_var.get().strip().lower())).pack(side="left")

    def _corner_selected(self, corner: str):
        if not corner:
            return
        self.motor_entries.append(MotorMapEntry(instance=self.motor_index, channel=self._current_channel, corner=corner))
        self.motor_table.insert(
            tk.END, f"instance {self.motor_index} -> channel {self._current_channel} -> {corner}"
        )
        for w in self.corner_btns_frame.winfo_children():
            w.destroy()
        self.motor_index += 1
        self._test_next_motor()

    def _finish_motor_map(self):
        self.start_motor_btn.configure(state="normal")
        self.motor_prompt_var.set("Diagnosis complete.")
        if self.motor_frame_key and self.motor_frame_key in FRAME_EXPECTED_LAYOUTS:
            expected = FRAME_EXPECTED_LAYOUTS[self.motor_frame_key]
            try:
                fixes = compute_servo_function_fixes(self.motor_entries, expected)
            except KeyError as e:
                messagebox.showwarning("Can't compute fixes", str(e))
                return
            self._pending_fixes = fixes
            for ch, func_val in fixes.items():
                self.motor_table.insert(tk.END, f"  -> fix: SERVO{ch}_FUNCTION = {func_val}")
            self.apply_fixes_btn.configure(state="normal")
        else:
            self.motor_table.insert(
                tk.END, "  (frame type not in local reference cache -- wiring table only, no fixes computed)"
            )

    def _apply_motor_fixes(self):
        if not self._require_conn():
            return
        if not messagebox.askyesno(
            "Confirm SERVOx_FUNCTION changes",
            f"This writes {len(self._pending_fixes)} SERVOx_FUNCTION parameter(s) and reboots the FC. Continue?",
        ):
            return
        self.apply_fixes_btn.configure(state="disabled")
        self.worker.submit(
            apply_servo_function_fixes, self.worker.conn, self._pending_fixes,
            on_done=lambda r: self._record_change(
                f"SERVOx_FUNCTION fixes applied and verified after reboot: {self._pending_fixes}"),
            on_error=self._on_job_error,
        )

    # -- Failsafe tab -----------------------------------------------------

    def _build_failsafe_tab(self, nb):
        tab = ttk.Frame(nb, padding=8)
        nb.add(tab, text="Failsafe")

        ttk.Label(tab, text=(
            '"Continue the mission regardless of link" and "return home on link loss"\n'
            "are different settings -- answer each explicitly."
        ), justify="left").pack(anchor="w", pady=(0, 8))

        self.fs_vars = {
            "continue_auto_mission_on_radio_loss": tk.BooleanVar(value=False),
            "continue_auto_mission_on_gcs_loss": tk.BooleanVar(value=False),
            "continue_guided_on_radio_loss": tk.BooleanVar(value=False),
            "continue_landing_on_any_failsafe": tk.BooleanVar(value=True),
            "continue_pilot_control_on_gcs_loss": tk.BooleanVar(value=False),
            "release_gripper_on_failsafe": tk.BooleanVar(value=False),
        }
        labels = {
            "continue_auto_mission_on_radio_loss": "Continue an active Auto mission if RC link is lost",
            "continue_auto_mission_on_gcs_loss": "Continue an active Auto mission if GCS/telemetry link is lost",
            "continue_guided_on_radio_loss": "Continue Guided mode if RC link is lost",
            "continue_landing_on_any_failsafe": "Continue landing if already landing, on any failsafe",
            "continue_pilot_control_on_gcs_loss": "Keep pilot control if only GCS link is lost while flying manually",
            "release_gripper_on_failsafe": "Release gripper during failsafe handling",
        }
        for key, var in self.fs_vars.items():
            ttk.Checkbutton(tab, text=labels[key], variable=var, command=self._update_fs_preview).pack(anchor="w")

        self.fs_preview_var = tk.StringVar()
        ttk.Label(tab, textvariable=self.fs_preview_var, wraplength=760, justify="left").pack(anchor="w", pady=8)
        self._update_fs_preview()

        ttk.Button(tab, text="Apply to FC", command=self._apply_failsafe, style="Accent.TButton").pack(anchor="w")

    def _build_intent(self) -> FailsafeIntent:
        return FailsafeIntent(**{k: v.get() for k, v in self.fs_vars.items()})

    def _update_fs_preview(self):
        value = compute_fs_options(self._build_intent())
        self.fs_preview_var.set(describe_fs_options(value))

    def _apply_failsafe(self):
        if not self._require_conn():
            return
        intent = self._build_intent()
        if not messagebox.askyesno("Confirm failsafe change", "Write FS_OPTIONS / FS_GCS_ENABLE / FS_THR_ENABLE to the FC?"):
            return
        self.worker.submit(
            apply_failsafe_intent, self.worker.conn, intent,
            on_done=lambda r: self._record_change(f"Failsafe applied (Failsafe tab): {describe_fs_options(compute_fs_options(intent))}"),
            on_error=self._on_job_error,
        )
