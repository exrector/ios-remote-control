# iOS Remote Control

Control a paired physical iPhone or iPad over any routable IP connection, including Tailscale. The CLI creates a rootless userspace RemoteXPC tunnel and exposes an agent-friendly command set for screenshots, app launching, taps, and swipes.

This project is a thin orchestration layer over [pymobiledevice3](https://github.com/doronz88/pymobiledevice3). It does not reimplement Apple's pairing or CoreDevice protocols.

## What it solves

Apple's normal tooling discovers devices on the local network with Bonjour. That discovery does not cross most routed networks. `ios-remote-control` skips Bonjour after pairing and connects directly to the device's reachable hostname or IP address.

Verified on a physical iPad 6th generation running iPadOS 17.7.11 through Tailscale, with no root tunnel and no WebDriverAgent.

## Requirements

- Python 3.11 or newer
- An iPhone or iPad supported by `pymobiledevice3`
- One initial trusted USB connection for RemotePairing bootstrap
- A route from the computer to the device, such as both devices joining the same Tailnet
- The RemotePairing TCP port reachable on the device; the usual advertised port is `49152`, but it is configurable

The commands execute on your computer. A cloud chatbot cannot reach a private Tailnet by itself; run Codex Desktop or another local agent on a computer that has the route.

## Install

```sh
python3 -m pip install .
```

For an isolated installation, use `pipx install .` or `uv tool install .`.

## Pair once over USB

Connect and unlock the device, tap **Trust** if iOS asks, then run:

```sh
ios-remote pair-usb
ios-remote list-pairs
```

`pair-usb` uses the trusted USB connection to create the RemotePairing record required by later IP connections. Pairing records contain credentials and stay in pymobiledevice3's local data directory. Never copy them into this repository or send them to an agent.

Save a local alias using the identifier shown by `list-pairs`:

```sh
ios-remote add home-ipad \
  --host ipad.example-tailnet.ts.net \
  --identifier DEVICE_IDENTIFIER \
  --port 49152
```

The alias file is stored at `~/.config/ios-remote-control/devices.json` with mode `0600`. Set `IOS_REMOTE_CONFIG` to use a different path.

## Use

```sh
ios-remote info --device home-ipad
ios-remote screenshot --device home-ipad screen.png
ios-remote launch --device home-ipad com.apple.Home
ios-remote tap --device home-ipad 768 1712
ios-remote swipe --device home-ipad 768 1700 768 500
```

Tap and swipe coordinates are pixels in the current screenshot. The CLI captures the current screen internally and converts the pixel coordinates to CoreDevice HID coordinates.

For reliable automation, always use an observe-act-verify loop:

1. Capture a screenshot.
2. Inspect the current state and choose coordinates.
3. Perform one action.
4. Capture another screenshot and verify the result.

## Codex skill

The repository includes `.codex/skills/ios-remote-control`. When the repository is open in Codex it describes the safe observe-act-verify workflow. You can also copy that folder into `~/.codex/skills/` for global use.

## Current scope

This first release deliberately stays small:

- direct connection to a saved host and port;
- rootless userspace tunnel;
- device information and PNG screenshots;
- application launch by bundle identifier;
- single-finger tap and swipe.

It does not provide unattended first-time pairing, bypass the lock screen, expose the device publicly, or relay traffic through a hosted service.

## Security

- Use a private routed network such as Tailscale; do not expose the RemotePairing port to the public internet.
- Treat pairing records as device-control credentials.
- Screenshots may contain messages, authentication codes, or personal data.
- Keep agent permissions narrow and request confirmation before destructive or sensitive actions.

## License

MIT. `pymobiledevice3` remains under its own license.
