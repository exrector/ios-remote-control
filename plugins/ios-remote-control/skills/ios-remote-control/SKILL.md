---
name: ios-remote-control
description: Inspect and operate a paired physical iPhone or iPad over a directly routable hostname or IP address, including Tailscale. Use for screenshots, launching apps, taps, and swipes on a real remote iOS device; not for Simulator automation.
---

# iOS Remote Control

Use the `ios-remote` CLI. It connects directly to a previously paired device and creates its own rootless userspace tunnel.

## Install the CLI

Check for the command first:

```sh
command -v ios-remote
```

If it is missing, ask the user before installing, then run:

```sh
uv tool install git+https://github.com/exrector/ios-remote-control
```

If `uv` is not available, `pipx install git+https://github.com/exrector/ios-remote-control` works too. If neither is present, tell the user what to install rather than installing a package manager yourself.

## Connect

Start with `ios-remote list`, then check the selected alias with:

```sh
ios-remote doctor --device ALIAS
```

**The device must already be paired with the user's Mac.** This tool cannot create the first pairing, and neither can you: do not try. Check this first, in Xcode or Device Hub, and if it is not paired, ask the user to pair it. On iPadOS 17.7 that means a cable. Never remove a device from Xcode or Device Hub: it deletes the trust this tool depends on.

Developer Mode is necessary but does not establish trust. If the paired device has no RemotePairing record, connect it by cable or put the computer and device on the same Wi-Fi, then run:

```sh
ios-remote setup ALIAS --host DEVICE-NAME.local
```

This uses the trust the Mac already has to create the record, stores the alias, and verifies the connection. If several devices are visible, select one with `--udid`. If none is found, the device is not paired with this Mac yet, so ask the user to pair it. A new computer cannot pair directly over the network: iOS closes the connection.

Then switch to the device's Tailscale name:

```sh
ios-remote set-host ALIAS TAILSCALE-NAME
```

To control the device from another computer, use `ios-remote export ALIAS FILE` and, on that computer, `ios-remote import FILE --host TAILSCALE-NAME`. Do this only when the user asks. The file gives full control of the device: never display it, commit it, or leave it behind.

## Operate

Use an observe-act-verify loop:

```sh
ios-remote screenshot --device ALIAS /absolute/path/before.png
ios-remote launch --device ALIAS com.example.app
ios-remote home --device ALIAS
ios-remote tap --device ALIAS X Y
ios-remote swipe --device ALIAS X1 Y1 X2 Y2
ios-remote screenshot --device ALIAS /absolute/path/after.png
```

Coordinates are pixels in the most recent screenshot, as it is displayed; the CLI handles device rotation. If your image viewer downscaled the screenshot, convert back using the `width` and `height` the command reported. Inspect a fresh screenshot before selecting them. Run commands one at a time. Each one opens a new tunnel, which takes a few seconds on a direct path and around ten on a relayed one. Perform one UI action at a time and verify the result with another screenshot. A successful command only proves delivery; the screenshot proves the UI outcome.

Someone may be using the device while you work. Take a fresh screenshot before each action, because the screen may have changed.

To leave an app, use `ios-remote home`. Never launch `com.apple.springboard`: it restarts the home screen, and the CLI refuses it.

Treat launching an app or manipulating its UI as a device mutation requiring the user's authorization. Do not type secrets, approve purchases, change accounts, install profiles, delete data, or alter security settings unless the user explicitly requests that exact action.

Screenshots can contain private information. Keep them local, use temporary or user-approved output paths, and do not publish them.

## Diagnose

- `ios-remote doctor --device ALIAS` reports whether configuration, pairing, and connectivity are ready, and exits with status 1 otherwise.
- `ios-remote info --device ALIAS` checks the complete RemotePairing and RSD path and reports orientation, backlight, and `passcode_required`.
- A locked device, a Touch ID or Face ID prompt, or a device that was rebooted needs a person. Report this to the user; do not try to get around it.
- A connection failure usually means the device is asleep/offline, the host or port is stale, Tailscale has no route, or the RemotePairing record is missing.
- Do not replace direct IP routing with public port forwarding. Prefer a private Tailnet or equivalent trusted network.
- "The RemotePairing record was rejected" can mean this computer's name changed or the record came from another computer. Use `ios-remote export` and `ios-remote import` to move a setup. If that does not help, run `ios-remote pair` while the Mac trusts the device. Do not delete existing pairing records without explicit approval.
- Removing a device from Xcode can also cut off this tool. Tell the user before suggesting it.
