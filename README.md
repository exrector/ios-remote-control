# iOS Remote Control

Control a paired physical iPhone or iPad over any routable IP connection, including Tailscale. The CLI creates a rootless userspace RemoteXPC tunnel and exposes an agent-friendly command set for screenshots, app launching, taps, and swipes.

This project is a thin orchestration layer over [pymobiledevice3](https://github.com/doronz88/pymobiledevice3). It does not reimplement Apple's pairing or CoreDevice protocols.

## First condition: the device must already be paired with your Mac

**This tool does not create the first pairing.** A person pairs the device with the Mac first, and Xcode or Device Hub then shows it as paired.

| Device | System | Pair by cable | Pair without a cable |
| --- | --- | --- | --- |
| iPhone, iPad | iOS or iPadOS 27 and later | Yes | Yes, on the same Wi-Fi |
| iPhone, iPad | iOS or iPadOS 26 and earlier | Yes | **No** |
| Apple Watch | Companion iPhone comes first | Through the paired iPhone | watchOS 27 and later |
| Apple TV | tvOS | Not described by Apple | Yes, on the same Wi-Fi with IPv6, using a PIN |
| Apple Vision Pro | visionOS | Not described by Apple | Yes, on the same Wi-Fi with IPv6, using a PIN |

This tool supports iPhones and iPads on iOS or iPadOS 17 and later. It does not support Apple Watch, Apple TV, or Apple Vision Pro, even though they can pair with a Mac.

[Devices, systems, and connections](plugins/ios-remote-control/skills/ios-remote-control/references/devices.md) has the steps for each device, what breaks a pairing, and Apple's sources.

## Documentation for AI agents

This tool is meant to be used by an agent, which gets everything it needs from the plugin:

- [Skill](plugins/ios-remote-control/skills/ios-remote-control/SKILL.md): how to connect and work safely.
- [Command reference](plugins/ios-remote-control/skills/ios-remote-control/references/commands.md): every command, argument, output field, and error.
- [Devices and connections](plugins/ios-remote-control/skills/ios-remote-control/references/devices.md): what pairs how, on which system.

Tests fail if a command, an argument, a function, or a class is left undocumented.

## What it solves

Apple's normal tooling discovers devices on the local network with Bonjour. That discovery does not cross most routed networks. `ios-remote-control` skips Bonjour after pairing and connects directly to the device's reachable hostname or IP address.

### What has been verified

| Test | Device | Result |
| --- | --- | --- |
| First pairing by cable, then `setup` and control over Tailscale | iPad, iPadOS 17.7.11 | Works |
| `setup` over Wi-Fi with no cable, on a device already paired with the Mac | iPhone, iOS 27.2 | Works |
| `info`, screenshots, app launch, tap, and Home on a locked device, from another country over a relayed Tailscale path | iPhone, iOS 27.2 | Work: an app opens over the lock screen and responds to touch |
| Screenshots, app launch, tap, swipe, and Home over a direct Tailscale path | iPad, iPadOS 17.7.11 | Works, 2–3 seconds per command |
| Tap, swipe, Home, and screenshots from another country over a relayed Tailscale path (DERP), after `export` and `import` | iPad, iPadOS 17.7.11 | Works: 8–17 seconds per command |
| Touch input in all four orientations | iPad, iPadOS 17.7.11 | Correct |
| Pairing a new computer directly over the network, with no existing trust | iPad, iPadOS 17.7.11 | Refused by iOS |
| Pairing a new computer through `lockdownd` over Tailscale or Wi-Fi, with no existing trust | iPad, iPadOS 17.7.11 | Refused by iOS: it withholds the key that pairing needs |
| Finding a device in Xcode tools after removing it from Xcode, with no cable | iPad, iPadOS 17.7.11 | Not found |

Not verified yet: an unlocked iPhone over a relayed path, swipes on iPhones, and first pairing without a cable.

## Requirements

- A device already paired with your Mac, as shown in Xcode or Device Hub
- macOS, the only platform tested so far
- Python 3.11 or newer, with `uv` or `pipx` to install the command
- An iPhone or iPad supported by `pymobiledevice3`, with Developer Mode on
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

## Set up

### Step 1: create this tool's pairing

With the device already paired with your Mac, put both on the same Wi-Fi or connect the cable, then run:

```sh
ios-remote setup home-ipad --host DEVICE-NAME.local
```

`setup` uses the trust your Mac already has to create a separate pairing for this tool, saves the device, and checks the connection. If several devices are visible, add `--udid DEVICE_IDENTIFIER`.

If `setup` finds no trusted device, the device is not paired with this Mac yet. See the first condition above.

### Step 2: switch to Tailscale

Turn on Tailscale on both devices, then give the tool the device's Tailscale name:

```sh
ios-remote set-host home-ipad ipad.example-tailnet.ts.net
ios-remote doctor --device home-ipad
```

From now on the device can be anywhere on your Tailnet.

### Step 3, optional: move the setup to another computer

```sh
ios-remote export home-ipad home-ipad.json
```

Copy the file over a private channel, then on the other computer:

```sh
ios-remote import home-ipad.json --host ipad.example-tailnet.ts.net
```

The file gives full control of the device. Delete it after importing, and never commit it or send it to an agent.

### Good to know

- Each device is stored in `~/.config/ios-remote-control/devices.json` with mode `0600`. Set `IOS_REMOTE_CONFIG` to use a different path.
- Pairing records are credentials and stay in `pymobiledevice3`'s data folder.
- iOS knows your computer by an identity derived from its hostname. Aliases made with this version save it, so pairing survives a rename. For an older alias, run `ios-remote add` again.
- Removing a device from Xcode also deletes the Mac's trust record, and this tool lost access too. On an iPad, no network route could restore it, so avoid doing this to a device you cannot reach in person.

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

The [command reference](plugins/ios-remote-control/skills/ios-remote-control/references/commands.md) describes every command, argument, output field, and error.

Tap and swipe coordinates are pixels in the current screenshot, in the orientation the screenshot shows. The CLI reads the display rotation from the device and converts the pixels to CoreDevice HID coordinates, which stay in the native orientation.

`info` also reports `orientation`, `rotation`, `backlight`, and `passcode_required`. `doctor` exits with status 1 unless the device is ready. Run commands one at a time: parallel screen captures can fail. Each command opens its own tunnel, which accounts for most of the time it takes.

For reliable automation, always use an observe-act-verify loop:

1. Capture a screenshot.
2. Inspect the current state and choose coordinates.
3. Perform one action.
4. Capture another screenshot and verify the result.

## When a person is still needed

The device can be controlled unattended only while it is paired, online, and unlocked. Someone has to be with it to:

- establish the first trust between the computer and the device;
- unlock it, because this tool does not enter a passcode. Other commands still work while it is locked, and an app can open over the lock screen and show its data, so treat a pairing like a key to the device;
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
