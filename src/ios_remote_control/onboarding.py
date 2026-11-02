"""Create RemotePairing records from existing trust, and move them between computers."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

from .config import Device


PAIRING_TIMEOUT = 120
# A device on Wi-Fi drops in and out of the list while it sleeps.
DISCOVERY_WAIT = 20
BUNDLE_FORMAT = 1


class SetupError(RuntimeError):
    """Pairing or moving a setup failed in a way the user can act on."""


def current_host_id() -> str:
    """The identity iOS knows this computer by; pymobiledevice3 derives it from the hostname."""
    from pymobiledevice3.pair_records import generate_host_id

    return generate_host_id()


def paired_identifiers() -> list[str]:
    """List the devices that have a RemotePairing record on this computer."""
    from pymobiledevice3.pair_records import iter_remote_pair_records_by_identifier

    return [identifier for identifier, _path, _record in iter_remote_pair_records_by_identifier()]


def has_pair_record(identifier: str) -> bool:
    """Return whether this computer has a RemotePairing record for the device."""
    return identifier in paired_identifiers()


def protect_pair_record(identifier: str) -> None:
    """Restrict a device's RemotePairing record to its owner, because it gives control of the device."""
    from pymobiledevice3.pair_records import iter_remote_pair_records_by_identifier

    for found, path, _record in iter_remote_pair_records_by_identifier():
        if found == identifier:
            path.chmod(0o600)


def failure_reason(stderr: str) -> str:
    """Return the last line of a failed command's error output, which usually names the cause."""
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    return lines[-1][:300] if lines else "no details reported"


async def find_trusted_identifier(requested: str | None = None) -> str:
    """Find a device this computer already trusts, over USB or the local network."""
    from pymobiledevice3.usbmux import list_devices

    found = await list_devices()
    waited = 0
    while waited < DISCOVERY_WAIT and (not found or (requested and requested not in [d.serial for d in found])):
        await asyncio.sleep(2)
        waited += 2
        found = await list_devices()
    devices = list(dict.fromkeys(device.serial for device in found))
    if requested:
        if requested not in devices:
            raise SetupError(f"device {requested!r} is not visible to this computer")
        return requested
    if not devices:
        raise SetupError(
            "no trusted iPhone or iPad found; pair it with this computer in Xcode (Window > Devices and Simulators) "
            "or connect it by USB, then unlock it"
        )
    usb = list(dict.fromkeys(device.serial for device in found if device.is_usb))
    if len(usb) == 1:
        return usb[0]
    if len(devices) > 1:
        raise SetupError(f"multiple devices found; choose one with --udid: {', '.join(devices)}")
    return devices[0]


def export_bundle(device: Device, output: Path) -> None:
    """Write everything another computer needs to control this device. The file is a credential."""
    from pymobiledevice3.pair_records import iter_remote_pair_records_by_identifier

    record = next((path for found, path, _ in iter_remote_pair_records_by_identifier() if found == device.identifier), None)
    if record is None:
        raise SetupError(f"no RemotePairing record for {device.name!r}; run `ios-remote setup` first")
    payload = {
        "format": BUNDLE_FORMAT,
        "name": device.name,
        "host": device.host,
        "port": device.port,
        "identifier": device.identifier,
        "host_id": device.host_id or current_host_id(),
        "record": base64.b64encode(record.read_bytes()).decode(),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as bundle:
        json.dump(payload, bundle)
    output.chmod(0o600)


def import_bundle(source: Path, host: str | None = None, force: bool = False) -> Device:
    """Install a bundle from `export_bundle` and return the device it describes."""
    from pymobiledevice3.common import get_home_folder
    from pymobiledevice3.pair_records import PAIRING_RECORD_EXT, get_remote_pairing_record_filename

    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("format") != BUNDLE_FORMAT:
        raise SetupError(f"{source} is not a bundle this version can read")
    identifier = payload["identifier"]
    record = base64.b64decode(payload["record"])
    target = get_home_folder() / f"{get_remote_pairing_record_filename(identifier)}.{PAIRING_RECORD_EXT}"
    if target.exists() and target.read_bytes() != record and not force:
        raise SetupError(f"this computer already has a different pairing for {identifier}; use --force to replace it")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as stored:
        stored.write(record)
    target.chmod(0o600)
    return Device(payload["name"], host or payload["host"], identifier, payload["port"], payload["host_id"])


def bootstrap_remote_pairing(identifier: str) -> None:
    """Create a RemotePairing record over the trusted lockdown channel. This cannot create the first trust."""
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
            f"RemotePairing timed out after {PAIRING_TIMEOUT}s. Unlock the device, accept Trust if prompted, and retry."
        ) from None
    if completed.returncode:
        raise SetupError(
            "RemotePairing failed. Unlock the device, accept Trust if prompted, and retry. "
            f"Reason: {failure_reason(completed.stderr)}"
        )
    if not has_pair_record(identifier):
        raise SetupError("pymobiledevice3 completed but did not create a RemotePairing record")
    protect_pair_record(identifier)
