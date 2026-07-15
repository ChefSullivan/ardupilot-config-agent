"""
ardupilot_gui_core.py

Core shell for the ArduPilot desktop GUI: background worker thread, top
connection bar, notebook host, standalone tool tabs (Parameters, Motor
Map, Failsafe), log panel, and shared plumbing. The Setup Wizard tab lives
in ardupilot_gui_wizard.py as a mixin -- split out purely to keep each
source file a manageable size, not for any architectural reason.

See ardupilot_gui.py for the entry point that combines the pieces.
"""
from __future__ import annotations

import contextlib
import io
import queue
import threading
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import ttk, messagebox
from typing import Any, Callable, List, Optional

from ardupilot_agent.connection import FCConnection, SafetyError
from ardupilot_agent.params import (
    fetch_all_params,
    search_params,
    get_param,
    set_param,
    set_param_and_verify_after_reboot,
)
from ardupilot_agent.motor_test import MotorMapEntry
from ardupilot_agent.param_help import describe_param_full, COMMON_SEARCHES
from ardupilot_gui_theme import apply_dark, apply_light, DARK, LIGHT, retheme_tk_widget

STANDARD_QUAD_CORNERS = ["front-right", "rear-left", "front-left", "rear-right"]


# ---------------------------------------------------------------------------
# Background worker: serializes all pymavlink access onto one thread so the
# GUI never has two things talking over the serial port at once.
# ---------------------------------------------------------------------------

@dataclass
class Job:
    func: Callable
    args: tuple
    kwargs: dict
    on_done: Callable[[Any], None] = field(default=lambda r: None)
    on_error: Callable[[Exception], None] = field(default=lambda e: None)


class Worker:
    def __init__(self):
        self.jobs: "queue.Queue[Job]" = queue.Queue()
        self.results: "queue.Queue[tuple]" = queue.Queue()
        self.conn: Optional[FCConnection] = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def submit(self, func, *args, on_done=None, on_error=None, **kwargs):
        self.jobs.put(Job(
            func=func, args=args, kwargs=kwargs,
            on_done=on_done or (lambda r: None),
            on_error=on_error or (lambda e: None),
        ))

    def _run(self):
        while True:
            job = self.jobs.get()
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    result = job.func(*job.args, **job.kwargs)
                self.results.put(("log", buf.getvalue()))
                self.results.put(("done", job.on_done, result))
            except SafetyError as e:
                self.results.put(("log", buf.getvalue()))
                self.results.put(("safety_error", job.on_error, e))
            except Exception as e:  # noqa: BLE001 - surface everything to the GUI, don't crash the worker
                self.results.put(("log", buf.getvalue()))
                self.results.put(("error", job.on_error, e))


