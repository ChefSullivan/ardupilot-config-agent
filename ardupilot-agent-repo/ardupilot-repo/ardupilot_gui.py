"""
ardupilot_gui.py

Entry point for the ArduPilot desktop GUI. Run with:

    py ardupilot_gui.py

Uses only the Python standard library (tkinter) -- no extra dependencies
beyond what requirements.txt already installs for the underlying toolkit.

The implementation is split across many small files purely to keep each
source file a manageable size (not for any architectural reason):

  ardupilot_gui_core.py          - worker thread, connection bar, theme
                                    toggle, notebook host, Parameters tab
  ardupilot_gui_tabs2.py         - Motor Map tab, Failsafe tab (standalone)
  ardupilot_gui_tabs3.py         - Compatibility tab (firmware version +
                                    live parameter-existence check)
  ardupilot_gui_shared.py        - log panel, connection guard, result-queue
                                    poller, change-log recorder, dark-widget
                                    theming registry
  ardupilot_gui_theme.py         - light/dark ttk theme
  ardupilot_gui_wizard_nav.py    - Setup Wizard: nav scaffolding + Welcome
  ardupilot_gui_wizard_frame.py  - Setup Wizard: Frame Class Review
  ardupilot_gui_wizard_rc.py     - Setup Wizard: RC Calibration
  ardupilot_gui_wizard_modes.py  - Setup Wizard: Flight Modes
  ardupilot_gui_wizard_motors.py - Setup Wizard: Motor Order & Direction
  ardupilot_gui_wizard_esc.py    - Setup Wizard: ESC Calibration
  ardupilot_gui_wizard_failsafe.py - Setup Wizard: Failsafe
  ardupilot_gui_wizard_arming.py - Setup Wizard: Arming Checks
  ardupilot_gui_wizard_summary.py - Setup Wizard: Summary + change log

Design notes:
- All pymavlink I/O happens on a single background worker thread (see
  Worker in ardupilot_gui_core.py). The GUI never touches the connection
  directly -- it submits jobs to a queue and gets results back via a
  second queue polled on the Tkinter main loop.
- Every destructive action (motor test, param write, reboot, failsafe
  apply) still goes through the same require_disarmed() gate as the CLI --
  this GUI adds convenience, it does not relax any safety check.
- Every wizard step and the Parameters tab record what they actually wrote
  to the FC via self._record_change(...), so the wizard's Summary step can
  show a complete, verifiable list of changes made this session.
"""
from __future__ import annotations

import tkinter as tk

from ardupilot_gui_core import ArduPilotGUICore
from ardupilot_gui_tabs2 import MotorFailsafeTabsMixin
from ardupilot_gui_tabs3 import CompatibilityTabMixin
from ardupilot_gui_shared import SharedPlumbingMixin
from ardupilot_gui_wizard_nav import WizardNavMixin
from ardupilot_gui_wizard_frame import WizardFrameMixin
from ardupilot_gui_wizard_rc import WizardRCMixin
from ardupilot_gui_wizard_modes import WizardModesMixin
from ardupilot_gui_wizard_motors import WizardMotorsMixin
from ardupilot_gui_wizard_esc import WizardEscMixin
from ardupilot_gui_wizard_failsafe import WizardFailsafeMixin
from ardupilot_gui_wizard_arming import WizardArmingMixin
from ardupilot_gui_wizard_summary import WizardSummaryMixin


class ArduPilotGUI(
    WizardNavMixin,
    WizardFrameMixin,
    WizardRCMixin,
    WizardModesMixin,
    WizardMotorsMixin,
    WizardEscMixin,
    WizardFailsafeMixin,
    WizardArmingMixin,
    WizardSummaryMixin,
    MotorFailsafeTabsMixin,
    CompatibilityTabMixin,
    SharedPlumbingMixin,
    ArduPilotGUICore,
):
    """Combines every wizard step, the standalone tabs, shared plumbing,
    and the core shell into the final application class. All the real
    logic lives in the mixins above -- this class body is intentionally
    empty.
    """
    pass


def main():
    root = tk.Tk()
    ArduPilotGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
