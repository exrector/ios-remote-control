# iOS Remote Control

Control a paired physical iPhone or iPad over any routable IP connection, including Tailscale. The CLI creates a rootless userspace RemoteXPC tunnel and exposes an agent-friendly command set for screenshots, app launching, taps, and swipes.

This project is a thin orchestration layer over [pymobiledevice3](https://github.com/doronz88/pymobiledevice3). It does not reimplement Apple's pairing or CoreDevice protocols.

## What it solves

Apple's normal tooling discovers devices on the local network with Bonjour. That discovery does not cross most routed networks. `ios-remote-control` skips Bonjour after pairing and connects directly to the device's reachable hostname or IP address.

### What has been verified

| Test | Device | Result |
| --- | --- | --- |
| Pairing with no cable, on the same Wi-Fi, on a device the Mac already trusts | iPhone, iOS 27.2 | Works |
| `info` and screenshots on a locked screen, on the same Wi-Fi | iPhone, iOS 27.2 | Works |
| Moving the setup to a new home folder and hostname with `export` and `import` | iPhone, iOS 27.2 | Works |
| Screenshots, app launch, tap, swipe, and Home over a direct Tailscale path | iPad, iPadOS 17.7.11 | Works, 2–3 seconds per command |
| Commands from another country over a relayed Tailscale path (DERP) | iPad, iPadOS 17.7.11 | Works, about 9 seconds per command |
| Touch input in all four orientations | iPad, iPadOS 17.7.11 | Correct |
| Pairing a new computer directly over the network, with no existing trust | iPad, iPadOS 17.7.11 | Refused by iOS |
| Pairing a new computer through `lockdownd` over Tailscale, with no existing trust | iPad, iPadOS 17.7.11 | Refused by iOS: it withholds the key that pairing needs |
| Finding a device in Xcode tools after removing it from Xcode, with no cable | iPad, iPadOS 17.7.11 | Not found |

Not verified yet: an iPhone over Tailscale, touch input on iPhones, and `export`/`import` between two physical computers with this release.

## Requirements

- macOS, the only platform tested so far
- Python 3.11 or newer, with `uv` or `pipx` to install the command
- An iPhone or iPad supported by `pymobiledevice3`, with Developer Mode on
- A Mac that already trusts the device, as shown in Xcode under **Window > Devices and Simulators**
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

### Step 1: pair on the same network

Put the computer and the device on the same Wi-Fi. Tailscale is not needed yet. If Xcode already shows the device as paired, no cable is needed:

```sh
ios-remote setup home-ipad --host DEVICE-NAME.local
```

`setup` uses the trust your Mac already has to create a separate pairing for this tool, saves the device, and checks the connection. If several devices are visible, add `--udid DEVICE_IDENTIFIER`.

If `setup` finds no trusted device, pair it in Xcode first. Trust has to be established with someone at the device: iOS refuses a new computer that asks directly over the network. On iPadOS 17.7 every network route we tried was refused, so expect to need a cable once. `pymobiledevice3` documents a no-cable way for iOS 27, using a code in **Settings > Developer > Paired Macs**, but in our one test the computer did not appear on the device.

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
- Removing a device from Xcode can also cut off this tool. This happened on an iPad, so pair it again before relying on it.

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

- establish the first trust between the computer and the device;
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
