from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Device:
    name: str
    host: str
    identifier: str
    port: int = 49152


def config_path() -> Path:
    override = os.environ.get("IOS_REMOTE_CONFIG")
    if override:
        return Path(override).expanduser()
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "ios-remote-control" / "devices.json"


def load_devices(path: Path | None = None) -> dict[str, Device]:
    path = path or config_path()
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {name: Device(name=name, **values) for name, values in data.get("devices", {}).items()}


def save_devices(devices: dict[str, Device], path: Path | None = None) -> None:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "devices": {
            name: {key: value for key, value in asdict(device).items() if key != "name"}
            for name, device in sorted(devices.items())
        }
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)
