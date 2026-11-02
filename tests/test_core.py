import json
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from ios_remote_control.config import Device, load_devices, save_devices
from ios_remote_control.device import pixel_to_hid, png_dimensions
from ios_remote_control.onboarding import SetupError, find_usb_identifier


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
