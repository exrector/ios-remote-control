"""Command-line interface. Each command prints one JSON object and exits with 0 on success."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from .config import Device, load_devices, save_devices, validate_port
from .device import PairingRequiredError, RemoteDevice, run
from .onboarding import (
    SetupError,
    bootstrap_remote_pairing,
    current_host_id,
    export_bundle,
    find_trusted_identifier,
    import_bundle,
    paired_identifiers,
)


UNLOCK_WARNING = """
DANGER ZONE: this enters the passcode of {device!r} once.
- Anyone watching the device or its screen can see what it does.
- Repeated wrong passcodes disable the device, so this never retries.
- The passcode is not stored, logged, or printed.
"""


def emit(payload: dict[str, Any]) -> None:
    """Print one JSON object on one line. Every command reports its result this way."""
    print(json.dumps(payload, ensure_ascii=False))


def error_message(error: Exception) -> str:
    """Return a non-empty explanation of an error, since some exceptions carry no text."""
    if isinstance(error, TimeoutError):
        return str(error) or "connection timed out; the device may be asleep, offline, or unreachable"
    return str(error) or "device operation failed"


def selected_device(name: str) -> Device:
    """Return a saved device by alias, or raise ValueError listing the aliases that exist."""
    devices = load_devices()
    try:
        return devices[name]
    except KeyError as error:
        choices = ", ".join(sorted(devices)) or "none configured"
        raise ValueError(f"unknown device {name!r}; configured: {choices}") from error


def add_device(args: argparse.Namespace) -> None:
    """Handle `add`: save an alias for a device whose RemotePairing record already exists."""
    validate_port(args.port)
    devices = load_devices()
    devices[args.name] = Device(args.name, args.host, args.identifier, args.port, args.host_id or current_host_id())
    save_devices(devices)
    emit({"status": "saved", "device": args.name, "host": args.host, "port": args.port})


def set_host(args: argparse.Namespace) -> None:
    """Handle `set-host`: change a saved device's address, such as to its Tailscale name."""
    devices = load_devices()
    device = selected_device(args.name)
    devices[args.name] = replace(device, host=args.host)
    save_devices(devices)
    emit({"status": "saved", "device": args.name, "host": args.host})


def export_device(args: argparse.Namespace) -> None:
    """Handle `export`: write a device's pairing and settings to a file for another computer."""
    output = Path(args.output).expanduser().resolve()
    export_bundle(selected_device(args.name), output)
    emit({"status": "exported", "device": args.name, "path": str(output), "warning": "this file gives control of the device"})


def import_device(args: argparse.Namespace) -> None:
    """Handle `import`: install a file made by `export` and save the device under an alias."""
    device = import_bundle(Path(args.path).expanduser(), args.host, args.force)
    devices = load_devices()
    if args.name:
        device = replace(device, name=args.name)
    devices[device.name] = device
    save_devices(devices)
    emit({"status": "imported", "device": device.name, "host": device.host, "port": device.port})


def remove_device(args: argparse.Namespace) -> None:
    """Handle `remove`: delete an alias. The RemotePairing record stays on disk."""
    devices = load_devices()
    if args.name not in devices:
        raise ValueError(f"unknown device {args.name!r}")
    del devices[args.name]
    save_devices(devices)
    emit({"status": "removed", "device": args.name})


def list_devices(_: argparse.Namespace) -> None:
    """Handle `list`: report every saved device alias."""
    emit({
        "devices": [
            {
                "name": device.name,
                "host": device.host,
                "port": device.port,
                "identifier": device.identifier,
                "host_id": device.host_id,
            }
            for device in load_devices().values()
        ]
    })


def list_pairs(_: argparse.Namespace) -> None:
    """Handle `list-pairs`: report the devices that have a RemotePairing record on this computer."""
    emit({"identifiers": paired_identifiers()})


def pair_device(args: argparse.Namespace) -> None:
    """Handle `pair`: create a RemotePairing record for a device this computer already trusts."""
    identifier = run(find_trusted_identifier(args.udid))
    bootstrap_remote_pairing(identifier)
    emit({"status": "paired", "identifier": identifier})


def setup(args: argparse.Namespace) -> None:
    """Handle `setup`: create the record, save the alias, and check the connection unless told not to."""
    validate_port(args.port)
    identifier = run(find_trusted_identifier(args.udid))
    bootstrap_remote_pairing(identifier)
    devices = load_devices()
    device = Device(args.name, args.host, identifier, args.port, current_host_id())
    devices[args.name] = device
    save_devices(devices)
    result: dict[str, Any] = {
        "status": "configured",
        "device": args.name,
        "host": args.host,
        "port": args.port,
        "identifier": identifier,
    }
    if not args.skip_verify:
        result["connection"] = run(RemoteDevice(device).info())
    emit(result)


