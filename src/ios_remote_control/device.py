from __future__ import annotations

import asyncio
import struct
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Any

from .config import Device
from .onboarding import has_pair_record

# pymobiledevice3 gives up after one second, too short for a relayed Tailscale path.
CONNECT_TIMEOUT = 10
HOME_BUTTON = (0x0C, 0x40)
HID_MAX = 65535
ROTATIONS = {"rot0": 0, "rot90": 90, "rot180": 180, "rot270": 270}
# Launching SpringBoard restarts the home screen instead of opening it.
UNLAUNCHABLE_BUNDLES = {"com.apple.springboard"}


class PairingRequiredError(RuntimeError):
    pass


def png_dimensions(data: bytes) -> tuple[int, int]:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError("screen capture did not return a valid PNG")
    return struct.unpack(">II", data[16:24])


def pixel_to_hid(value: float, extent: int) -> int:
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


class RemoteDevice:
    def __init__(self, device: Device):
        self.device = device

    @asynccontextmanager
    async def rsd(self) -> AsyncIterator[Any]:
        from pymobiledevice3.remote import tunnel_service, userspace_tunnel
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
            tunnel_service.USE_USERSPACE_TUNNEL = True
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
        finally:
            await service.close()

    async def info(self) -> dict[str, Any]:
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
        from pymobiledevice3.remote.core_device.screen_capture_service import ScreenCaptureService

        async with self.rsd() as rsd:
            async with ScreenCaptureService(rsd) as capture:
                response = await capture.capture_screenshot()
                return response["image"]

    async def screenshot(self, output: Path) -> tuple[int, int]:
        data = await self.screenshot_bytes()
        dimensions = png_dimensions(data)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
        return dimensions

    async def launch(self, bundle_id: str) -> None:
        from pymobiledevice3.remote.core_device.app_service import AppServiceService

        if bundle_id in UNLAUNCHABLE_BUNDLES:
            raise ValueError(f"launching {bundle_id} restarts the home screen; use `ios-remote home`")
        async with self.rsd() as rsd:
            async with AppServiceService(rsd) as apps:
                await apps.launch_application(bundle_id)

    async def home(self) -> None:
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

    async def _screen_size(self, rsd: Any) -> tuple[int, int]:
        from pymobiledevice3.remote.core_device.screen_capture_service import ScreenCaptureService

        async with ScreenCaptureService(rsd) as capture:
            response = await capture.capture_screenshot()
        return png_dimensions(response["image"])

    async def _rotation(self, rsd: Any) -> int:
        from pymobiledevice3.remote.core_device.device_info import DeviceInfoService

        async with DeviceInfoService(rsd) as info:
            return rotation_degrees(await info.get_display_info())

    async def tap(self, x: float, y: float, hold: float = 0.08) -> tuple[int, int]:
        from pymobiledevice3.remote.core_device.hid_service import UniversalHIDServiceService

        if hold < 0:
            raise ValueError("hold must not be negative")
        async with self.rsd() as rsd:
            width, height = await self._screen_size(rsd)
            point = screen_to_hid(x, y, width, height, await self._rotation(rsd))
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
        from pymobiledevice3.remote.core_device.hid_service import UniversalHIDServiceService

        if steps < 1:
            raise ValueError("steps must be at least 1")
        if duration <= 0:
            raise ValueError("duration must be positive")
        async with self.rsd() as rsd:
            width, height = await self._screen_size(rsd)
            rotation = await self._rotation(rsd)
            path = (
                *screen_to_hid(x1, y1, width, height, rotation),
                *screen_to_hid(x2, y2, width, height, rotation),
            )
            async with UniversalHIDServiceService(rsd) as hid:
                await hid.multi_drag([path], duration=duration, steps=steps)
            return width, height


def run(coroutine: Any) -> Any:
    return asyncio.run(coroutine)
