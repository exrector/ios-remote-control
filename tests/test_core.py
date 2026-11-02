import json
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import argparse
import ast
import asyncio
import contextlib
import io
import subprocess

import ios_remote_control
from ios_remote_control import cli
from ios_remote_control.config import Device, load_devices, save_devices
from ios_remote_control.device import (
    RemoteDevice,
    pixel_to_hid,
    png_dimensions,
    keypad_point,
    keypad_visible,
    rotation_degrees,
    screen_geometry,
    screen_to_hid,
    validate_passcode,
)
from ios_remote_control.onboarding import (
    SetupError,
    bootstrap_remote_pairing,
    export_bundle,
    find_trusted_identifier,
    import_bundle,
)


class CoordinateTests(unittest.TestCase):
    def test_pixel_to_hid_endpoints(self):
        self.assertEqual(pixel_to_hid(0, 100), 0)
        self.assertEqual(pixel_to_hid(99, 100), 65535)

    def test_pixel_to_hid_rejects_out_of_bounds(self):
        with self.assertRaises(ValueError):
            pixel_to_hid(100, 100)

    def test_png_dimensions(self):
        png_header = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 1536, 2048)
        self.assertEqual(png_dimensions(png_header), (1536, 2048))


class RotationTests(unittest.TestCase):
    # A tap near (6211, 15754) opened the Clock icon drawn at (492, 1389) on a physical iPad at rot270.
    def test_landscape_matches_physical_ipad(self):
        self.assertEqual(screen_to_hid(492, 1389, 2048, 1536, 270), (6233, 15751))

    def test_native_orientation_is_unchanged(self):
        self.assertEqual(screen_to_hid(0, 2047, 1536, 2048, 0), (0, 65535))

    def test_corners_for_each_rotation(self):
        self.assertEqual(screen_to_hid(0, 0, 2048, 1536, 90), (0, 65535))
        self.assertEqual(screen_to_hid(0, 0, 1536, 2048, 180), (65535, 65535))
        self.assertEqual(screen_to_hid(0, 0, 2048, 1536, 270), (65535, 0))

    def test_rejects_rotation_that_contradicts_the_screen(self):
        with self.assertRaisesRegex(ValueError, "rotation 270"):
            screen_to_hid(10, 10, 1536, 2048, 270)
        with self.assertRaisesRegex(ValueError, "rotation 0"):
            screen_to_hid(10, 10, 2048, 1536, 0)

    def geometry(self, orientation):
        return screen_geometry({
            "displays": [
                {"primary": False, "currentMode": {"size": [0.0, 0.0]}, "currentOrientation": "rot0"},
                {
                    "primary": True,
                    "currentMode": {"size": [1536.0, 2048.0]},
                    "currentOrientation": orientation,
                    "nativeOrientation": "rot0",
                },
            ]
        })

    def test_geometry_matches_what_a_screenshot_shows(self):
        self.assertEqual(self.geometry("rot0"), (1536, 2048, 0))
        self.assertEqual(self.geometry("rot180"), (1536, 2048, 180))
        self.assertEqual(self.geometry("rot90"), (2048, 1536, 90))
        self.assertEqual(self.geometry("rot270"), (2048, 1536, 270))

    def test_rotation_comes_from_the_primary_display(self):
        info = {
            "displays": [
                {"primary": False, "currentOrientation": "rot0", "nativeOrientation": "rot0"},
                {"primary": True, "currentOrientation": "rot270", "nativeOrientation": "rot0"},
            ]
        }
        self.assertEqual(rotation_degrees(info), 270)


