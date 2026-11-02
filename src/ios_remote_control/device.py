"""Connect to a paired device over its routable address and operate it through CoreDevice."""

from __future__ import annotations

import asyncio
import struct
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Any

from .config import Device
from .onboarding import has_pair_record

# pymobiledevice3 gives up after one to three seconds, too short for a relayed Tailscale path.
CONNECT_TIMEOUT = 10
HANDSHAKE_TIMEOUT = 20
HOME_BUTTON = (0x0C, 0x40)
HID_MAX = 65535
ROTATIONS = {"rot0": 0, "rot90": 90, "rot180": 180, "rot270": 270}
# Launching SpringBoard restarts the home screen instead of opening it.
UNLAUNCHABLE_BUNDLES = {"com.apple.springboard"}
# Centers of the passcode keys in portrait screenshots: columns, then rows. Measured on each device.
KEYPADS = {(1290, 2796): ((309, 645, 981), (1113, 1437, 1761, 2085))}
# Codes of these lengths submit themselves. Others need the OK button that appears after the first digit.
AUTO_SUBMIT_LENGTHS = (4, 6)
PASSCODE_MIN_LENGTH = 4
PASSCODE_MAX_LENGTH = 16
OK_BUTTONS = {(1290, 2796): (978, 716)}
UNLOCK_WAKE_SECONDS = 1
UNLOCK_KEYPAD_SECONDS = 0.5
BACKLIGHT_ON = "activeOn"
UNLOCK_SETTLE_SECONDS = 2
UNLOCK_KEY_GAP_SECONDS = 0.25


class PairingRequiredError(RuntimeError):
    """The device has no usable RemotePairing record on this computer."""


def png_dimensions(data: bytes) -> tuple[int, int]:
    """Read width and height from PNG data, or raise ValueError if it is not a PNG."""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError("screen capture did not return a valid PNG")
    return struct.unpack(">II", data[16:24])


def pixel_to_hid(value: float, extent: int) -> int:
    """Scale a pixel position to the 0..65535 HID range, or raise ValueError if it is off screen."""
    if extent <= 1:
        raise ValueError("screen extent must be greater than one pixel")
    if value < 0 or value > extent - 1:
        raise ValueError(f"coordinate {value} is outside 0..{extent - 1}")
    return round(value * 65535 / (extent - 1))


def rotation_degrees(display_info: dict[str, Any]) -> int:
    """Rotation of the primary display's interface relative to its native orientation."""
    display = next(item for item in display_info["displays"] if item.get("primary"))
    current = ROTATIONS[display["currentOrientation"]]
    return (current - ROTATIONS[display.get("nativeOrientation", "rot0")]) % 360


def screen_geometry(display_info: dict[str, Any]) -> tuple[int, int, int]:
    """Width and height as a screenshot shows them, and the rotation, without capturing a screenshot."""
    display = next(item for item in display_info["displays"] if item.get("primary"))
    width, height = (int(value) for value in display["currentMode"]["size"])
    rotation = rotation_degrees(display_info)
    return (height, width, rotation) if rotation in (90, 270) else (width, height, rotation)


def screen_to_hid(x: float, y: float, width: int, height: int, rotation: int) -> tuple[int, int]:
    """Map screenshot pixels to HID coordinates, which stay in the native orientation."""
    if (rotation in (90, 270)) != (width > height):
        raise ValueError(f"device reports rotation {rotation} but the screen is {width}x{height}; retry")
    across, down = pixel_to_hid(x, width), pixel_to_hid(y, height)
    if rotation == 90:
        return down, HID_MAX - across
    if rotation == 180:
        return HID_MAX - across, HID_MAX - down
    if rotation == 270:
        return HID_MAX - down, across
    return across, down


