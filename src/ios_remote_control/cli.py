from __future__ import annotations

import argparse
import json
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


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def error_message(error: Exception) -> str:
    if isinstance(error, TimeoutError):
        return str(error) or "connection timed out; the device may be asleep, offline, or unreachable"
    return str(error) or "device operation failed"


def selected_device(name: str) -> Device:
    devices = load_devices()
    try:
        return devices[name]
    except KeyError as error:
        choices = ", ".join(sorted(devices)) or "none configured"
        raise ValueError(f"unknown device {name!r}; configured: {choices}") from error


def add_device(args: argparse.Namespace) -> None:
    validate_port(args.port)
    devices = load_devices()
    devices[args.name] = Device(args.name, args.host, args.identifier, args.port, args.host_id or current_host_id())
    save_devices(devices)
    emit({"status": "saved", "device": args.name, "host": args.host, "port": args.port})


def set_host(args: argparse.Namespace) -> None:
    devices = load_devices()
    device = selected_device(args.name)
    devices[args.name] = replace(device, host=args.host)
    save_devices(devices)
    emit({"status": "saved", "device": args.name, "host": args.host})


def export_device(args: argparse.Namespace) -> None:
    output = Path(args.output).expanduser().resolve()
    export_bundle(selected_device(args.name), output)
    emit({"status": "exported", "device": args.name, "path": str(output), "warning": "this file gives control of the device"})


def import_device(args: argparse.Namespace) -> None:
    device = import_bundle(Path(args.path).expanduser(), args.host, args.force)
    devices = load_devices()
    if args.name:
        device = replace(device, name=args.name)
    devices[device.name] = device
    save_devices(devices)
    emit({"status": "imported", "device": device.name, "host": device.host, "port": device.port})


def remove_device(args: argparse.Namespace) -> None:
    devices = load_devices()
    if args.name not in devices:
        raise ValueError(f"unknown device {args.name!r}")
    del devices[args.name]
    save_devices(devices)
    emit({"status": "removed", "device": args.name})


def list_devices(_: argparse.Namespace) -> None:
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
    emit({"identifiers": paired_identifiers()})


def pair_device(args: argparse.Namespace) -> None:
    identifier = run(find_trusted_identifier(args.udid))
    bootstrap_remote_pairing(identifier)
    emit({"status": "paired", "identifier": identifier})


def setup(args: argparse.Namespace) -> None:
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
        result["status"] = "needs_usb_pairing"
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
    emit(run(RemoteDevice(selected_device(args.device)).info()))


def screenshot(args: argparse.Namespace) -> None:
    output = Path(args.output).expanduser().resolve()
    width, height = run(RemoteDevice(selected_device(args.device)).screenshot(output))
    emit({"status": "saved", "path": str(output), "width": width, "height": height})


def launch(args: argparse.Namespace) -> None:
    run(RemoteDevice(selected_device(args.device)).launch(args.bundle_id))
    emit({"status": "launched", "bundle_id": args.bundle_id})


def home(args: argparse.Namespace) -> None:
    run(RemoteDevice(selected_device(args.device)).home())
    emit({"status": "pressed", "button": "home"})


def tap(args: argparse.Namespace) -> None:
    width, height = run(RemoteDevice(selected_device(args.device)).tap(args.x, args.y, args.hold))
    emit({"status": "tapped", "x": args.x, "y": args.y, "screen": [width, height]})


def swipe(args: argparse.Namespace) -> None:
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
    root = argparse.ArgumentParser(
        prog="ios-remote",
        description="Control a paired physical iPhone or iPad over a routable IP address.",
    )
    commands = root.add_subparsers(dest="command", required=True)

    pair = commands.add_parser(
        "pair", aliases=["pair-usb"], help="create a RemotePairing record through an already trusted connection"
    )
    pair.add_argument("--udid")
    pair.set_defaults(handler=pair_device)

    setup_command = commands.add_parser(
        "setup", help="pair one trusted device, save its remote host, and verify the complete connection"
    )
    setup_command.add_argument("name", help="local alias for the device")
    setup_command.add_argument("--host", required=True, help="Tailscale name, IP address, or other routable host")
    setup_command.add_argument("--port", type=int, default=49152)
    setup_command.add_argument("--udid", help="required only when several devices are visible")
    setup_command.add_argument("--skip-verify", action="store_true")
    setup_command.set_defaults(handler=setup)

    pairs = commands.add_parser("list-pairs", help="list locally stored RemotePairing identifiers")
    pairs.set_defaults(handler=list_pairs)

    add = commands.add_parser("add", help="save a device alias locally")
    add.add_argument("name")
    add.add_argument("--host", required=True, help="Tailscale name, IP address, or other routable host")
    add.add_argument("--identifier", required=True, help="RemotePairing identifier, normally the device UDID")
    add.add_argument("--port", type=int, default=49152)
    add.add_argument("--host-id", help="identity the pairing was made with; defaults to this computer's")
    add.set_defaults(handler=add_device)

    host = commands.add_parser("set-host", help="change the address of a saved device, such as to its Tailscale name")
    host.add_argument("name")
    host.add_argument("host")
    host.set_defaults(handler=set_host)

    export = commands.add_parser("export", help="save a device's pairing and settings to a file for another computer")
    export.add_argument("name")
    export.add_argument("output")
    export.set_defaults(handler=export_device)

    import_command = commands.add_parser("import", help="install a file made by export")
    import_command.add_argument("path")
    import_command.add_argument("--name", help="save under this alias instead of the original one")
    import_command.add_argument("--host", help="reach the device at this address, such as its Tailscale name")
    import_command.add_argument("--force", action="store_true", help="replace a different pairing for this device")
    import_command.set_defaults(handler=import_device)

    listing = commands.add_parser("list", help="list configured device aliases")
    listing.set_defaults(handler=list_devices)

    remove = commands.add_parser("remove", help="remove a device alias; pairing records are left untouched")
    remove.add_argument("name")
    remove.set_defaults(handler=remove_device)

    doctor_command = commands.add_parser("doctor", help="check configuration, pairing, and connectivity")
    doctor_command.add_argument("--device", required=True, help="saved device alias")
    doctor_command.set_defaults(handler=doctor)

    for command_name, handler, help_text in [
        ("info", info, "show device information"),
        ("screenshot", screenshot, "capture the current screen"),
        ("launch", launch, "launch an application by bundle identifier"),
        ("home", home, "press the Home button"),
        ("tap", tap, "tap screenshot pixel coordinates"),
        ("swipe", swipe, "swipe between screenshot pixel coordinates"),
    ]:
        command = commands.add_parser(command_name, help=help_text)
        command.add_argument("--device", required=True, help="saved device alias")
        command.set_defaults(handler=handler)
        if command_name == "screenshot":
            command.add_argument("output")
        elif command_name == "launch":
            command.add_argument("bundle_id")
        elif command_name == "tap":
            command.add_argument("x", type=float)
            command.add_argument("y", type=float)
            command.add_argument("--hold", type=float, default=0.08)
        elif command_name == "swipe":
            command.add_argument("x1", type=float)
            command.add_argument("y1", type=float)
            command.add_argument("x2", type=float)
            command.add_argument("y2", type=float)
            command.add_argument("--duration", type=float, default=0.6)
            command.add_argument("--steps", type=int, default=30)
    return root


def main() -> None:
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
