"""
Safety-gated pymavlink connection helper for ArduPilot configuration work.

Core rule encoded here: any destructive or state-changing operation (a
reboot, a motor test, a param write that affects motor/servo output) must
pass through require_disarmed() first. This is a hard precondition in code,
not a prompt reminder -- callers cannot skip it without explicitly bypassing
the check.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from pymavlink import mavutil


class SafetyError(RuntimeError):
    """Raised when an operation is refused because a safety precondition failed."""


@dataclass
class FCConnection:
    """Wraps a pymavlink connection with the patterns that mattered in
    practice: armed-check gating, heartbeat wait, and a reboot-and-reconnect
    helper that actually waits for the FC to come back before returning.
    """
    master: "mavutil.mavlink_connection"
    device: str
    baud: int

    @classmethod
    def connect(cls, device: str, baud: int = 115200, heartbeat_timeout: int = 30) -> "FCConnection":
        """Open a direct MAVLink connection (e.g. device='COM6' on Windows,
        '/dev/ttyACM0' on Linux/macOS) and block until a heartbeat is seen.

        Connecting directly via pymavlink -- not just through the GCS -- lets
        you script parameter/motor-test work independently of Mission
        Planner. The FC is powered over USB independent of the flight
        battery, so parameter work doesn't require props-on power. That does
        NOT mean it's risk-free: always treat the vehicle as if it could
        arm, and route destructive actions through require_disarmed().
        """
        master = mavutil.mavlink_connection(device, baud=baud)
        print(f"Waiting for heartbeat on {device} @ {baud}...")
        master.wait_heartbeat(timeout=heartbeat_timeout)
        print(
            f"Heartbeat received (system {master.target_system}, "
            f"component {master.target_component})"
        )
        return cls(master=master, device=device, baud=baud)

    def is_armed(self) -> bool:
        """Check the live HEARTBEAT.base_mode for MAV_MODE_FLAG_SAFETY_ARMED.
        Always re-check right before a destructive action rather than
        caching a prior result -- state can change between calls.
        """
        hb = self.master.recv_match(type="HEARTBEAT", blocking=True, timeout=5)
        if hb is None:
            raise SafetyError("No HEARTBEAT received; cannot verify armed state. Refusing to proceed.")
        return bool(hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)

    def require_disarmed(self) -> None:
        """Hard precondition gate. Call immediately before any reboot, motor
        test, or param write that affects motor/servo behavior. Raises
        SafetyError -- never silently proceeds -- if the vehicle is armed.
        """
        if self.is_armed():
            raise SafetyError(
                "Vehicle is ARMED. Refusing to proceed with a destructive/"
                "state-changing operation. Disarm the vehicle first."
            )

    def reboot_and_wait(self, timeout: int = 60) -> None:
        """Send MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN and block until the FC is
        back and answering heartbeats again.

        IMPORTANT (Windows/USB): rebooting the FC over a USB-CDC serial link
        very commonly makes Windows tear down and re-enumerate the COM
        port. The old pyserial handle becomes invalid at that point --
        continuing to read/write it raises repeated
        "ClearCommError failed (PermissionError...)" errors instead of a
        clean timeout. So after sending the reboot command, this closes the
        old connection outright and opens a *fresh* one on the same
        device/baud, retrying with a short backoff since the COM port can
        take several seconds to disappear and reappear in Windows. This is
        safer than trying to keep reusing the pre-reboot handle.
        """
        self.require_disarmed()
        self.master.mav.command_long_send(
            self.master.target_system,
            self.master.target_component,
            mavutil.mavlink.MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN,
            0,
            1, 0, 0, 0, 0, 0, 0,
        )
        print("Reboot command sent. Closing this connection and waiting for the FC to come back...")
        try:
            self.master.close()
        except Exception:
            pass  # the port may already be gone -- that's expected here

        time.sleep(3)  # let the FC actually go down and the USB device drop first

        deadline = time.time() + timeout
        last_error: Exception | None = None
        while time.time() < deadline:
            try:
                new_master = mavutil.mavlink_connection(self.device, baud=self.baud)
                new_master.wait_heartbeat(timeout=5)
                self.master = new_master
                print(f"FC back online after reboot (reconnected to {self.device}).")
                return
            except Exception as e:  # noqa: BLE001 - COM port may not exist yet, or may still be enumerating
                last_error = e
                time.sleep(1)

        raise TimeoutError(
            f"Could not reconnect to {self.device} within {timeout}s after reboot. "
            f"The COM port may have changed number after re-enumerating -- check Device "
            f"Manager and reconnect manually if needed. Last error: {last_error}"
        )

    def close(self) -> None:
        self.master.close()
