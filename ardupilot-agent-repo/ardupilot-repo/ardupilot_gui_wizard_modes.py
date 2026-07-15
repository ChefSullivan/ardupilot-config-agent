"""
ardupilot_gui_wizard_modes.py

Setup Wizard: Flight Mode / Switch Assignment step. Adds a live readout of
the flight-mode channel's PWM and which of the 6 switch slots it currently
falls into -- so flipping the physical switch on the transmitter shows,
in real time, "you are on slot N right now", and a mode can be assigned to
that exact slot without doing PWM-range arithmetic by hand.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Dict

from ardupilot_agent.rc_calibration import read_rc_channels
from ardupilot_agent.flight_modes import (
    FLIGHT_MODE_NUMBERS,
    FLTMODE_CH_VALUES,
    ModeAssignment,
    get_flight_mode_channel,
    set_flight_mode_channel,
    set_flight_modes,
    read_current_assignments,
    slot_for_pwm,
    MODE_DESCRIPTIONS,
)


class WizardModesMixin:
    def _init_wizard_modes_state(self):
        self.modes_live_monitor_active = False
        self._modes_live_job_pending = False

    def _start_wizard_modes_polling(self):
        self.root.after(300, self._poll_wizard_modes_live)

    def _poll_wizard_modes_live(self):
        if (self.modes_live_monitor_active and self.worker.conn is not None
                and not self._modes_live_job_pending and hasattr(self, "_modes_ch_var")):
            self._modes_live_job_pending = True
            self.worker.submit(read_rc_channels, self.worker.conn, timeout=0.4,
                                on_done=self._on_wizard_modes_live_sample, on_error=self._on_wizard_modes_live_error)
        self.root.after(300, self._poll_wizard_modes_live)

    def _on_wizard_modes_live_error(self, e):
        self._modes_live_job_pending = False

    def _on_wizard_modes_live_sample(self, sample):
        self._modes_live_job_pending = False
        if not hasattr(self, "_modes_current_slot_var"):
            return
        try:
            ch = int(self._modes_ch_var.get())
        except (ValueError, tk.TclError):
            return
        pwm = sample.get(ch)
        if pwm is None:
            try:
                self._modes_current_slot_var.set(f"No signal on channel {ch} yet.")
            except tk.TclError:
                return
            return
        slot = slot_for_pwm(pwm)
        try:
            self._modes_current_slot_var.set(f"Switch is currently on Slot {slot}  (channel {ch} = {pwm} PWM)")
            self._modes_current_slot = slot
        except tk.TclError:
            pass

    def _wizard_modes_toggle_monitor(self, btn):
        if not self._require_conn():
            return
        self.modes_live_monitor_active = not self.modes_live_monitor_active
        btn.configure(text="Stop Live Monitor" if self.modes_live_monitor_active else "Start Live Monitor")

    def _wizard_modes_assign_current_slot(self, mode_var):
        slot = getattr(self, "_modes_current_slot", None)
        if slot is None:
            messagebox.showwarning("No live reading yet", "Start the live monitor and flip the switch first.")
            return
        mode_name = mode_var.get()
        if not mode_name:
            messagebox.showwarning("Pick a mode", "Choose a flight mode to assign first.")
            return
        if slot in self.wizard_mode_vars:
            self.wizard_mode_vars[slot].set(mode_name)
        if not messagebox.askyesno("Confirm", f"Assign {mode_name} to Slot {slot} (writes FLTMODE{slot})?"):
            return
        self.worker.submit(
            set_flight_modes, self.worker.conn, [ModeAssignment(slot=slot, mode_name=mode_name)],
            on_done=lambda r: self._record_change(f"FLTMODE{slot} = {mode_name} (assigned via live switch flip)"),
            on_error=self._on_job_error,
        )

    def _wizard_step_modes(self, parent):
        self._wizard_leave_hook = lambda: setattr(self, "modes_live_monitor_active", False)

        ttk.Label(parent, text="Flight Mode / Switch Assignment", style="StepTitle.TLabel").pack(anchor="w")
        ttk.Label(parent, wraplength=780, justify="left", text=(
            "Assigns a flight mode to each of the 6 switch positions on FLTMODE_CH. ArduPilot "
            "recommends always leaving at least one position on Stabilize as a fallback."
        )).pack(anchor="w", pady=(4, 8))

        ch_row = ttk.Frame(parent)
        ch_row.pack(anchor="w", pady=4)
        ttk.Label(ch_row, text="Flight mode channel (FLTMODE_CH):").pack(side="left")
        self._modes_ch_var = tk.IntVar(value=5)
        ttk.Combobox(ch_row, textvariable=self._modes_ch_var, width=6, state="readonly",
                     values=sorted(FLTMODE_CH_VALUES.keys())).pack(side="left", padx=4)
        ttk.Button(ch_row, text="Read Current", command=lambda: self._wizard_modes_read_channel(self._modes_ch_var)).pack(
            side="left", padx=4
        )
        ttk.Button(ch_row, text="Set Channel", command=lambda: self._wizard_modes_set_channel(self._modes_ch_var.get())).pack(
            side="left"
        )

        live_frame = ttk.LabelFrame(parent, text="Live switch position -- flip the switch on your "
                                                   "transmitter and watch this update", padding=6)
        live_frame.pack(fill="x", pady=8)
        toggle_btn = ttk.Button(live_frame, text="Start Live Monitor")
        toggle_btn.configure(command=lambda: self._wizard_modes_toggle_monitor(toggle_btn))
        toggle_btn.pack(anchor="w")
        self._modes_current_slot_var = tk.StringVar(value="(live monitor not started)")
        ttk.Label(live_frame, textvariable=self._modes_current_slot_var, font=("", 10, "bold")).pack(
            anchor="w", pady=6
        )
        quick_row = ttk.Frame(live_frame)
        quick_row.pack(anchor="w")
        ttk.Label(quick_row, text="Assign to current slot:").pack(side="left")
        quick_mode_var = tk.StringVar()
        ttk.Combobox(quick_row, textvariable=quick_mode_var, width=16, state="readonly",
                     values=sorted(FLIGHT_MODE_NUMBERS.keys())).pack(side="left", padx=4)
        ttk.Button(quick_row, text="Assign", style="Accent.TButton",
                   command=lambda: self._wizard_modes_assign_current_slot(quick_mode_var)).pack(
            side="left", padx=4
        )

        grid = ttk.Frame(parent)
        grid.pack(anchor="w", pady=10)
        self.wizard_mode_vars: Dict[int, tk.StringVar] = {}
        mode_names = sorted(FLIGHT_MODE_NUMBERS.keys())
        desc_var = tk.StringVar(value="Select a mode to see its description here.")
        for slot in range(1, 7):
            ttk.Label(grid, text=f"Slot {slot}:").grid(row=slot, column=0, sticky="w", pady=2)
            var = tk.StringVar(value="STABILIZE" if slot == 1 else "")
            combo = ttk.Combobox(grid, textvariable=var, width=18, state="readonly", values=mode_names)
            combo.grid(row=slot, column=1, padx=4)
            combo.bind("<<ComboboxSelected>>", lambda e, v=var: desc_var.set(
                MODE_DESCRIPTIONS.get(v.get(), {}).get("summary", "")
            ))
            self.wizard_mode_vars[slot] = var
        ttk.Label(parent, textvariable=desc_var, wraplength=780, justify="left", foreground="#555").pack(
            anchor="w", pady=(0, 8)
        )
        ttk.Button(parent, text="Read Current Assignments", command=self._wizard_modes_read_all).pack(anchor="w")
        ttk.Button(parent, text="Apply All Slots", style="Accent.TButton", command=self._wizard_modes_apply).pack(anchor="w", pady=6)

    def _wizard_modes_read_channel(self, ch_var: tk.IntVar):
        if not self._require_conn():
            return
        self.worker.submit(get_flight_mode_channel, self.worker.conn,
                            on_done=lambda v: ch_var.set(v), on_error=self._on_job_error)

    def _wizard_modes_set_channel(self, channel: int):
        if not self._require_conn():
            return
        self.worker.submit(set_flight_mode_channel, self.worker.conn, channel,
                            on_done=lambda r: self._record_change(f"FLTMODE_CH set to {channel}"),
                            on_error=self._on_job_error)

    def _wizard_modes_read_all(self):
        if not self._require_conn():
            return

        def apply_to_ui(assignments):
            for slot, name in assignments.items():
                if slot in self.wizard_mode_vars and name in FLIGHT_MODE_NUMBERS:
                    self.wizard_mode_vars[slot].set(name)

        self.worker.submit(read_current_assignments, self.worker.conn,
                            on_done=apply_to_ui, on_error=self._on_job_error)

    def _wizard_modes_apply(self):
        if not self._require_conn():
            return
        assignments = []
        for slot, var in self.wizard_mode_vars.items():
            if var.get():
                assignments.append(ModeAssignment(slot=slot, mode_name=var.get()))
        if not assignments:
            messagebox.showwarning("Nothing to apply", "Assign at least one slot first.")
            return
        if not messagebox.askyesno("Confirm flight modes", f"Write {len(assignments)} FLTMODEn parameter(s)?"):
            return
        self.worker.submit(
            set_flight_modes, self.worker.conn, assignments,
            on_done=lambda r: self._record_change(f"Flight modes applied: {[(a.slot, a.mode_name) for a in assignments]}"),
            on_error=self._on_job_error,
        )