def keypad_point(digit: str, width: int, height: int) -> tuple[int, int]:
    """Return where a passcode digit is on this screen, or raise ValueError for an unmeasured screen."""
    if (width, height) not in KEYPADS:
        raise ValueError(f"no passcode keypad layout is known for a {width}x{height} screen")
    if len(digit) != 1 or digit not in "0123456789":
        raise ValueError("a passcode key must be one digit")
    columns, rows = KEYPADS[(width, height)]
    if digit == "0":
        return columns[1], rows[3]
    index = int(digit) - 1
    return columns[index % 3], rows[index // 3]


def validate_passcode(passcode: str) -> None:
    """Raise ValueError unless this is a passcode the keypad can enter. The message never contains it."""
    if (
        not passcode.isascii()
        or not passcode.isdigit()
        or not PASSCODE_MIN_LENGTH <= len(passcode) <= PASSCODE_MAX_LENGTH
    ):
        raise ValueError(
            f"only numeric passcodes of {PASSCODE_MIN_LENGTH} to {PASSCODE_MAX_LENGTH} digits are supported; "
            "nothing was sent to the device"
        )


class RemoteDevice:
    """Operations on one saved device. Each one opens its own tunnel and closes it afterwards."""

    def __init__(self, device: Device):
        """Remember the saved device to operate on."""
        self.device = device

    @asynccontextmanager
    async def rsd(self) -> AsyncIterator[Any]:
        """Open a rootless userspace tunnel to the device and yield its service connection."""
        from pymobiledevice3.remote import remote_service_discovery, remotexpc, tunnel_service, userspace_tunnel
        from pymobiledevice3.remote.remote_service_discovery import RemoteServiceDiscoveryService
        from pymobiledevice3.remote.tunnel_service import RemotePairingManualPairingService
        from pymobiledevice3.remote.userspace_tunnel import UserspaceDialPlane

        if not has_pair_record(self.device.identifier):
            raise PairingRequiredError(
                "no local RemotePairing record; with the device trusted by this computer and unlocked, run "
                f"`ios-remote setup {self.device.name} --host {self.device.host}`"
            )

        service = RemotePairingManualPairingService(self.device.identifier, self.device.host, self.device.port)
        if self.device.host_id:
            # A pairing belongs to the identity it was made with, not to the current hostname.
            service.identifier = self.device.host_id
        try:
            previous_timeout = tunnel_service.TIMEOUT
            tunnel_service.TIMEOUT = CONNECT_TIMEOUT
            try:
                await service.connect(autopair=False)
            finally:
                tunnel_service.TIMEOUT = previous_timeout
            if not hasattr(service, "client_cip"):
                raise PairingRequiredError(
                    "the RemotePairing record was rejected; if this computer's name changed or the record came from "
                    "another computer, set its identity with `ios-remote add --host-id`; otherwise run `ios-remote pair` "
                    "while this computer trusts the device"
                )

            previous_use_userspace = tunnel_service.USE_USERSPACE_TUNNEL
            previous_first_reply = remotexpc.FIRST_REPLY_TIMEOUT
            previous_peer_info = remote_service_discovery.PEER_INFO_TIMEOUT
            tunnel_service.USE_USERSPACE_TUNNEL = True
            remotexpc.FIRST_REPLY_TIMEOUT = HANDSHAKE_TIMEOUT
            remote_service_discovery.PEER_INFO_TIMEOUT = HANDSHAKE_TIMEOUT
            try:
                async with service.start_tcp_tunnel() as tunnel:
                    tun = tunnel.client.tun
                    tun.set_peer(tunnel.address)
                    async with UserspaceDialPlane(tun, tunnel.address) as dial_plane:
                        previous_active = userspace_tunnel.USERSPACE_ACTIVE
                        previous_tunnel = userspace_tunnel._active_tunnel
                        userspace_tunnel.USERSPACE_ACTIVE = True
                        active_tunnel = userspace_tunnel.UserspaceRsdTunnel()
                        active_tunnel.tun = tun
                        rsd = RemoteServiceDiscoveryService(
                            (tunnel.address, tunnel.port),
                            open_connection=dial_plane.dial,
                            auxiliary_metadata=tunnel.auxiliary_metadata,
                        )
                        active_tunnel.rsd = rsd
                        userspace_tunnel._active_tunnel = active_tunnel
                        try:
                            await rsd.connect()
                            yield rsd
                        finally:
                            await rsd.close()
                            userspace_tunnel.USERSPACE_ACTIVE = previous_active
                            userspace_tunnel._active_tunnel = previous_tunnel
            finally:
                tunnel_service.USE_USERSPACE_TUNNEL = previous_use_userspace
                remotexpc.FIRST_REPLY_TIMEOUT = previous_first_reply
                remote_service_discovery.PEER_INFO_TIMEOUT = previous_peer_info
        finally:
            await service.close()

    async def info(self) -> dict[str, Any]:
        """Return device model, OS, orientation, rotation, backlight, and passcode state."""
        from pymobiledevice3.remote.core_device.device_info import DeviceInfoService

        async with self.rsd() as rsd:
            properties = (rsd.peer_info or {}).get("Properties", {})
            async with DeviceInfoService(rsd) as device_info:
                display_info = await device_info.get_display_info()
            return {
                "orientation": display_info["orientation"]["currentDeviceOrientation"],
                "rotation": rotation_degrees(display_info),
                "backlight": display_info.get("backlightState"),
                "passcode_required": await rsd.get_value(key="PasswordProtected"),
                "alias": self.device.name,
                "identifier": properties.get("UniqueDeviceID"),
                "product": properties.get("ProductType"),
                "os": properties.get("OSVersion"),
                "host": self.device.host,
                "port": self.device.port,
            }

    async def screenshot_bytes(self) -> bytes:
        """Capture the current screen as PNG data."""
        from pymobiledevice3.remote.core_device.screen_capture_service import ScreenCaptureService

        async with self.rsd() as rsd:
            async with ScreenCaptureService(rsd) as capture:
                response = await capture.capture_screenshot()
                return response["image"]

    async def screenshot(self, output: Path) -> tuple[int, int]:
        """Save the screen to a file only if it is a valid PNG, and return its width and height."""
        data = await self.screenshot_bytes()
        dimensions = png_dimensions(data)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
        return dimensions

    async def launch(self, bundle_id: str) -> None:
        """Open an app. SpringBoard is refused, because launching it restarts the home screen."""
        from pymobiledevice3.remote.core_device.app_service import AppServiceService

        if bundle_id in UNLAUNCHABLE_BUNDLES:
            raise ValueError(f"launching {bundle_id} restarts the home screen; use `ios-remote home`")
        async with self.rsd() as rsd:
            async with AppServiceService(rsd) as apps:
                await apps.launch_application(bundle_id)

    async def home(self) -> None:
        """Press and release the Home button."""
        from pymobiledevice3.remote.core_device.hid_service import (
            HID_BUTTON_STATE_DOWN,
            HID_BUTTON_STATE_UP,
            IndigoHIDService,
        )

        async with self.rsd() as rsd:
            async with IndigoHIDService(rsd) as buttons:
                await buttons.send_button(*HOME_BUTTON, HID_BUTTON_STATE_DOWN)
                await asyncio.sleep(0.05)
                await buttons.send_button(*HOME_BUTTON, HID_BUTTON_STATE_UP)

    async def _press_home(self, rsd: Any) -> None:
        """Press and release the Home button on an open connection."""
        from pymobiledevice3.remote.core_device.hid_service import (
            HID_BUTTON_STATE_DOWN,
            HID_BUTTON_STATE_UP,
            IndigoHIDService,
        )

        async with IndigoHIDService(rsd) as buttons:
            await buttons.send_button(*HOME_BUTTON, HID_BUTTON_STATE_DOWN)
            await asyncio.sleep(0.05)
            await buttons.send_button(*HOME_BUTTON, HID_BUTTON_STATE_UP)

    async def _show_keypad(self, rsd: Any, hid: Any, width: int, height: int) -> None:
        """Wake a dark screen and swipe up once. The keypad fades quickly, so typing must follow at once."""
        from pymobiledevice3.remote.core_device.device_info import DeviceInfoService

        async with DeviceInfoService(rsd) as info:
            screen_on = (await info.get_display_info()).get("backlightState") == BACKLIGHT_ON
        if not screen_on:
            await self._press_home(rsd)
            await asyncio.sleep(UNLOCK_WAKE_SECONDS)
        start = screen_to_hid(width / 2, height * 0.97, width, height, 0)
        end = screen_to_hid(width / 2, height * 0.45, width, height, 0)
        await hid.multi_drag([(*start, *end)], duration=0.3, steps=12)
        await asyncio.sleep(UNLOCK_KEYPAD_SECONDS)

    async def unlock(self, passcode: str) -> str:
        """Bring up the keypad and enter a passcode once. Return `unlocked` or `already_unlocked`.

        It never retries, because repeated failures make iOS disable the device.
        """
        from pymobiledevice3.remote.core_device.hid_service import UniversalHIDServiceService

        validate_passcode(passcode)
        async with self.rsd() as rsd:
            if not await rsd.get_value(key="PasswordProtected"):
                return "already_unlocked"
            width, height, rotation = await self._geometry(rsd)
            if rotation != 0:
                raise ValueError("the passcode keypad is only supported in portrait; no digits were entered")
            keypad_point("0", width, height)
            async with UniversalHIDServiceService(rsd) as hid:
                await self._show_keypad(rsd, hid, width, height)
                for digit in passcode:
                    x, y = keypad_point(digit, width, height)
                    await hid.multi_tap([screen_to_hid(x, y, width, height, 0)], hold=0.05)
                    await asyncio.sleep(UNLOCK_KEY_GAP_SECONDS)
                if len(passcode) not in AUTO_SUBMIT_LENGTHS:
                    await hid.multi_tap([screen_to_hid(*OK_BUTTONS[(width, height)], width, height, 0)], hold=0.05)
            await asyncio.sleep(UNLOCK_SETTLE_SECONDS)
            if await rsd.get_value(key="PasswordProtected"):
                raise ValueError("the device is still locked after one attempt; not retrying, check it before trying again")
            return "unlocked"

    async def _geometry(self, rsd: Any) -> tuple[int, int, int]:
        """Ask the device for its screen size and rotation, without transferring a screenshot."""
        from pymobiledevice3.remote.core_device.device_info import DeviceInfoService

        async with DeviceInfoService(rsd) as info:
            return screen_geometry(await info.get_display_info())

    async def tap(self, x: float, y: float, hold: float = 0.08) -> tuple[int, int]:
        """Touch one point given in screenshot pixels, and return the screen size."""
        from pymobiledevice3.remote.core_device.hid_service import UniversalHIDServiceService

        if hold < 0:
            raise ValueError("hold must not be negative")
        async with self.rsd() as rsd:
            width, height, rotation = await self._geometry(rsd)
            point = screen_to_hid(x, y, width, height, rotation)
            async with UniversalHIDServiceService(rsd) as hid:
                await hid.multi_tap([point], hold=hold)
            return width, height

    async def swipe(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        duration: float = 0.6,
        steps: int = 30,
    ) -> tuple[int, int]:
        """Drag one finger between two points given in screenshot pixels, and return the screen size."""
        from pymobiledevice3.remote.core_device.hid_service import UniversalHIDServiceService

        if steps < 1:
            raise ValueError("steps must be at least 1")
        if duration <= 0:
            raise ValueError("duration must be positive")
        async with self.rsd() as rsd:
            width, height, rotation = await self._geometry(rsd)
            path = (
                *screen_to_hid(x1, y1, width, height, rotation),
                *screen_to_hid(x2, y2, width, height, rotation),
            )
            async with UniversalHIDServiceService(rsd) as hid:
                await hid.multi_drag([path], duration=duration, steps=steps)
            return width, height


def run(coroutine: Any) -> Any:
    """Run one asynchronous operation to completion from synchronous code."""
    return asyncio.run(coroutine)
