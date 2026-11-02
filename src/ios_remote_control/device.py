from __future__ import annotations

import asyncio
import struct
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Any

from .config import Device
from .onboarding import has_pair_record


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
                "no local RemotePairing record; connect the unlocked device over USB and run "
                f"`ios-remote setup {self.device.name} --host {self.device.host}`"
            )

        service = RemotePairingManualPairingService(self.device.identifier, self.device.host, self.device.port)
        try:
            await service.connect(autopair=False)
            if not hasattr(service, "client_cip"):
                raise PairingRequiredError(
                    "the RemotePairing record was rejected; reconnect over USB and run `ios-remote pair-usb`"
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
        async with self.rsd() as rsd:
            properties = (rsd.peer_info or {}).get("Properties", {})
            return {
                "name": properties.get("DeviceName") or properties.get("Name"),
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
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
        return png_dimensions(data)

    async def launch(self, bundle_id: str) -> None:
        from pymobiledevice3.remote.core_device.app_service import AppServiceService

        async with self.rsd() as rsd:
            async with AppServiceService(rsd) as apps:
                await apps.launch_application(bundle_id)

    async def _screen_size(self, rsd: Any) -> tuple[int, int]:
        from pymobiledevice3.remote.core_device.screen_capture_service import ScreenCaptureService

        async with ScreenCaptureService(rsd) as capture:
            response = await capture.capture_screenshot()
        return png_dimensions(response["image"])

    async def tap(self, x: float, y: float, hold: float = 0.08) -> tuple[int, int]:
        from pymobiledevice3.remote.core_device.hid_service import UniversalHIDServiceService

        async with self.rsd() as rsd:
            width, height = await self._screen_size(rsd)
            point = (pixel_to_hid(x, width), pixel_to_hid(y, height))
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

        async with self.rsd() as rsd:
            width, height = await self._screen_size(rsd)
            path = (
                pixel_to_hid(x1, width),
                pixel_to_hid(y1, height),
                pixel_to_hid(x2, width),
                pixel_to_hid(y2, height),
            )
            async with UniversalHIDServiceService(rsd) as hid:
                await hid.multi_drag([path], duration=duration, steps=steps)
            return width, height


def run(coroutine: Any) -> Any:
    return asyncio.run(coroutine)
