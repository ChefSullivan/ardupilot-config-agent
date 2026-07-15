"""
ardupilot_gui_wizard_esc.py

Setup Wizard: ESC Calibration step, simplified per feedback that the full
checklist felt confusing and often unnecessary. Now: the protocol check
runs automatically when the step opens, leads with a plain "skip this" or
"you need this" verdict, and the detailed step-by-step checklist is
collapsed behind a button instead of always shown.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

from ardupilot_agent.esc_calibration import (
    needs_calibration as esc_needs_calibration,
    start_semi_automatic as esc_start_semi_automatic,
    verify_calibration_flag_cleared,
    ALL_AT_ONCE_STEPS,
    SEMI_AUTOMATIC_STEPS_AFTER_POWER_CYCLE,
)


class WizardEscMixin:
    def _wizard_step_esc(self, parent):
        ttk.Label(parent, text="ESC Calibration", style="StepTitle.TLabel").pack(anchor="w")

        verdict_var = tk.StringVar(value="Checking your ESC protocol...")
        ttk.Label(parent, textvariable=verdict_var, font=("", 11, "bold"), wraplength=780, justify="left").pack(
            anchor="w", pady=(6, 10)
        )

        action_frame = ttk.Frame(parent)
        action_frame.pack(anchor="w", fill="x")

        details_frame = ttk.Frame(parent)
        # not packed until the user asks to see it -- keeps the step
        # simple by default.

        def show_details():
            if details_frame.winfo_ismapped():
                details_frame.pack_forget()
                details_btn.configure(text="Show detailed steps")
                return
            details_frame.pack(fill="both", expand=True, pady=(8, 0))
            details_btn.configure(text="Hide detailed steps")

        details_btn = ttk.Button(parent, text="Show detailed steps", command=show_details)

        def build_needed_ui():
            for w in action_frame.winfo_children():
                w.destroy()
            details_btn.pack(anchor="w", pady=(4, 0))

            for w in details_frame.winfo_children():
                w.destroy()
            steps_text = "All-at-once method:\n" + "\n".join(f"  {i + 1}. {s}" for i, s in enumerate(ALL_AT_ONCE_STEPS))
            text_widget = tk.Text(details_frame, height=11, wrap="word")
            text_widget.insert("1.0", steps_text)
            text_widget.configure(state="disabled")
            text_widget.pack(fill="both", expand=True, pady=(0, 8))
            self._register_dark_widget(text_widget, "text")

            semi_row = ttk.Frame(details_frame)
            semi_row.pack(anchor="w")

            def start_semi():
                if not self._require_conn():
                    return
                if not messagebox.askyesno(
                    "Confirm ESC_CALIBRATION",
                    "This sets ESC_CALIBRATION=3. After this, disconnect USB + battery, then "
                    "reconnect ONLY the battery to begin. Continue?",
                ):
                    return
                self.worker.submit(
                    esc_start_semi_automatic, self.worker.conn,
                    on_done=lambda r: self._record_change("ESC_CALIBRATION=3 set (semi-automatic calibration armed)"),
                    on_error=self._on_job_error,
                )

            def verify_after():
                if not self._require_conn():
                    return
                self.worker.submit(
                    verify_calibration_flag_cleared, self.worker.conn,
                    on_done=lambda ok: messagebox.showinfo(
                        "Verification",
                        "ESC_CALIBRATION reads 0 -- consistent with calibration having run. "
                        "Confirm you heard the completion tone too." if ok else
                        "ESC_CALIBRATION is not 0 -- calibration may not have completed. Check the tone sequence."
                    ),
                    on_error=self._on_job_error,
                )

            ttk.Button(semi_row, text="Start Semi-Automatic Calibration", command=start_semi).pack(side="left")
            ttk.Button(semi_row, text="Verify After Reconnecting", command=verify_after).pack(side="left", padx=8)
            ttk.Label(details_frame, text="After power-cycling: " + " / ".join(SEMI_AUTOMATIC_STEPS_AFTER_POWER_CYCLE),
                      wraplength=780, justify="left", foreground="#888").pack(anchor="w", pady=(6, 0))

        def build_skip_ui():
            for w in action_frame.winfo_children():
                w.destroy()
            details_btn.pack_forget()
            details_frame.pack_forget()
            ttk.Label(action_frame, text="Nothing to do here -- click Next to continue.",
                      foreground="#2e8b57").pack(anchor="w")

        def on_checked(needed: bool):
            if needed:
                verdict_var.set("Your ESC protocol (MOT_PWM_TYPE) needs calibration. Expand the details "
                                 "below when you're ready to run it.")
                build_needed_ui()
            else:
                verdict_var.set("Your ESC protocol is digital/DShot -- calibration is NOT required. Skip this step.")
                build_skip_ui()
            # The step's content just changed size (often shrinking, once the
            # "not needed" verdict comes back) -- recalculate the scroll
            # region rather than leaving whatever was computed for the
            # initial "Checking..." placeholder state.
            if hasattr(self, "_wizard_recalc_scrollregion"):
                self._wizard_recalc_scrollregion()

        def check():
            if self.worker.conn is None:
                verdict_var.set("Connect to the flight controller (top bar) to check your ESC protocol.")
                return
            self.worker.submit(esc_needs_calibration, self.worker.conn,
                                on_done=on_checked, on_error=self._on_job_error)

        ttk.Button(parent, text="Re-check ESC Protocol", command=check).pack(anchor="w", pady=(0, 6))
        self.root.after(50, check)
