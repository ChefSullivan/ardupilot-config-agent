"""
ardupilot_gui_wizard_motors.py

Setup Wizard: Motor Order & Direction step. Section 1 is the existing
empirical per-instance diagnosis (SERVOx_FUNCTION corner-mapping fixes).
Section 2 is new: motor *rotation direction*, which SERVOx_FUNCTION does
not touch at all. For analog PWM/OneShot/OneShot125 ESCs there is no
software fix (physically swap 2 of 3 motor/ESC wires); for DShot ESCs the
DShot "reverse motor direction" command can flip it via SERVO_BLH_RVMASK,
see ardupilot_agent/motor_direction.py for the verified details.
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
from ardupilot_agent.motor_direction import (
    is_dshot_protocol,
    dshot_commands_enabled,
    enable_dshot_commands,
    get_reversed_channels,
    set_channel_reversed,
)

STANDARD_QUAD_CORNERS = ["front-right", "rear-left", "front-left", "rear-right"]


class WizardMotorsMixin:
    def _wizard_step_motors(self, parent):
        ttk.Label(parent, text="Motor Order & Direction", style="StepTitle.TLabel").pack(anchor="w")
        ttk.Label(parent, text=(
            "Same empirical per-instance test as the Motor Map tab, embedded here in sequence. "
            "Props off recommended. Throttle >=15-20% so a working motor doesn't look dead."
        ), wraplength=780, justify="left").pack(anchor="w", pady=(4, 8))

        cfg = ttk.Frame(parent)
        cfg.pack(fill="x", pady=4)
        ttk.Label(cfg, text="Motor count:").grid(row=0, column=0, sticky="w")
        count_var = tk.IntVar(value=4)
        ttk.Spinbox(cfg, from_=2, to=8, textvariable=count_var, width=5).grid(row=0, column=1, padx=4)
        ttk.Label(cfg, text="Throttle %:").grid(row=0, column=2, sticky="w", padx=(12, 0))
        throttle_var = tk.IntVar(value=20)
        ttk.Spinbox(cfg, from_=15, to=40, textvariable=throttle_var, width=5).grid(row=0, column=3, padx=4)
        ttk.Label(cfg, text="Frame type:").grid(row=0, column=4, sticky="w", padx=(12, 0))
        frame_var = tk.StringVar(value=list(FRAME_EXPECTED_LAYOUTS.keys())[0] if FRAME_EXPECTED_LAYOUTS else "")
        ttk.Combobox(cfg, textvariable=frame_var, width=16, values=list(FRAME_EXPECTED_LAYOUTS.keys())).grid(
            row=0, column=5, padx=4
        )

        self.wizard_motor_start_btn = ttk.Button(
            parent, text="Start Diagnosis",
            command=lambda: self._wizard_start_motor_map(count_var.get(), throttle_var.get(), frame_var.get()),
        )
        self.wizard_motor_start_btn.pack(anchor="w", pady=6)

        self.wizard_motor_prompt_var = tk.StringVar(value="")
        ttk.Label(parent, textvariable=self.wizard_motor_prompt_var, font=("", 10, "bold")).pack(anchor="w", pady=4)
        self.wizard_corner_frame = ttk.Frame(parent)
        self.wizard_corner_frame.pack(anchor="w", pady=4)
        self.wizard_motor_table = tk.Listbox(parent, height=6)
        self.wizard_motor_table.pack(fill="both", expand=False, pady=8)
        self._register_dark_widget(self.wizard_motor_table, "listbox")
        self.wizard_apply_fixes_btn = ttk.Button(
            parent, text="Apply SERVOx_FUNCTION Fixes (reboots FC)", style="Accent.TButton",
            command=self._wizard_apply_motor_fixes, state="disabled",
        )
        self.wizard_apply_fixes_btn.pack(anchor="w")
        self.wizard_pending_fixes = {}

        # -- rotation direction --
        dir_frame = ttk.LabelFrame(parent, text="Motor Rotation Direction (CW/CCW)", padding=6)
        dir_frame.pack(fill="both", expand=True, pady=(12, 0))
        ttk.Label(dir_frame, wraplength=740, justify="left", text=(
            "SERVOx_FUNCTION fixes above only correct which corner responds to which mixer "
            "input -- they don't fix which way a motor spins. If a motor spins the wrong "
            "direction:\n"
            "  • Normal PWM / OneShot / OneShot125 ESCs: no software fix -- physically swap "
            "any 2 of the 3 motor/ESC wires.\n"
            "  • DShot ESCs (BLHeli32/AM32/BLHeli_S): can be reversed in software below, no "
            "wiring changes needed."
        )).pack(anchor="w", pady=(0, 8))

        status_var = tk.StringVar(value="(not checked yet)")
        ttk.Label(dir_frame, textvariable=status_var, font=("", 10, "bold"), wraplength=740, justify="left").pack(
            anchor="w", pady=4
        )
        reverse_body = ttk.Frame(dir_frame)
        reverse_body.pack(fill="x", pady=6)

        def check_protocol():
            if not self._require_conn():
                return
            self.worker.submit(is_dshot_protocol, self.worker.conn,
                                on_done=lambda dshot: on_protocol_checked(dshot), on_error=self._on_job_error)

        def on_protocol_checked(dshot: bool):
            if not dshot:
                status_var.set("MOT_PWM_TYPE is analog PWM/OneShot/OneShot125 -- no software direction "
                                "reversal available. Swap 2 of 3 motor/ESC wires for any motor spinning "
                                "the wrong way.")
                for w in reverse_body.winfo_children():
                    w.destroy()
                return
            status_var.set("DShot protocol detected -- checking whether DShot commands are enabled...")
            self.worker.submit(dshot_commands_enabled, self.worker.conn,
                                on_done=on_commands_checked, on_error=self._on_job_error)

        def on_commands_checked(enabled: bool):
            for w in reverse_body.winfo_children():
                w.destroy()
            if not enabled:
                status_var.set("DShot protocol detected, but SERVO_DSHOT_ESC is not set -- DShot "
                                "commands (including reverse) won't be sent yet.")
                ttk.Button(reverse_body, text="Enable DShot Commands (SERVO_DSHOT_ESC=1) -- only for "
                                               "BLHeli32/AM32/BLHeli_S ESCs",
                           command=enable_commands).pack(anchor="w")
                return
            status_var.set("DShot commands enabled. Pick which output channels should spin reversed:")
            build_reverse_controls()

        def enable_commands():
            if not messagebox.askyesno("Confirm", "Set SERVO_DSHOT_ESC=1? Only do this if your ESCs are "
                                                    "BLHeli32/AM32/BLHeli_S -- an unrecognized ESC receiving "
                                                    "this is documented as undefined behavior."):
                return
            self.worker.submit(enable_dshot_commands, self.worker.conn,
                                on_done=lambda r: (self._record_change("SERVO_DSHOT_ESC set to 1"), check_protocol()),
                                on_error=self._on_job_error)

        def build_reverse_controls():
            channels = sorted({e.channel for e in getattr(self, "wizard_motor_entries", [])}) or list(range(1, 5))
            self.worker.submit(get_reversed_channels, self.worker.conn,
                                on_done=lambda current: render_checks(channels, current),
                                on_error=self._on_job_error)

        def render_checks(channels, current):
            vars_by_ch = {}
            grid = ttk.Frame(reverse_body)
            grid.pack(anchor="w")
            for i, ch in enumerate(channels):
                v = tk.BooleanVar(value=ch in current)
                vars_by_ch[ch] = v
                ttk.Checkbutton(grid, text=f"Motor output ch{ch} reversed", variable=v).grid(
                    row=i // 3, column=i % 3, sticky="w", padx=8, pady=2
                )

            def apply_reverse():
                if not messagebox.askyesno("Confirm direction reversal",
                                            "Write SERVO_BLH_RVMASK changes and reboot is recommended after?"):
                    return
                changed = [ch for ch, v in vars_by_ch.items() if v.get() != (ch in current)]
                if not changed:
                    messagebox.showinfo("No changes", "No reversal checkboxes were changed.")
                    return

                def do_apply():
                    for ch in changed:
                        set_channel_reversed(self.worker.conn, ch, vars_by_ch[ch].get())
                    return changed

                self.worker.submit(do_apply,
                                    on_done=lambda ch_list: self._record_change(
                                        f"SERVO_BLH_RVMASK reversal toggled for channel(s): {ch_list}"),
                                    on_error=self._on_job_error)

            ttk.Button(reverse_body, text="Apply Reversal Changes", style="Accent.TButton", command=apply_reverse).pack(anchor="w", pady=6)

        ttk.Button(dir_frame, text="Check ESC Protocol / Direction Options", command=check_protocol).pack(anchor="w")

    def _wizard_start_motor_map(self, count, throttle, frame_key):
        if not self._require_conn():
            return
        self.wizard_motor_count = count
        self.wizard_motor_throttle = throttle
        self.wizard_motor_frame_key = frame_key
        self.wizard_motor_entries = []
        self.wizard_motor_index = 1
        self.wizard_motor_table.delete(0, tk.END)
        self.wizard_apply_fixes_btn.configure(state="disabled")
        self.wizard_motor_start_btn.configure(state="disabled")
        self.worker.submit(request_servo_output_stream, self.worker.conn,
                            on_done=lambda r: self._wizard_test_next_motor(), on_error=self._on_job_error)

    def _wizard_test_next_motor(self):
        if self.wizard_motor_index > self.wizard_motor_count:
            self._wizard_finish_motor_map()
            return
        self.wizard_motor_prompt_var.set(f"Testing motor instance {self.wizard_motor_index}...")
        self.worker.submit(
            diagnose_one_instance, self.worker.conn, self.wizard_motor_index,
            throttle_pct=self.wizard_motor_throttle,
            on_done=self._wizard_on_motor_sample, on_error=self._wizard_on_motor_error,
        )

    def _wizard_on_motor_error(self, e: Exception):
        self.wizard_motor_start_btn.configure(state="normal")
        self.wizard_motor_prompt_var.set("")
        messagebox.showerror("Motor test failed", str(e))

    def _wizard_on_motor_sample(self, sample):
        self._wizard_current_channel = sample.channel
        self.wizard_motor_prompt_var.set(
            f"Motor instance {self.wizard_motor_index} spun output channel {sample.channel}. "
            f"Which physical corner spun?"
        )
        for w in self.wizard_corner_frame.winfo_children():
            w.destroy()
        if self.wizard_motor_count == 4:
            for corner in STANDARD_QUAD_CORNERS:
                ttk.Button(self.wizard_corner_frame, text=corner,
                           command=lambda c=corner: self._wizard_corner_selected(c)).pack(side="left", padx=4)
        else:
            entry_var = tk.StringVar()
            ttk.Entry(self.wizard_corner_frame, textvariable=entry_var, width=20).pack(side="left", padx=4)
            ttk.Button(self.wizard_corner_frame, text="Confirm",
                       command=lambda: self._wizard_corner_selected(entry_var.get().strip().lower())).pack(
                side="left"
            )

    def _wizard_corner_selected(self, corner: str):
        if not corner:
            return
        self.wizard_motor_entries.append(
            MotorMapEntry(instance=self.wizard_motor_index, channel=self._wizard_current_channel, corner=corner)
        )
        self.wizard_motor_table.insert(
            tk.END, f"instance {self.wizard_motor_index} -> channel {self._wizard_current_channel} -> {corner}"
        )
        for w in self.wizard_corner_frame.winfo_children():
            w.destroy()
        self.wizard_motor_index += 1
        self._wizard_test_next_motor()

    def _wizard_finish_motor_map(self):
        self.wizard_motor_start_btn.configure(state="normal")
        self.wizard_motor_prompt_var.set("Diagnosis complete.")
        if self.wizard_motor_frame_key and self.wizard_motor_frame_key in FRAME_EXPECTED_LAYOUTS:
            expected = FRAME_EXPECTED_LAYOUTS[self.wizard_motor_frame_key]
            try:
                fixes = compute_servo_function_fixes(self.wizard_motor_entries, expected)
            except KeyError as e:
                messagebox.showwarning("Can't compute fixes", str(e))
                return
            self.wizard_pending_fixes = fixes
            for ch, func_val in fixes.items():
                self.wizard_motor_table.insert(tk.END, f"  -> fix: SERVO{ch}_FUNCTION = {func_val}")
            self.wizard_apply_fixes_btn.configure(state="normal")
        else:
            self.wizard_motor_table.insert(
                tk.END, "  (frame type not in local reference cache -- wiring table only, no fixes computed)"
            )

    def _wizard_apply_motor_fixes(self):
        if not self._require_conn():
            return
        if not messagebox.askyesno(
            "Confirm SERVOx_FUNCTION changes",
            f"This writes {len(self.wizard_pending_fixes)} SERVOx_FUNCTION parameter(s) and reboots the FC. Continue?",
        ):
            return
        self.wizard_apply_fixes_btn.configure(state="disabled")
        self.worker.submit(
            apply_servo_function_fixes, self.worker.conn, self.wizard_pending_fixes,
            on_done=lambda r: self._record_change(
                f"SERVOx_FUNCTION fixes applied and verified after reboot: {self.wizard_pending_fixes}"),
            on_error=self._on_job_error,
        )
