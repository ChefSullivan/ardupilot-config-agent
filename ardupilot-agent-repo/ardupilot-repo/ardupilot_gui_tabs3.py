"""
ardupilot_gui_tabs3.py

Compatibility tab: reads the connected FC's firmware version and checks
whether every parameter this toolkit relies on anywhere still exists under
the name this toolkit expects. This is the answer to "what happens when
ArduPilot updates and something this tool assumes is no longer true" --
run this any time something in the wizard behaves unexpectedly, or right
after updating firmware, and it tells you exactly which step (if any) is
affected instead of a confusing failure deep inside that step.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ardupilot_agent.compatibility import run_compatibility_check


class CompatibilityTabMixin:
    def _build_compat_tab_if_present(self, nb):
        self._build_compat_tab(nb)

    def _open_compat_tab(self):
        if hasattr(self, "notebook") and hasattr(self, "_compat_tab_widget"):
            self.notebook.select(self._compat_tab_widget)

    def _build_compat_tab(self, nb):
        tab = ttk.Frame(nb, padding=8)
        nb.add(tab, text="Compatibility")
        self._compat_tab_widget = tab

        ttk.Label(tab, text="Firmware Compatibility Check", style="StepTitle.TLabel").pack(anchor="w")
        ttk.Label(tab, wraplength=880, justify="left", text=(
            "Every parameter name and enum value in this toolkit was written against a specific "
            "version of ArduPilot's docs/firmware -- if a future update renames, removes, or "
            "changes the meaning of one of them, this is how you'd find out, rather than a "
            "wizard step failing in a confusing way. This checks the parameters directly "
            "against your connected FC's live firmware, not against anything cached."
        ), style="Muted.TLabel").pack(anchor="w", pady=(4, 8))

        self.compat_version_var = tk.StringVar(value="(not checked yet)")
        ttk.Label(tab, textvariable=self.compat_version_var, font=("Segoe UI", 10, "bold")).pack(
            anchor="w", pady=(0, 8)
        )

        ttk.Button(tab, text="Run Compatibility Check", style="Accent.TButton",
                   command=self._run_compat_check).pack(anchor="w")

        self.compat_results = tk.Listbox(tab, height=18)
        self.compat_results.pack(fill="both", expand=True, pady=8)
        self._register_dark_widget(self.compat_results, "listbox")

    def _run_compat_check(self):
        if not self._require_conn():
            return
        self.compat_version_var.set("Checking...")
        self.compat_results.delete(0, tk.END)
        self.worker.submit(run_compatibility_check, self.worker.conn,
                            on_done=self._on_compat_result, on_error=self._on_job_error)

    def _on_compat_result(self, report):
        version = report.firmware_version or "unknown (FC didn't answer the version request -- may be very old firmware)"
        self.compat_version_var.set(f"Connected firmware: {version}")
        self.compat_results.delete(0, tk.END)
        if report.all_ok:
            self.compat_results.insert(tk.END, f"All {len(report.results)} parameters this toolkit "
                                                 f"relies on were found on this firmware. No known drift.")
            return
        self.compat_results.insert(tk.END, f"{len(report.missing)} of {len(report.results)} parameters "
                                             f"were NOT found -- these wizard steps may not work correctly:")
        self.compat_results.insert(tk.END, "")
        by_step = {}
        for r in report.missing:
            by_step.setdefault(r.step, []).append(r.name)
        for step, names in by_step.items():
            self.compat_results.insert(tk.END, f"  {step}: missing {', '.join(names)}")
        self.compat_results.insert(tk.END, "")
        self.compat_results.insert(tk.END, "If you hit this, the toolkit's code likely needs updating for "
                                             "your firmware version -- check ardupilot.org's current parameter "
                                             "list for the renamed/replacement name.")