class CommandValidationTests(unittest.TestCase):
    device = RemoteDevice(Device("tablet", "tablet.example.ts.net", "example-id"))

    def test_rejects_springboard_launch(self):
        with self.assertRaisesRegex(ValueError, "home"):
            asyncio.run(self.device.launch("com.apple.springboard"))

    def test_rejects_swipe_without_movement(self):
        with self.assertRaisesRegex(ValueError, "steps"):
            asyncio.run(self.device.swipe(0, 0, 1, 1, steps=0))
        with self.assertRaisesRegex(ValueError, "duration"):
            asyncio.run(self.device.swipe(0, 0, 1, 1, duration=0))

    def test_rejects_negative_hold(self):
        with self.assertRaisesRegex(ValueError, "hold"):
            asyncio.run(self.device.tap(0, 0, hold=-1))

    def test_invalid_screenshot_is_not_written(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "screen.png"
            with patch.object(RemoteDevice, "screenshot_bytes", AsyncMock(return_value=b"not a png")):
                with self.assertRaises(ValueError):
                    asyncio.run(self.device.screenshot(output))
            self.assertFalse(output.exists())


class CliTests(unittest.TestCase):
    device = Device("tablet", "tablet.example.ts.net", "example-id")

    def run_doctor(self, paired, connection=None):
        output = io.StringIO()
        info = AsyncMock(side_effect=connection) if isinstance(connection, Exception) else AsyncMock(return_value=connection)
        with patch.object(cli, "selected_device", return_value=self.device), \
             patch.object(cli, "paired_identifiers", return_value=["example-id"] if paired else []), \
             patch.object(RemoteDevice, "info", info), \
             contextlib.redirect_stdout(output):
            try:
                cli.doctor(argparse.Namespace(device="tablet"))
                code = 0
            except SystemExit as error:
                code = error.code
        return code, json.loads(output.getvalue())

    def test_doctor_succeeds_only_when_ready(self):
        code, payload = self.run_doctor(True, {"os": "17.7"})
        self.assertEqual((code, payload["status"]), (0, "ready"))

    def test_doctor_fails_when_unreachable(self):
        code, payload = self.run_doctor(True, TimeoutError())
        self.assertEqual((code, payload["status"]), (1, "unreachable"))
        self.assertIn("timed out", payload["error"])

    def test_doctor_fails_when_unpaired(self):
        code, payload = self.run_doctor(False)
        self.assertEqual((code, payload["status"]), (1, "needs_pairing"))

    def test_unknown_alias_is_reported_as_json(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary, \
             patch.dict("os.environ", {"IOS_REMOTE_CONFIG": str(Path(temporary) / "devices.json")}), \
             patch("sys.argv", ["ios-remote", "info", "--device", "missing"]), \
             contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as caught:
                cli.main()
        self.assertEqual(caught.exception.code, 1)
        self.assertIn("unknown device", json.loads(output.getvalue())["error"])

    def test_add_rejects_invalid_port(self):
        arguments = argparse.Namespace(name="tablet", host="host", identifier="id", port=70000, host_id=None)
        with self.assertRaisesRegex(ValueError, "port"):
            cli.add_device(arguments)

    def run_add(self, host_id):
        arguments = argparse.Namespace(name="tablet", host="host", identifier="id", port=49152, host_id=host_id)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "devices.json"
            with patch.dict("os.environ", {"IOS_REMOTE_CONFIG": str(path)}), \
                 patch.object(cli, "current_host_id", return_value="THIS-COMPUTER"), \
                 contextlib.redirect_stdout(io.StringIO()):
                cli.add_device(arguments)
            return load_devices(path)["tablet"].host_id

    def test_add_pins_the_current_identity_by_default(self):
        self.assertEqual(self.run_add(None), "THIS-COMPUTER")

    def test_add_accepts_an_explicit_identity(self):
        self.assertEqual(self.run_add("OTHER-COMPUTER"), "OTHER-COMPUTER")


class BundleTests(unittest.TestCase):
    device = Device("tablet", "tablet.local", "example-id", 49152, "SAVED-IDENTITY")

    def in_home(self, home):
        return patch("pymobiledevice3.common.get_home_folder", return_value=Path(home))

    def export_from(self, home, output, record=b"secret-record"):
        path = Path(home) / "remote_example-id.plist"
        path.write_bytes(record)
        with patch("pymobiledevice3.pair_records.iter_remote_pair_records_by_identifier", return_value=[("example-id", path, {})]):
            export_bundle(self.device, output)

    def test_round_trip_moves_pairing_and_identity(self):
        with tempfile.TemporaryDirectory() as old, tempfile.TemporaryDirectory() as new:
            bundle = Path(old) / "bundle.json"
            self.export_from(old, bundle)
            self.assertEqual(bundle.stat().st_mode & 0o777, 0o600)
            with self.in_home(new):
                device = import_bundle(bundle, host="tablet.example.ts.net")
            self.assertEqual(device.host, "tablet.example.ts.net")
            self.assertEqual(device.host_id, "SAVED-IDENTITY")
            stored = Path(new) / "remote_example-id.plist"
            self.assertEqual(stored.read_bytes(), b"secret-record")
            self.assertEqual(stored.stat().st_mode & 0o777, 0o600)

    def test_keeps_the_original_host_by_default(self):
        with tempfile.TemporaryDirectory() as old, tempfile.TemporaryDirectory() as new:
            bundle = Path(old) / "bundle.json"
            self.export_from(old, bundle)
            with self.in_home(new):
                self.assertEqual(import_bundle(bundle).host, "tablet.local")

    def test_does_not_replace_a_different_pairing_without_force(self):
        with tempfile.TemporaryDirectory() as old, tempfile.TemporaryDirectory() as new:
            bundle = Path(old) / "bundle.json"
            self.export_from(old, bundle)
            stored = Path(new) / "remote_example-id.plist"
            stored.write_bytes(b"other-record")
            with self.in_home(new):
                with self.assertRaisesRegex(SetupError, "--force"):
                    import_bundle(bundle)
                self.assertEqual(stored.read_bytes(), b"other-record")
                import_bundle(bundle, force=True)
            self.assertEqual(stored.read_bytes(), b"secret-record")

    def test_rejects_unknown_files(self):
        with tempfile.TemporaryDirectory() as home:
            source = Path(home) / "other.json"
            source.write_text('{"format": 99}')
            with self.assertRaisesRegex(SetupError, "not a bundle"):
                import_bundle(source)


class HostIdentityTests(unittest.TestCase):
    def identity_used(self, device):
        class Stop(Exception):
            pass

        created = []

        class FakeService:
            def __init__(self, *_args):
                self.identifier = "FROM-HOSTNAME"
                created.append(self)

            async def connect(self, autopair):
                raise Stop

            async def close(self):
                pass

        async def attempt():
            async with RemoteDevice(device).rsd():
                pass

        with patch("ios_remote_control.device.has_pair_record", return_value=True), \
             patch("pymobiledevice3.remote.tunnel_service.RemotePairingManualPairingService", FakeService):
            with self.assertRaises(Stop):
                asyncio.run(attempt())
        return created[0].identifier

    def test_saved_identity_survives_a_hostname_change(self):
        device = Device("tablet", "host", "id", 49152, "SAVED-IDENTITY")
        self.assertEqual(self.identity_used(device), "SAVED-IDENTITY")

    def test_older_aliases_keep_the_hostname_identity(self):
        self.assertEqual(self.identity_used(Device("tablet", "host", "id")), "FROM-HOSTNAME")


class PackagingTests(unittest.TestCase):
    root = Path(__file__).resolve().parent.parent
    plugin = "plugins/ios-remote-control"

    def manifest(self, relative):
        return json.loads((self.root / relative).read_text(encoding="utf-8"))

    def test_versions_match_across_packages(self):
        expected = ios_remote_control.__version__
        self.assertEqual(self.manifest(f"{self.plugin}/.claude-plugin/plugin.json")["version"], expected)
        self.assertEqual(self.manifest(f"{self.plugin}/.codex-plugin/plugin.json")["version"], expected)
        self.assertIn(f'version = "{expected}"', (self.root / "pyproject.toml").read_text(encoding="utf-8"))

    def test_both_plugins_ship_the_skill(self):
        self.assertTrue((self.root / self.plugin / "skills/ios-remote-control/SKILL.md").is_file())
        self.assertEqual(self.manifest(f"{self.plugin}/.codex-plugin/plugin.json")["skills"], "./skills/")

    def test_codex_icons_exist(self):
        interface = self.manifest(f"{self.plugin}/.codex-plugin/plugin.json")["interface"]
        for key in ("composerIcon", "logo"):
            self.assertTrue((self.root / self.plugin / interface[key]).is_file(), key)

    def test_marketplaces_list_the_plugin(self):
        for relative in (".claude-plugin/marketplace.json", ".agents/plugins/marketplace.json"):
            names = [entry["name"] for entry in self.manifest(relative)["plugins"]]
            self.assertEqual(names, ["ios-remote-control"], relative)


class UnlockTests(unittest.TestCase):
    device = RemoteDevice(Device("phone", "host", "id"))

    def screen(self, keys=True, size=(1290, 2796)):
        from PIL import Image, ImageDraw

        image = Image.new("RGB", size, (20, 20, 20))
        if keys:
            draw = ImageDraw.Draw(image)
            for digit in "0123456789":
                x, y = keypad_point(digit, *size)
                draw.ellipse((x - 125, y - 125, x + 125, y + 125), fill=(60, 60, 60))
        output = io.BytesIO()
        image.save(output, "PNG")
        return output.getvalue()

    def test_digits_map_to_measured_keys(self):
        self.assertEqual(keypad_point("1", 1290, 2796), (309, 1113))
        self.assertEqual(keypad_point("6", 1290, 2796), (981, 1437))
        self.assertEqual(keypad_point("8", 1290, 2796), (645, 1761))
        self.assertEqual(keypad_point("0", 1290, 2796), (645, 2085))

    def test_unmeasured_screen_is_refused(self):
        with self.assertRaisesRegex(ValueError, "no passcode keypad layout"):
            keypad_point("1", 1536, 2048)

    def test_recognizes_the_keypad_only_when_it_is_there(self):
        self.assertTrue(keypad_visible(self.screen()))
        self.assertFalse(keypad_visible(self.screen(keys=False)))

    def test_passcode_errors_do_not_reveal_it(self):
        for bad in ("12345", "abcd", "١٢٣٤", ""):
            with self.assertRaises(ValueError) as caught:
                validate_passcode(bad)
            if bad:
                self.assertNotIn(bad, str(caught.exception))
        validate_passcode("1234")
        validate_passcode("123456")

    def run_cli(self, tty=False):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary, \
             patch.dict("os.environ", {"IOS_REMOTE_CONFIG": str(Path(temporary) / "devices.json")}), \
             patch("sys.argv", ["ios-remote", "unlock", "--device", "phone"]), \
             patch("sys.stdin.isatty", return_value=tty), \
             patch.object(RemoteDevice, "unlock", AsyncMock(return_value="unlocked")) as send, \
             patch("builtins.input", return_value="no"), \
             patch("getpass.getpass", return_value="123456") as ask, \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                cli.main()
        return json.loads(output.getvalue()), send, ask

    def test_refuses_without_a_person_at_a_terminal(self):
        payload, send, ask = self.run_cli(tty=False)
        self.assertIn("person at a terminal", payload["error"])
        ask.assert_not_called()
        send.assert_not_called()

    def test_needs_explicit_confirmation(self):
        payload, send, ask = self.run_cli(tty=True)
        self.assertIn("not confirmed", payload["error"])
        ask.assert_not_called()
        send.assert_not_called()

    def test_passcode_cannot_be_passed_as_an_argument(self):
        options = next(a for a in cli.parser()._actions if isinstance(a, argparse._SubParsersAction)).choices["unlock"]
        self.assertEqual([a.dest for a in options._actions], ["help", "device"])


class DocumentationTests(unittest.TestCase):
    root = Path(__file__).resolve().parent.parent

    def commands(self):
        for action in cli.parser()._actions:
            if isinstance(action, argparse._SubParsersAction):
                return action.choices
        self.fail("no subcommands")

    def test_every_function_class_and_module_has_a_docstring(self):
        for path in sorted((self.root / "src").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            self.assertTrue(ast.get_docstring(tree), f"{path.name}: module")
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    self.assertTrue(ast.get_docstring(node), f"{path.name}: {node.name}")

    def test_every_command_and_argument_has_help(self):
        root_actions = next(a for a in cli.parser()._actions if isinstance(a, argparse._SubParsersAction))
        described = {choice.dest for choice in root_actions._choices_actions}
        for name, command in self.commands().items():
            if name != "pair-usb":
                self.assertIn(name, described, f"{name}: command help")
            for action in command._actions:
                if not isinstance(action, argparse._HelpAction):
                    self.assertTrue(action.help, f"{name} {action.dest}: argument help")

    def test_reference_documents_every_command_and_option(self):
        skill = self.root / "plugins/ios-remote-control/skills/ios-remote-control"
        reference = (skill / "references/commands.md").read_text(encoding="utf-8")
        for name, command in self.commands().items():
            self.assertIn(f"`{name}`" if name == "pair-usb" else f"### `{name}`", reference, name)
            for action in command._actions:
                for option in action.option_strings:
                    if option not in ("-h", "--help"):
                        self.assertIn(f"`{option}`", reference, f"{name} {option}")

    def test_skill_links_its_references(self):
        skill = self.root / "plugins/ios-remote-control/skills/ios-remote-control"
        text = (skill / "SKILL.md").read_text(encoding="utf-8")
        for reference in ("references/commands.md", "references/devices.md"):
            self.assertIn(reference, text)
            self.assertTrue((skill / reference).is_file(), reference)


class ConfigTests(unittest.TestCase):
    def test_config_round_trip_and_permissions(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "devices.json"
            expected = {"tablet": Device("tablet", "tablet.example.ts.net", "example-id")}
            save_devices(expected, path)
            self.assertEqual(load_devices(path), expected)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            payload = json.loads(path.read_text())
            self.assertNotIn("name", payload["devices"]["tablet"])
            self.assertNotIn("host_id", payload["devices"]["tablet"])


class BootstrapTests(unittest.TestCase):
    @patch("ios_remote_control.onboarding.subprocess.run")
    def test_reports_the_reason_for_failure(self, run):
        run.return_value = subprocess.CompletedProcess([], 1, "secret stdout", "trace\nPasswordRequiredError: locked\n")
        with self.assertRaisesRegex(SetupError, "Reason: PasswordRequiredError: locked") as caught:
            bootstrap_remote_pairing("example-id")
        self.assertNotIn("secret stdout", str(caught.exception))

    @patch("ios_remote_control.onboarding.subprocess.run")
    def test_times_out_instead_of_hanging(self, run):
        run.side_effect = subprocess.TimeoutExpired("pymobiledevice3", 120)
        with self.assertRaisesRegex(SetupError, "timed out"):
            bootstrap_remote_pairing("example-id")

    @patch("ios_remote_control.onboarding.protect_pair_record")
    @patch("ios_remote_control.onboarding.has_pair_record", return_value=True)
    @patch("ios_remote_control.onboarding.subprocess.run")
    def test_protects_the_new_pair_record(self, run, _has_record, protect):
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        bootstrap_remote_pairing("example-id")
        protect.assert_called_once_with("example-id")


class OnboardingTests(unittest.IsolatedAsyncioTestCase):
    @patch("pymobiledevice3.usbmux.list_devices", new_callable=AsyncMock)
    async def test_finds_a_device_trusted_over_the_network(self, list_devices):
        list_devices.return_value = [SimpleNamespace(serial="wifi-id", is_usb=False)]
        self.assertEqual(await find_trusted_identifier(), "wifi-id")

    @patch("pymobiledevice3.usbmux.list_devices", new_callable=AsyncMock)
    async def test_prefers_the_single_usb_device(self, list_devices):
        list_devices.return_value = [
            SimpleNamespace(serial="usb-id", is_usb=True),
            SimpleNamespace(serial="wifi-id", is_usb=False),
        ]
        self.assertEqual(await find_trusted_identifier(), "usb-id")

    @patch("pymobiledevice3.usbmux.list_devices", new_callable=AsyncMock)
    async def test_same_device_on_two_connections_is_one_device(self, list_devices):
        list_devices.return_value = [
            SimpleNamespace(serial="same", is_usb=False),
            SimpleNamespace(serial="same", is_usb=False),
        ]
        self.assertEqual(await find_trusted_identifier(), "same")

    @patch("ios_remote_control.onboarding.DISCOVERY_WAIT", 0)
    @patch("pymobiledevice3.usbmux.list_devices", new_callable=AsyncMock)
    async def test_requires_a_trusted_device(self, list_devices):
        list_devices.return_value = []
        with self.assertRaisesRegex(SetupError, "no trusted"):
            await find_trusted_identifier()

    @patch("pymobiledevice3.usbmux.list_devices", new_callable=AsyncMock)
    async def test_requires_selection_for_multiple_devices(self, list_devices):
        list_devices.return_value = [
            SimpleNamespace(serial="first", is_usb=False),
            SimpleNamespace(serial="second", is_usb=False),
        ]
        with self.assertRaisesRegex(SetupError, "multiple devices"):
            await find_trusted_identifier()
        self.assertEqual(await find_trusted_identifier("second"), "second")


if __name__ == "__main__":
    unittest.main()
