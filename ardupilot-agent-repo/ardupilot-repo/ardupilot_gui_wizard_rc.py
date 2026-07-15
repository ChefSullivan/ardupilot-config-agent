"""
ardupilot_gui_wizard_rc.py

Setup Wizard: RC Calibration step. Three sections:

1. Live Channel Monitor -- always-on readout of every RC channel's current
   PWM while this step is visible, with the most recently moved channel
   highlighted, so the user can wiggle a stick/switch and immediately see
   which channel number it is.
2. Role Reassignment -- read/write RCMAP_ROLL/PITCH/THROTTLE/YAW directly
   from what was just observed in the live monitor.
3. Calibrate Min/Max/Trim -- the original Guided (live-capture) / Quick
   (type known values) flow, unchanged in behavior.
"""
from __future__ import annotations

import queue
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Dict, Tuple

from ardupilot_agent.rc_calibration import (
    get_rcmap,
    set_rcmap,
    capture_center,
    capture_ranges,
    read_rc_channels,
    RCChannelCal,
    quick_apply as rc_quick_apply,
)

LIVE_MONITOR_CHANNELS = list(range(1, 13))
MOVE_THRESHOLD = 12  # PWM delta between polls that counts as "just moved"


class WizardRCMixin:
    def _init_wizard_rc_state(self):
        self.rc_capture_queue: "queue.Queue" = queue.Queue()
        self.rc_capture_active = False
        self.rc_captured_ranges: Dict[int, Tuple[int, int]] = {}
        self.rc_captured_trim: Dict[int, int] = {}
        self.rc_live_monitor_active = False
        self._rc_live_job_pending = False
        self._wizard_rc_prev_sample: Dict[int, int] = {}

    def _start_wizard_rc_polling(self):
        self.root.after(300, self._poll_rc_capture)
        self.root.after(250, self._poll_wizard_rc_live)

    # -- live monitor ------------------------------------------------------

    def _poll_wizard_rc_live(self):
        if self.rc_live_monitor_active and self.worker.conn is not None and not self._rc_live_job_pending:
            self._rc_live_job_pending = True
            self.worker.submit(read_rc_channels, self.worker.conn, timeout=0.4,
                                on_done=self._on_wizard_rc_live_sample, on_error=self._on_wizard_rc_live_error)
        self.root.after(250, self._poll_wizard_rc_live)

    def _on_wizard_rc_live_error(self, e):
        self._rc_live_job_pending = False

    def _on_wizard_rc_live_sample(self, sample):
        self._rc_live_job_pending = False
        if not hasattr(self, "_rc_live_rows"):
            return
        prev = self._wizard_rc_prev_sample
        for ch, (pwm_var, bar, name_label) in self._rc_live_rows.items():
            pwm = sample.get(ch)
            if pwm is None:
                try:
                    pwm_var.set("--")
                except tk.TclError:
                    return
                continue
            moved = ch in prev and abs(pwm - prev[ch]) >= MOVE_THRESHOLD
            try:
                pwm_var.set(str(pwm))
                bar["value"] = max(0, min(100, (pwm - 1000) / 10))
                name_label.configure(foreground="#e0a020" if moved else "")
            except tk.TclError:
                return
        self._wizard_rc_prev_sample = dict(sample)

    def _wizard_rc_toggle_monitor(self, btn):
        if not self._require_conn():
            return
        self.rc_live_monitor_active = not self.rc_live_monitor_active
        btn.configure(text="Stop Live Monitor" if self.rc_live_monitor_active else "Start Live Monitor")

    # -- role reassignment ---------------------------------------------------

    def _wizard_rc_read_rcmap_into(self, vars_by_role):
        if not self._require_conn():
            return
        self.worker.submit(
            get_rcmap, self.worker.conn,
            on_done=lambda roles: [vars_by_role[r].set(str(roles[r])) for r in roles if r in vars_by_role],
            on_error=self._on_job_error,
        )

    def _wizard_rc_apply_rcmap(self, vars_by_role):
        if not self._require_conn():
            return
        try:
            kwargs = {role: int(var.get()) for role, var in vars_by_role.items() if var.get()}
        except ValueError:
            messagebox.showerror("Invalid value", "Channel numbers must be integers.")
            return
        if not kwargs:
            return
        if not messagebox.askyesno(
            "Confirm channel reassignment",
            f"Write RCMAP_{'/'.join(k.upper() for k in kwargs)}? A reboot is recommended "
            "afterward for ArduPilot to fully pick up the remap.",
        ):
            return
        self.worker.submit(
            set_rcmap, self.worker.conn, **kwargs,
            on_done=lambda r: self._record_change(f"RCMAP updated: {kwargs}"),
            on_error=self._on_job_error,
        )

    # -- step builder --------------------------------------------------------

    def _wizard_step_rc(self, parent):
        self._wizard_leave_hook = lambda: setattr(self, "rc_live_monitor_active", False)

        ttk.Label(parent, text="RC Calibration", style="StepTitle.TLabel").pack(anchor="w")
        ttk.Label(parent, wraplength=780, justify="left", text=(
            "Keep the battery disconnected during this step (accidental arming risk) -- this "
            "toolkit's disarm gate is defense in depth on top of that, not a replacement for it."
        )).pack(anchor="w", pady=(4, 8))

        # -- Section 1: live monitor --
        mon_frame = ttk.LabelFrame(parent, text="1. Live Channel Monitor -- move a stick or "
                                                  "flip a switch and watch which row changes", padding=6)
        mon_frame.pack(fill="x", pady=(0, 10))
        toggle_btn = ttk.Button(mon_frame, text="Start Live Monitor")
        toggle_btn.configure(command=lambda: self._wizard_rc_toggle_monitor(toggle_btn))
        toggle_btn.pack(anchor="w", pady=(0, 6))

        grid = ttk.Frame(mon_frame)
        grid.pack(anchor="w", fill="x")
        self._rc_live_rows = {}
        for i, ch in enumerate(LIVE_MONITOR_CHANNELS):
            row, col = divmod(i, 4)
            cell = ttk.Frame(grid)
            cell.grid(row=row, column=col, padx=8, pady=3, sticky="w")
            name_label = ttk.Label(cell, text=f"ch{ch}", width=5)
            name_label.pack(side="left")
            pwm_var = tk.StringVar(value="--")
            ttk.Label(cell, textvariable=pwm_var, width=6, font=("Courier", 9)).pack(side="left")
            bar = ttk.Progressbar(cell, length=60, maximum=100)
            bar.pack(side="left", padx=4)
            self._rc_live_rows[ch] = (pwm_var, bar, name_label)

        # -- Section 2: role reassignment --
        role_frame = ttk.LabelFrame(parent, text="2. Which channel is which control?", padding=6)
        role_frame.pack(fill="x", pady=(0, 10))
        ttk.Label(role_frame, text=(
            "Watch the monitor above while you move each stick, then confirm/fix the channel "
            "number for each role and apply."
        ), wraplength=740, justify="left").pack(anchor="w", pady=(0, 6))
        role_vars = {}
        role_row = ttk.Frame(role_frame)
        role_row.pack(anchor="w")
        for i, role in enumerate(["roll", "pitch", "throttle", "yaw"]):
            ttk.Label(role_row, text=role.capitalize() + ":").grid(row=0, column=i * 2, sticky="w", padx=(0, 2))
            var = tk.StringVar()
            ttk.Combobox(role_row, textvariable=var, width=4, values=[str(c) for c in range(1, 17)]).grid(
                row=0, column=i * 2 + 1, padx=(0, 10)
            )
            role_vars[role] = var
        btn_row = ttk.Frame(role_frame)
        btn_row.pack(anchor="w", pady=6)
        ttk.Button(btn_row, text="Read Current RCMAP", command=lambda: self._wizard_rc_read_rcmap_into(role_vars)).pack(
            side="left"
        )
        ttk.Button(btn_row, text="Apply Channel Mapping", style="Accent.TButton",
                   command=lambda: self._wizard_rc_apply_rcmap(role_vars)).pack(
            side="left", padx=8
        )

        # -- Section 3: min/max/trim calibration (unchanged behavior) --
        cal_frame = ttk.LabelFrame(parent, text="3. Calibrate Min / Max / Trim", padding=6)
        cal_frame.pack(fill="both", expand=True)

        mode_var = tk.StringVar(value="guided")
        mode_row = ttk.Frame(cal_frame)
        mode_row.pack(anchor="w", pady=4)
        ttk.Radiobutton(mode_row, text="Guided (move sticks, watch live)", variable=mode_var,
                         value="guided", command=lambda: switch_mode()).pack(side="left")
        ttk.Radiobutton(mode_row, text="Quick (type known values)", variable=mode_var,
                         value="quick", command=lambda: switch_mode()).pack(side="left", padx=12)

        body = ttk.Frame(cal_frame)
        body.pack(fill="both", expand=True, pady=8)

        def switch_mode():
            for w in body.winfo_children():
                w.destroy()
            if mode_var.get() == "guided":
                build_guided(body)
            else:
                build_quick(body)

        def build_guided(container):
            ttk.Label(container, text="Center all sticks, throttle at minimum, then:").pack(anchor="w")
            ttk.Button(container, text="Capture Center (trim)",
                       command=self._wizard_rc_capture_center).pack(anchor="w", pady=(2, 10))

            dur_row = ttk.Frame(container)
            dur_row.pack(anchor="w")
            ttk.Label(dur_row, text="Capture duration (s):").pack(side="left")
            dur_var = tk.IntVar(value=15)
            ttk.Spinbox(dur_row, from_=5, to=60, textvariable=dur_var, width=5).pack(side="left", padx=4)
            ttk.Button(dur_row, text="Start Range Capture (now move every stick/switch to its limits)",
                       command=lambda: self._wizard_rc_start_capture(dur_var.get())).pack(side="left", padx=8)

            self.rc_live_var = tk.StringVar(value="(capture not started)")
            ttk.Label(container, textvariable=self.rc_live_var, font=("Courier", 9), justify="left").pack(
                anchor="w", pady=8
            )
            ttk.Button(container, text="Apply Captured Calibration to FC", style="Accent.TButton",
                       command=self._wizard_rc_apply_captured).pack(anchor="w", pady=8)

        def build_quick(container):
            ttk.Label(container, text=(
                "Enter known min/trim/max per channel (from your radio's display or a previous "
                "calibration) and apply directly -- no live movement needed."
            ), wraplength=740, justify="left").pack(anchor="w", pady=(0, 8))
            grid2 = ttk.Frame(container)
            grid2.pack(anchor="w")
            headers = ["Ch", "Min", "Trim", "Max", "Reversed"]
            for c, h in enumerate(headers):
                ttk.Label(grid2, text=h, font=("", 9, "bold")).grid(row=0, column=c, padx=4)
            self.rc_quick_rows = {}
            for i, ch in enumerate(range(1, 9), start=1):
                ttk.Label(grid2, text=str(ch)).grid(row=i, column=0, padx=4, pady=2)
                min_v, trim_v, max_v = tk.StringVar(), tk.StringVar(), tk.StringVar()
                rev_v = tk.BooleanVar(value=False)
                ttk.Entry(grid2, textvariable=min_v, width=8).grid(row=i, column=1)
                ttk.Entry(grid2, textvariable=trim_v, width=8).grid(row=i, column=2)
                ttk.Entry(grid2, textvariable=max_v, width=8).grid(row=i, column=3)
                ttk.Checkbutton(grid2, variable=rev_v).grid(row=i, column=4)
                self.rc_quick_rows[ch] = (min_v, trim_v, max_v, rev_v)
            ttk.Button(container, text="Apply All Filled Rows", style="Accent.TButton",
                       command=self._wizard_rc_quick_apply).pack(
                anchor="w", pady=10
            )

        build_guided(body)

    def _wizard_rc_capture_center(self):
        if not self._require_conn():
            return
        self.worker.submit(
            capture_center, self.worker.conn,
            on_done=lambda r: (self.rc_captured_trim.update(r), self._log(f"Captured center/trim: {r}\n")),
            on_error=self._on_job_error,
        )

    def _wizard_rc_start_capture(self, duration_s: int):
        if not self._require_conn():
            return
        if self.rc_capture_active:
            messagebox.showinfo("Already capturing", "A capture is already in progress.")
            return
        self.rc_capture_active = True

        def on_sample(sample, mins, maxs):
            self.rc_capture_queue.put(dict(maxs=maxs, mins=mins))

        def on_done(ranges):
            self.rc_capture_active = False
            self.rc_captured_ranges = ranges
            self._log(f"RC range capture complete: {ranges}\n")

        def on_error(e):
            self.rc_capture_active = False
            self._on_job_error(e)

        self.worker.submit(
            capture_ranges, self.worker.conn, duration_s=duration_s, on_sample=on_sample,
            on_done=on_done, on_error=on_error,
        )

    def _wizard_rc_apply_captured(self):
        if not self._require_conn():
            return
        if not self.rc_captured_ranges:
            messagebox.showwarning("No capture yet", "Run range capture before applying.")
            return
        cals = []
        for ch, (lo, hi) in self.rc_captured_ranges.items():
            trim = self.rc_captured_trim.get(ch, (lo + hi) // 2)
            cals.append(RCChannelCal(channel=ch, pwm_min=lo, pwm_max=hi, pwm_trim=trim))
        if not messagebox.askyesno("Confirm RC calibration", f"Apply calibration for {len(cals)} channel(s)?"):
            return
        self.worker.submit(
            rc_quick_apply, self.worker.conn, cals,
            on_done=lambda r: self._record_change(f"RC calibration applied for {len(cals)} channel(s) (guided capture)."),
            on_error=self._on_job_error,
        )

    def _wizard_rc_quick_apply(self):
        if not self._require_conn():
            return
        cals = []
        for ch, (min_v, trim_v, max_v, rev_v) in self.rc_quick_rows.items():
            if not (min_v.get() and trim_v.get() and max_v.get()):
                continue
            try:
                cals.append(RCChannelCal(
                    channel=ch, pwm_min=int(min_v.get()), pwm_max=int(max_v.get()),
                    pwm_trim=int(trim_v.get()), reversed=rev_v.get(),
                ))
            except ValueError:
                messagebox.showerror("Invalid value", f"Channel {ch}: min/trim/max must be numbers.")
                return
        if not cals:
            messagebox.showwarning("Nothing to apply", "Fill in at least one channel's row first.")
            return
        if not messagebox.askyesno("Confirm RC calibration", f"Apply calibration for {len(cals)} channel(s)?"):
            return
        self.worker.submit(
            rc_quick_apply, self.worker.conn, cals,
            on_done=lambda r: self._record_change(f"RC calibration applied for {len(cals)} channel(s) (quick mode)."),
            on_error=self._on_job_error,
        )

    def _poll_rc_capture(self):
        latest = None
        while True:
            try:
                latest = self.rc_capture_queue.get_nowait()
            except queue.Empty:
                break
        if latest is not None and hasattr(self, "rc_live_var"):
            mins, maxs = latest["mins"], latest["maxs"]
            text = "  ".join(f"ch{ch}: {mins[ch]}-{maxs[ch]}" for ch in sorted(maxs))
            try:
                self.rc_live_var.set(text or "(no samples yet)")
            except tk.TclError:
                pass
        self.root.after(300, self._poll_rc_capture)
