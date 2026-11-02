from __future__ import annotations

import subprocess
import sys
from typing import Any


PAIRING_TIMEOUT = 120


class SetupError(RuntimeError):
    pass


def paired_identifiers() -> list[str]:
    from pymobiledevice3.pair_records import iter_remote_pair_records_by_identifier

    return [identifier for identifier, _path, _record in iter_remote_pair_records_by_identifier()]


def has_pair_record(identifier: str) -> bool:
    return identifier in paired_identifiers()


def protect_pair_record(identifier: str) -> None:
    from pymobiledevice3.pair_records import iter_remote_pair_records_by_identifier

    for found, path, _record in iter_remote_pair_records_by_identifier():
        if found == identifier:
            path.chmod(0o600)


def failure_reason(stderr: str) -> str:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    return lines[-1][:300] if lines else "no details reported"


async def find_usb_identifier(requested: str | None = None) -> str:
    from pymobiledevice3.usbmux import list_devices

    devices = [device.serial for device in await list_devices() if device.is_usb]
    if requested:
        if requested not in devices:
            raise SetupError(f"USB device {requested!r} is not connected")
        return requested
    if not devices:
        raise SetupError("no USB iPhone or iPad found; connect and unlock the device first")
    if len(devices) > 1:
        raise SetupError("multiple USB devices found; choose one with --udid")
    return devices[0]


def bootstrap_remote_pairing(identifier: str) -> None:
    command = [
        sys.executable,
        "-m",
        "pymobiledevice3",
        "lockdown",
        "remotepairing",
        "--pair",
        "--udid",
        identifier,
    ]
    try:
        completed = subprocess.run(command, check=False, text=True, capture_output=True, timeout=PAIRING_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise SetupError(
            f"USB RemotePairing timed out after {PAIRING_TIMEOUT}s. Unlock the device, accept Trust if prompted, and retry."
        ) from None
    if completed.returncode:
        raise SetupError(
            "USB RemotePairing failed. Unlock the device, accept Trust if prompted, and retry. "
            f"Reason: {failure_reason(completed.stderr)}"
        )
    if not has_pair_record(identifier):
        raise SetupError("pymobiledevice3 completed but did not create a RemotePairing record")
    protect_pair_record(identifier)
