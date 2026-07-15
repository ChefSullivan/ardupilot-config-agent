"""
ardupilot_gui_wizard_frame.py

Setup Wizard: Frame Class Review step. Shows FRAME_CLASS/FRAME_TYPE with
their human-readable meaning (Quad/Hexa/Octa/BetaFlightX/etc), plus the
detected top-level vehicle type (Copter/Plane/Rover/etc) from the live
HEARTBEAT -- FRAME_CLASS is Copter-specific, so knowing the vehicle family
first avoids reading a meaningless value on non-Copter firmware.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

from ardupilot_agent.params import get_param
from ardupilot_agent.vehicle_info import (
    describe_frame_class,
    describe_frame_type,
    get_vehicle_type_name,
    apply_frame_class_and_type,
    FRAME_CLASS_NAMES,
    FRAME_TYPE_NAMES,
)


class WizardFrameMixin:
    def _wizard_step_frame(self, parent):
        ttk.Label(parent, text="Review FRAME_CLASS / FRAME_TYPE", style="StepTitle.TLabel").pack(anchor="w")
        ttk.Label(parent, wraplength=780, justify="left", text=(
            "FRAME_CLASS=0 (undefined) is a valid-but-broken default that silently blocks "
            "arming -- worth catching here before anything else. This step is read-only; edit "
            "these in the Parameters tab if they need to change, using the exact value from "
            "https://ardupilot.org/copter/docs/frame-type-configuration.html for your frame. "
            "FRAME_CLASS/FRAME_TYPE are Copter-specific -- if your firmware is Plane/Rover/Sub, "
            "these don't apply the same way (or may not exist)."
        )).pack(anchor="w", pady=8)

        result_var = tk.StringVar(value="(not read yet)")
        ttk.Label(parent, textvariable=result_var, font=("Courier", 10), justify="left").pack(anchor="w", pady=8)

        def show(text):
            current = result_var.get()
            if current in ("(not read yet)", "(reading...)"):
                result_var.set(text)
            else:
                result_var.set(current + "\n" + text)

        def read_vehicle_type():
            name = get_vehicle_type_name(self.worker.conn)
            self.root.after(0, lambda: show(f"Vehicle type (from HEARTBEAT): {name or 'unknown -- no heartbeat yet'}"))

        def read_frame_class():
            v = get_param(self.worker.conn, "FRAME_CLASS")
            self.root.after(0, lambda: show(f"FRAME_CLASS = {describe_frame_class(v)}"))
            if int(v) == 0:
                self.root.after(0, lambda: messagebox.showwarning(
                    "FRAME_CLASS is 0", "FRAME_CLASS=0 (undefined) will silently block arming. "
                    "Set it correctly in the Parameters tab before continuing."))
            return v

        def read_frame_type():
            v = get_param(self.worker.conn, "FRAME_TYPE")
            self.root.after(0, lambda: show(f"FRAME_TYPE = {describe_frame_type(v)}"))

        def refresh():
            if not self._require_conn():
                return
            result_var.set("(reading...)")
            self.worker.submit(read_vehicle_type, on_done=lambda r: None, on_error=self._on_job_error)
            self.worker.submit(read_frame_class, on_done=lambda r: None, on_error=self._on_job_error)
            self.worker.submit(read_frame_type, on_done=lambda r: None, on_error=self._on_job_error)

        ttk.Button(parent, text="Read Current Values", command=refresh).pack(anchor="w")

        set_frame = ttk.LabelFrame(parent, text="Set / change FRAME_CLASS and FRAME_TYPE", padding=6)
        set_frame.pack(fill="x", pady=(12, 0))
        ttk.Label(set_frame, text=(
            "Only change these if they're wrong or still at the FRAME_CLASS=0 default. Pick the "
            "values that match your actual physical frame -- see "
            "https://ardupilot.org/copter/docs/connect-escs-and-motors.html if you're not sure."
        ), wraplength=740, justify="left").pack(anchor="w", pady=(0, 6))

        row = ttk.Frame(set_frame)
        row.pack(anchor="w")
        class_labels = [f"{v} - {name}" for v, name in sorted(FRAME_CLASS_NAMES.items())]
        type_labels = [f"{v} - {name}" for v, name in sorted(FRAME_TYPE_NAMES.items())]
        ttk.Label(row, text="FRAME_CLASS:").grid(row=0, column=0, sticky="w")
        class_var = tk.StringVar()
        ttk.Combobox(row, textvariable=class_var, width=26, state="readonly", values=class_labels).grid(
            row=0, column=1, padx=6, pady=2
        )
        ttk.Label(row, text="FRAME_TYPE:").grid(row=1, column=0, sticky="w")
        type_var = tk.StringVar()
        ttk.Combobox(row, textvariable=type_var, width=26, state="readonly", values=type_labels).grid(
            row=1, column=1, padx=6, pady=2
        )

        def apply_frame():
            if not self._require_conn():
                return
            if not class_var.get() or not type_var.get():
                messagebox.showwarning("Pick both values", "Choose a FRAME_CLASS and FRAME_TYPE first.")
                return
            frame_class = int(class_var.get().split(" - ")[0])
            frame_type = int(type_var.get().split(" - ")[0])
            if not messagebox.askyesno(
                "Confirm frame change",
                f"Write FRAME_CLASS={frame_class} and FRAME_TYPE={frame_type} and reboot the FC?",
            ):
                return
            self.worker.submit(
                apply_frame_class_and_type, self.worker.conn, frame_class, frame_type,
                on_done=lambda r: self._record_change(
                    f"FRAME_CLASS={frame_class} ({FRAME_CLASS_NAMES.get(frame_class, '?')}), "
                    f"FRAME_TYPE={frame_type} ({FRAME_TYPE_NAMES.get(frame_type, '?')})"),
                on_error=self._on_job_error,
            )

        ttk.Button(set_frame, text="Apply Frame Class/Type (reboots FC)", style="Accent.TButton",
                   command=apply_frame).pack(anchor="w", pady=(8, 0))