def doctor(args: argparse.Namespace) -> None:
    """Handle `doctor`: report configuration, pairing, and connectivity. Exit with 1 unless ready."""
    device = selected_device(args.device)
    paired = device.identifier in paired_identifiers()
    result: dict[str, Any] = {
        "device": device.name,
        "configured": True,
        "paired": paired,
        "host": device.host,
        "port": device.port,
    }
    if not paired:
        result["status"] = "needs_pairing"
        result["next"] = f"ios-remote setup {device.name} --host {device.host}"
        emit(result)
        raise SystemExit(1)
    try:
        result["connection"] = run(RemoteDevice(device).info())
        result["status"] = "ready"
    except Exception as error:
        result["status"] = "unreachable"
        result["error_type"] = type(error).__name__
        result["error"] = error_message(error)
        emit(result)
        raise SystemExit(1) from error
    emit(result)


def info(args: argparse.Namespace) -> None:
    """Handle `info`: connect and report device, orientation, backlight, and passcode state."""
    emit(run(RemoteDevice(selected_device(args.device)).info()))


def screenshot(args: argparse.Namespace) -> None:
    """Handle `screenshot`: save the current screen as a PNG and report its size."""
    output = Path(args.output).expanduser().resolve()
    width, height = run(RemoteDevice(selected_device(args.device)).screenshot(output))
    emit({"status": "saved", "path": str(output), "width": width, "height": height})


def launch(args: argparse.Namespace) -> None:
    """Handle `launch`: open an app by bundle identifier."""
    run(RemoteDevice(selected_device(args.device)).launch(args.bundle_id))
    emit({"status": "launched", "bundle_id": args.bundle_id})


def home(args: argparse.Namespace) -> None:
    """Handle `home`: press the Home button."""
    run(RemoteDevice(selected_device(args.device)).home())
    emit({"status": "pressed", "button": "home"})


def unlock(args: argparse.Namespace) -> None:
    """Handle `unlock`: a person types the passcode at a hidden prompt, and it goes no further than the device."""
    if not sys.stdin.isatty():
        raise ValueError("unlock needs a person at a terminal; the passcode cannot come from a program or an agent")
    print(UNLOCK_WARNING.format(device=args.device), file=sys.stderr)
    print("Type UNLOCK to continue: ", end="", file=sys.stderr, flush=True)
    if input().strip() != "UNLOCK":
        raise ValueError("not confirmed; nothing was sent to the device")
    outcome = run(RemoteDevice(selected_device(args.device)).unlock(getpass.getpass("Passcode (hidden): ").strip()))
    emit({"status": outcome, "device": args.device})


def tap(args: argparse.Namespace) -> None:
    """Handle `tap`: touch one point given in screenshot pixels."""
    width, height = run(RemoteDevice(selected_device(args.device)).tap(args.x, args.y, args.hold))
    emit({"status": "tapped", "x": args.x, "y": args.y, "screen": [width, height]})


def swipe(args: argparse.Namespace) -> None:
    """Handle `swipe`: drag one finger between two points given in screenshot pixels."""
    width, height = run(
        RemoteDevice(selected_device(args.device)).swipe(
            args.x1, args.y1, args.x2, args.y2, args.duration, args.steps
        )
    )
    emit({
        "status": "swiped",
        "from": [args.x1, args.y1],
        "to": [args.x2, args.y2],
        "screen": [width, height],
    })


