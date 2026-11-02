# iOS Remote Control

Control a paired physical iPhone or iPad over any routable IP connection, including Tailscale. The CLI creates a rootless userspace RemoteXPC tunnel and exposes an agent-friendly command set for screenshots, app launching, taps, and swipes.

This project is a thin orchestration layer over [pymobiledevice3](https://github.com/doronz88/pymobiledevice3). It does not reimplement Apple's pairing or CoreDevice protocols.

## What it solves

Apple's normal tooling discovers devices on the local network with Bonjour. That discovery does not cross most routed networks. `ios-remote-control` skips Bonjour after pairing and connects directly to the device's reachable hostname or IP address.

### What has been verified

| Tested on a physical iPad 6th generation, iPadOS 17.7.11 | Result |
| --- | --- |
| Screenshots, app launch, tap, swipe, and Home over a direct Tailscale path | Works, 2–3 seconds per command |
| Commands from a computer in another country over a relayed Tailscale path (DERP) | Works, about 9 seconds per command |
| Touch input in all four orientations | Correct |
| First pairing from a new computer over Tailscale or local Wi-Fi | Refused by iOS |
| A pairing moved to another computer | Works with the original identity |

Not verified yet: iPhones, iOS newer than 17.7, the lock screen, and a full first-time `setup` over USB with this release.

## Requirements

- macOS, the only platform tested so far
- Python 3.11 or newer, with `uv` or `pipx` to install the command
- An iPhone or iPad supported by `pymobiledevice3`, with Developer Mode on
- A person with the device for the first pairing
- A route from the computer to the device, such as both devices joining the same Tailnet
- The RemotePairing TCP port reachable on the device; the usual advertised port is `49152`, but it is configurable

The commands execute on your computer. A cloud chatbot cannot reach a private Tailnet by itself; run Claude Code, Codex, or another local agent on a computer that has the route.

## Install

### As a plugin

Claude Code:

```sh
claude plugin marketplace add exrector/ios-remote-control
claude plugin install ios-remote-control@ios-remote-control
```

Codex:

```sh
codex plugin marketplace add exrector/ios-remote-control
codex plugin add ios-remote-control@ios-remote-control
```

The plugin gives the agent the skill. It does not install the `ios-remote` command, so the skill offers to do that the first time it runs.

### Only the command

```sh
uv tool install git+https://github.com/exrector/ios-remote-control
```

`pipx install git+https://github.com/exrector/ios-remote-control` works too. From a clone, use `uv tool install .`.

## Pair once, with the device in hand

Developer Mode is required for CoreDevice services, but it does **not** authorize a new computer by itself. Over the network, iOS closes the connection as soon as an unpaired computer asks to pair. This happened both over Tailscale and on the same Wi-Fi, so first pairing cannot be done from afar.

Once paired, the device can be anywhere on your Tailnet.

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

Pairing records contain credentials and stay in pymobiledevice3's local data directory. Never copy them into a repository or send them to an agent.

The alias file is stored at `~/.config/ios-remote-control/devices.json` with mode `0600`. Set `IOS_REMOTE_CONFIG` to use a different path.

iOS 27 adds pairing without a cable: `pymobiledevice3` documents `remote pair-host`, with the device on the same Wi-Fi as the computer and a code entered in **Settings > Developer > Paired Macs**. It still needs a person with the device. It has not been tested with this project.

### Your computer's identity

iOS knows your computer by an identity that `pymobiledevice3` derives from its hostname. Aliases made with this version save that identity, so a pairing keeps working if the hostname changes. An alias made with an earlier version does not have it; run `ios-remote add` again to save it.

### Moving a pairing to another computer

If someone pairs the device for you, or you want to control it from a second computer:

1. On the computer that made the pairing, run `ios-remote list` and note `identifier` and `host_id`.
2. Copy `~/.pymobiledevice3/remote_IDENTIFIER.plist` to the same path on the new computer over a private channel, and run `chmod 600` on it. Anyone holding this file can control the device.
3. On the new computer, run:

```sh
ios-remote add home-ipad --host ipad.example-tailnet.ts.net --identifier IDENTIFIER --host-id HOST_ID
```

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

`info` also reports `orientation`, `rotation`, `backlight`, and `passcode_required`. `doctor` exits with status 1 unless the device is ready. Run commands one at a time: parallel screen captures can fail. Each command opens its own tunnel, which accounts for most of the time it takes.

For reliable automation, always use an observe-act-verify loop:

1. Capture a screenshot.
2. Inspect the current state and choose coordinates.
3. Perform one action.
4. Capture another screenshot and verify the result.

## When a person is still needed

The device can be controlled unattended only while it is paired, online, and unlocked. Someone has to be with it to:

- do the first pairing;
- unlock it, because this tool does not enter a passcode;
- answer Touch ID or Face ID prompts, which touch input cannot satisfy;
- bring it back after a reboot or when Tailscale has stopped running on it.

## Current scope

This release deliberately stays small:

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

Free and open source under [GPL-3.0-or-later](LICENSE), the same license as `pymobiledevice3`, which this project depends on.
