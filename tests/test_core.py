import json
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import argparse
import asyncio
import contextlib
import io
import subprocess

from ios_remote_control import cli
from ios_remote_control.config import Device, load_devices, save_devices
from ios_remote_control.device import RemoteDevice, pixel_to_hid, png_dimensions, rotation_degrees, screen_to_hid
from ios_remote_control.onboarding import SetupError, bootstrap_remote_pairing, find_usb_identifier


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
        self.assertEqual((code, payload["status"]), (1, "needs_usb_pairing"))

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
        arguments = argparse.Namespace(name="tablet", host="host", identifier="id", port=70000)
        with self.assertRaisesRegex(ValueError, "port"):
            cli.add_device(arguments)


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
    async def test_finds_only_usb_device(self, list_devices):
        list_devices.return_value = [
            SimpleNamespace(serial="usb-id", is_usb=True),
            SimpleNamespace(serial="wifi-id", is_usb=False),
        ]
        self.assertEqual(await find_usb_identifier(), "usb-id")

    @patch("pymobiledevice3.usbmux.list_devices", new_callable=AsyncMock)
    async def test_requires_usb_device(self, list_devices):
        list_devices.return_value = []
        with self.assertRaisesRegex(SetupError, "no USB"):
            await find_usb_identifier()

    @patch("pymobiledevice3.usbmux.list_devices", new_callable=AsyncMock)
    async def test_requires_selection_for_multiple_devices(self, list_devices):
        list_devices.return_value = [
            SimpleNamespace(serial="first", is_usb=True),
            SimpleNamespace(serial="second", is_usb=True),
        ]
        with self.assertRaisesRegex(SetupError, "multiple USB"):
            await find_usb_identifier()
        self.assertEqual(await find_usb_identifier("second"), "second")


if __name__ == "__main__":
    unittest.main()