def parser() -> argparse.ArgumentParser:
    """Build the command-line parser, with help text for every command and argument."""
    root = argparse.ArgumentParser(
        prog="ios-remote",
        description="Control a paired physical iPhone or iPad over a routable IP address.",
    )
    commands = root.add_subparsers(dest="command", required=True)

    pair = commands.add_parser(
        "pair", aliases=["pair-usb"], help="create a RemotePairing record through an already trusted connection"
    )
    pair.add_argument("--udid", help="device to pair; required only when several devices are visible")
    pair.set_defaults(handler=pair_device)

    setup_command = commands.add_parser(
        "setup", help="pair one trusted device, save its remote host, and verify the complete connection"
    )
    setup_command.add_argument("name", help="local alias for the device")
    setup_command.add_argument("--host", required=True, help="Tailscale name, IP address, or other routable host")
    setup_command.add_argument("--port", type=int, default=49152, help="RemotePairing TCP port on the device")
    setup_command.add_argument("--udid", help="required only when several devices are visible")
    setup_command.add_argument("--skip-verify", action="store_true", help="do not connect to the device after saving it")
    setup_command.set_defaults(handler=setup)

    pairs = commands.add_parser("list-pairs", help="list locally stored RemotePairing identifiers")
    pairs.set_defaults(handler=list_pairs)

    add = commands.add_parser("add", help="save a device alias locally")
    add.add_argument("name", help="local alias for the device")
    add.add_argument("--host", required=True, help="Tailscale name, IP address, or other routable host")
    add.add_argument("--identifier", required=True, help="RemotePairing identifier, normally the device UDID")
    add.add_argument("--port", type=int, default=49152, help="RemotePairing TCP port on the device")
    add.add_argument("--host-id", help="identity the pairing was made with; defaults to this computer's")
    add.set_defaults(handler=add_device)

    host = commands.add_parser("set-host", help="change the address of a saved device, such as to its Tailscale name")
    host.add_argument("name", help="saved device alias")
    host.add_argument("host", help="new Tailscale name, IP address, or other routable host")
    host.set_defaults(handler=set_host)

    export = commands.add_parser("export", help="save a device's pairing and settings to a file for another computer")
    export.add_argument("name", help="saved device alias")
    export.add_argument("output", help="file to write; it gives control of the device, so keep it private")
    export.set_defaults(handler=export_device)

    import_command = commands.add_parser("import", help="install a file made by export")
    import_command.add_argument("path", help="file made by export")
    import_command.add_argument("--name", help="save under this alias instead of the original one")
    import_command.add_argument("--host", help="reach the device at this address, such as its Tailscale name")
    import_command.add_argument("--force", action="store_true", help="replace a different pairing for this device")
    import_command.set_defaults(handler=import_device)

    listing = commands.add_parser("list", help="list configured device aliases")
    listing.set_defaults(handler=list_devices)

    remove = commands.add_parser("remove", help="remove a device alias; pairing records are left untouched")
    remove.add_argument("name", help="saved device alias")
    remove.set_defaults(handler=remove_device)

    doctor_command = commands.add_parser("doctor", help="check configuration, pairing, and connectivity")
    doctor_command.add_argument("--device", required=True, help="saved device alias")
    doctor_command.set_defaults(handler=doctor)

    for command_name, handler, help_text in [
        ("info", info, "show device information"),
        ("screenshot", screenshot, "capture the current screen"),
        ("launch", launch, "launch an application by bundle identifier"),
        ("home", home, "press the Home button"),
        ("unlock", unlock, "DANGER ZONE: a person types the passcode at a hidden prompt, and it is entered once"),
        ("tap", tap, "tap screenshot pixel coordinates"),
        ("swipe", swipe, "swipe between screenshot pixel coordinates"),
    ]:
        command = commands.add_parser(command_name, help=help_text)
        command.add_argument("--device", required=True, help="saved device alias")
        command.set_defaults(handler=handler)
        if command_name == "screenshot":
            command.add_argument("output", help="PNG file to write; missing folders are created")
        elif command_name == "launch":
            command.add_argument("bundle_id", help="app bundle identifier, such as com.apple.mobiletimer")
        elif command_name == "tap":
            command.add_argument("x", type=float, help="pixels from the left of the screenshot")
            command.add_argument("y", type=float, help="pixels from the top of the screenshot")
            command.add_argument("--hold", type=float, default=0.08, help="seconds to keep the finger down")
        elif command_name == "swipe":
            command.add_argument("x1", type=float, help="start, pixels from the left of the screenshot")
            command.add_argument("y1", type=float, help="start, pixels from the top of the screenshot")
            command.add_argument("x2", type=float, help="end, pixels from the left of the screenshot")
            command.add_argument("y2", type=float, help="end, pixels from the top of the screenshot")
            command.add_argument("--duration", type=float, default=0.6, help="seconds the swipe takes; must be positive")
            command.add_argument("--steps", type=int, default=30, help="touch updates sent along the path; at least 1")
    return root


def main() -> None:
    """Run one command. Known failures print a JSON error and exit with 1."""
    args = parser().parse_args()
    try:
        args.handler(args)
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except (ConnectionError, OSError, PairingRequiredError, SetupError, TimeoutError, ValueError) as error:
        emit({"status": "error", "error": error_message(error), "type": type(error).__name__})
        raise SystemExit(1) from error
    except Exception as error:
        from pymobiledevice3.exceptions import PyMobileDevice3Exception

        if not isinstance(error, PyMobileDevice3Exception):
            raise
        emit({"status": "error", "error": error_message(error), "type": type(error).__name__})
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