class ArduPilotGUICore:
    """Base class: connection bar, notebook host, standalone tabs, log
    panel, shared plumbing. Subclassed (via mixin) by the final ArduPilotGUI
    in ardupilot_gui.py, which adds the Setup Wizard tab.
    """

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("ArduPilot Config Agent")
        self.root.geometry("980x760")
        self.change_log: List[str] = []
        self._dark_widgets: List[tuple] = []
        self.theme_mode = "dark"
        try:
            apply_dark(self.root)
        except Exception as e:  # noqa: BLE001 - never let a theming issue block the app from launching
            print(f"WARNING: could not apply theme at startup ({e}); continuing with default Tk styling.")

        self.worker = Worker()
        self.motor_entries: List[MotorMapEntry] = []
        self.motor_index = 1
        self.motor_count = 4
        self.motor_throttle = 20
        self.motor_frame_key = ""

        self._init_wizard_state()

        self._build_top_bar()
        self._build_notebook()
        self._build_log()

        self.root.after(100, self._poll_results)
        self._start_wizard_polling()
        self._refresh_ports()

    def _init_wizard_state(self):
        """Overridden by the WizardMixin; no-op here so this class works
        standalone if the wizard mixin isn't present.
        """
        pass

    def _start_wizard_polling(self):
        pass

    def _wizard_refresh_current_step(self):
        """Overridden by WizardNavMixin; no-op here so this class works
        standalone if the wizard mixin isn't present.
        """
        pass

    # -- top connection bar -------------------------------------------------

    def _build_top_bar(self):
        title_bar = ttk.Frame(self.root, padding=(10, 8, 10, 0))
        title_bar.pack(fill="x")
        ttk.Label(title_bar, text="ArduPilot Config Agent", style="Title.TLabel").pack(side="left")

        bar = ttk.Frame(self.root, padding=8)
        bar.pack(fill="x")

        ttk.Label(bar, text="Device:").pack(side="left")
        self.device_var = tk.StringVar()
        self.device_combo = ttk.Combobox(bar, textvariable=self.device_var, width=28)
        self.device_combo.pack(side="left", padx=4)

        ttk.Button(bar, text="Refresh Ports", command=self._refresh_ports).pack(side="left", padx=4)

        ttk.Label(bar, text="Baud:").pack(side="left", padx=(12, 0))
        self.baud_var = tk.StringVar(value="115200")
        ttk.Combobox(bar, textvariable=self.baud_var, width=10,
                     values=["57600", "115200", "921600"]).pack(side="left", padx=4)

        self.connect_btn = ttk.Button(bar, text="Connect", command=self._connect, style="Accent.TButton")
        self.connect_btn.pack(side="left", padx=(12, 4))

        self.status_var = tk.StringVar(value="DISCONNECTED")
        self.status_label = ttk.Label(bar, textvariable=self.status_var, width=28,
                                       anchor="center", relief="sunken", padding=4)
        self.status_label.pack(side="left", padx=8)
        self._set_status("DISCONNECTED", "#888888")

        self.theme_btn = ttk.Button(bar, text="Light Mode", command=self._toggle_theme)
        self.theme_btn.pack(side="right", padx=4)

    def _toggle_theme(self):
        if self.theme_mode == "dark":
            apply_light(self.root)
            self.theme_mode = "light"
            self.theme_btn.configure(text="Dark Mode")
            palette = LIGHT
        else:
            apply_dark(self.root)
            self.theme_mode = "dark"
            self.theme_btn.configure(text="Light Mode")
            palette = DARK
        for widget, kind in list(self._dark_widgets):
            retheme_tk_widget(widget, palette, kind)

    def _refresh_ports(self):
        try:
            from serial.tools import list_ports
            ports = [p.device for p in list_ports.comports()]
        except Exception:
            ports = []
        self.device_combo["values"] = ports
        if ports and not self.device_var.get():
            self.device_var.set(ports[0])

    def _set_status(self, text: str, color: str):
        self.status_var.set(text)
        self.status_label.configure(background=color)

    def _connect(self):
        device = self.device_var.get().strip()
        if not device:
            messagebox.showwarning("No device", "Pick or type a serial device/COM port first.")
            return
        baud = int(self.baud_var.get())
        self.connect_btn.configure(state="disabled")
        self._set_status("CONNECTING...", "#e0c341")
        self.worker.submit(
            FCConnection.connect, device, baud=baud,
            on_done=self._on_connected, on_error=self._on_connect_error,
        )

    def _on_connected(self, conn: FCConnection):
        self.worker.conn = conn
        self.connect_btn.configure(text="Reconnect", state="normal")
        self._log(f"Connected to {conn.device} @ {conn.baud}\n")
        self._poll_armed()
        self._wizard_refresh_current_step()

    def _on_connect_error(self, e: Exception):
        self.connect_btn.configure(state="normal")
        self._set_status("CONNECT FAILED", "#c0392b")
        device = self.device_var.get().strip()
        baud = self.baud_var.get()
        messagebox.showerror(
            "Connection failed",
            f"Could not connect to {device} @ {baud} baud.\n\n"
            f"{type(e).__name__}: {e}\n\n"
            "Common causes: wrong COM port selected (click Refresh Ports and re-check Device "
            "Manager -- the port number can change after a reboot or replug), the port is "
            "already open in another program (Mission Planner, a previous run of this tool), "
            "or the FC isn't powered/enumerated yet.",
        )

    def _poll_armed(self):
        if self.worker.conn is not None:
            self.worker.submit(self.worker.conn.is_armed, on_done=self._on_armed_result, on_error=self._on_armed_error)
        self.root.after(4000, self._poll_armed)

    def _on_armed_result(self, armed: bool):
        if armed:
            self._set_status("CONNECTED - ARMED (locked)", "#c0392b")
        else:
            self._set_status("CONNECTED - disarmed", "#2e8b57")

    def _on_armed_error(self, e: Exception):
        self._set_status("CONNECTION LOST", "#c0392b")

    # -- notebook -------------------------------------------------------

    def _build_notebook(self):
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        self.notebook = nb
        self._build_wizard_tab_if_present(nb)
        self._build_params_tab(nb)
        self._build_motor_tab(nb)
        self._build_failsafe_tab(nb)
        self._build_compat_tab_if_present(nb)
        nb.select(0)

    def _build_compat_tab_if_present(self, nb):
        """Overridden by CompatibilityTabMixin. No-op here."""
        pass

    def _open_compat_tab(self):
        """Overridden by CompatibilityTabMixin. No-op here."""
        pass

    def _build_wizard_tab_if_present(self, nb):
        """Overridden by the WizardMixin. No-op here."""
        pass

    # -- Parameters tab ---------------------------------------------------

    def _build_params_tab(self, nb):
        tab = ttk.Frame(nb, padding=8)
        nb.add(tab, text="Parameters")

        ttk.Label(tab, text=(
            "Raw ArduPilot parameters -- for first-time setup, the Setup Wizard tab covers the "
            "common ones with plain-language explanations. Type or select any parameter here and "
            "the line below decodes its subsystem prefix (EKF, SERIAL, RNGFND, etc.) into plain "
            "English, even for parameters this toolkit doesn't have a specific description for."
        ), wraplength=880, justify="left", style="Muted.TLabel").pack(anchor="w", pady=(0, 6))

        search_row = ttk.Frame(tab)
        search_row.pack(fill="x", pady=4)
        ttk.Label(search_row, text="Search (substring):").pack(side="left")
        self.search_var = tk.StringVar()
        ttk.Entry(search_row, textvariable=self.search_var, width=25).pack(side="left", padx=4)
        ttk.Button(search_row, text="Search", command=self._do_search).pack(side="left")
        ttk.Label(search_row, text="Common:").pack(side="left", padx=(16, 4))
        common_var = tk.StringVar()
        common_combo = ttk.Combobox(search_row, textvariable=common_var, width=18, state="readonly",
                                     values=COMMON_SEARCHES)
        common_combo.pack(side="left")

        def use_common(_e=None):
            self.search_var.set(common_var.get())
            self._do_search()

        common_combo.bind("<<ComboboxSelected>>", use_common)

        self.search_results = tk.Listbox(tab, height=10)
        self.search_results.pack(fill="both", expand=True, pady=4)
        self.search_results.bind("<<ListboxSelect>>", self._on_result_selected)
        self._register_dark_widget(self.search_results, "listbox")

        edit_row = ttk.Frame(tab)
        edit_row.pack(fill="x", pady=8)
        ttk.Label(edit_row, text="Param name:").grid(row=0, column=0, sticky="w")
        self.param_name_var = tk.StringVar()
        name_entry = ttk.Entry(edit_row, textvariable=self.param_name_var, width=25)
        name_entry.grid(row=0, column=1, padx=4)
        ttk.Button(edit_row, text="Get", command=self._do_get).grid(row=0, column=2, padx=4)

        ttk.Label(edit_row, text="New value:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.param_value_var = tk.StringVar()
        ttk.Entry(edit_row, textvariable=self.param_value_var, width=25).grid(row=1, column=1, padx=4, pady=(6, 0))
        self.reboot_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(edit_row, text="apply-after-reboot pattern", variable=self.reboot_var).grid(
            row=1, column=2, padx=4, pady=(6, 0), sticky="w"
        )
        ttk.Button(edit_row, text="Set", command=self._do_set, style="Accent.TButton").grid(
            row=1, column=3, padx=4, pady=(6, 0))

        self.param_desc_var = tk.StringVar(value="")
        ttk.Label(tab, textvariable=self.param_desc_var, wraplength=880, justify="left",
                  foreground="#4f8cff").pack(anchor="w", pady=(4, 0))
        name_entry.bind("<KeyRelease>", lambda e: self.param_desc_var.set(describe_param_full(self.param_name_var.get())))

    def _do_search(self):
        if not self._require_conn():
            return
        self.worker.submit(fetch_all_params, self.worker.conn, on_done=self._on_search_fetched, on_error=self._on_job_error)

    def _on_search_fetched(self, all_params):
        matches = search_params(all_params, self.search_var.get())
        self.search_results.delete(0, tk.END)
        for name, value in sorted(matches.items()):
            self.search_results.insert(tk.END, f"{name} = {value}")
        if not matches:
            self.search_results.insert(tk.END, "(no matches -- check spelling/instance suffix)")

    def _on_result_selected(self, _event):
        sel = self.search_results.curselection()
        if not sel:
            return
        text = self.search_results.get(sel[0])
        if " = " in text:
            name = text.split(" = ")[0]
            self.param_name_var.set(name)
            self.param_desc_var.set(describe_param_full(name))

    def _do_get(self):
        if not self._require_conn():
            return
        name = self.param_name_var.get().strip()
        if not name:
            return
        self.worker.submit(get_param, self.worker.conn, name, on_done=self._on_get_result, on_error=self._on_job_error)

    def _on_get_result(self, value):
        self.param_value_var.set(str(value))
        self.param_desc_var.set(describe_param_full(self.param_name_var.get()))
        self._log(f"{self.param_name_var.get()} = {value}\n")

    def _do_set(self):
        if not self._require_conn():
            return
        name = self.param_name_var.get().strip()
        raw_value = self.param_value_var.get().strip()
        if not name or not raw_value:
            return
        try:
            value = float(raw_value)
        except ValueError:
            messagebox.showerror("Invalid value", f"'{raw_value}' is not a number.")
            return
        if not messagebox.askyesno("Confirm parameter write", f"Set {name} = {value}?"):
            return
        if self.reboot_var.get():
            self.worker.submit(
                set_param_and_verify_after_reboot, self.worker.conn, name, value,
                on_done=lambda r: self._record_change(f"{name} = {r} (verified after reboot)"),
                on_error=self._on_job_error,
            )
        else:
            self.worker.submit(
                set_param, self.worker.conn, name, value,
                on_done=lambda r: self._record_change(f"{name} = {r}"),
                on_error=self._on_job_error,
            )
