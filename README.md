# iOS Remote Control

Control a paired physical iPhone or iPad over any routable IP connection, including Tailscale. The CLI creates a rootless userspace RemoteXPC tunnel and exposes an agent-friendly command set for screenshots, app launching, taps, and swipes.

This project is a thin orchestration layer over [pymobiledevice3](https://github.com/doronz88/pymobiledevice3). It does not reimplement Apple's pairing or CoreDevice protocols.

## What it solves

Apple's normal tooling discovers devices on the local network with Bonjour. That discovery does not cross most routed networks. `ios-remote-control` skips Bonjour after pairing and connects directly to the device's reachable hostname or IP address.

Verified on a physical iPad 6th generation running iPadOS 17.7.11 in all four orientations, through a direct Tailscale path on the same local network, with no root tunnel and no WebDriverAgent. Newer iOS versions, iPhones, and relayed internet paths have not been verified.

## Requirements

- Python 3.11 or newer
- An iPhone or iPad supported by `pymobiledevice3`
- One initial USB connection to establish trust and bootstrap RemotePairing
- A route from the computer to the device, such as both devices joining the same Tailnet
- The RemotePairing TCP port reachable on the device; the usual advertised port is `49152`, but it is configurable

The commands execute on your computer. A cloud chatbot cannot reach a private Tailnet by itself; run Codex Desktop or another local agent on a computer that has the route.

## Install

```sh
uv tool install .
```

`pipx install .` works too. Plain `pip install .` needs a virtual environment on a Homebrew Python, which refuses system-wide installs.

Developer Mode is required for CoreDevice services, but it does **not** authorize a new computer by itself. An unpaired client can reach the RemotePairing port, but iOS rejects the setup until trust has been established through an Apple-supported pairing path. The universal path for iOS 17+ is one initial USB connection.

## Set up once over USB

Connect and unlock the device, tap **Trust** if iOS asks, then run:

```sh
ios-remote setup home-ipad --host ipad.example-tailnet.ts.net
```

`setup` finds the single USB-connected device, performs the promptless RemotePairing bootstrap over the already trusted lockdown connection, stores the remote host, and verifies the complete IP path. If the computer has never trusted this device, iOS first shows its normal **Trust This Computer?** prompt. With multiple USB devices attached, add `--udid DEVICE_IDENTIFIER`.

For manual or diagnostic use, the underlying steps remain available:

```sh
ios-remote pair-usb
ios-remote list-pairs
ios-remote add home-ipad --host ipad.example-tailnet.ts.net --identifier DEVICE_IDENTIFIER
```

Pairing records contain credentials and stay in pymobiledevice3's local data directory. Never copy them into this repository or send them to an agent.

The alias file is stored at `~/.config/ios-remote-control/devices.json` with mode `0600`. Set `IOS_REMOTE_CONFIG` to use a different path.

## Use

```sh
ios-remote info --device home-ipad
ios-remote doctor --device home-ipad
ios-remote screenshot --device home-ipad screen.png
ios-remote launch --device home-ipad com.apple.Home
ios-remote home --device home-ipad
ios-remote tap --device home-ipad 500 700
ios-remote swipe --device home-ipad 1500 800 500 800
```

Tap and swipe coordinates are pixels in the current screenshot, in the orientation the screenshot shows. The CLI reads the display rotation from the device and converts the pixels to CoreDevice HID coordinates, which stay in the native orientation.

`info` also reports `orientation`, `rotation`, `backlight`, and `passcode_required`. `doctor` exits with status 1 unless the device is ready. Run commands one at a time: parallel screen captures can fail.

For reliable automation, always use an observe-act-verify loop:

1. Capture a screenshot.
2. Inspect the current state and choose coordinates.
3. Perform one action.
4. Capture another screenshot and verify the result.

## When a person is still needed

The device can be controlled unattended only while it is paired, online, and unlocked. Someone has to be with it to:

- connect USB, unlock, and accept Trust for the first pairing;
- unlock it, because this tool does not enter a passcode;
- answer Touch ID or Face ID prompts, which touch input cannot satisfy;
- bring it back after a reboot or when Tailscale has stopped running on it.

## Codex skill

The repository includes `.codex/skills/ios-remote-control`. When the repository is open in Codex it describes the safe observe-act-verify workflow. You can also copy that folder into `~/.codex/skills/` for global use.

## Current scope

This first release deliberately stays small:

- direct connection to a saved host and port;
- rootless userspace tunnel;
- device information and PNG screenshots;
- application launch by bundle identifier and the Home button;
- single-finger tap and swipe.

It does not provide unattended first-time trust, bypass the lock screen, expose the device publicly, or relay traffic through a hosted service. This is intentional: Developer Mode enables developer services but must not silently grant a new computer control of the device.

## Security

- Use a private routed network such as Tailscale; do not expose the RemotePairing port to the public internet.
- Treat pairing records as device-control credentials.
- Screenshots may contain messages, authentication codes, or personal data.
- Keep agent permissions narrow and request confirmation before destructive or sensitive actions.

## License

MIT. `pymobiledevice3` remains under its own license.
