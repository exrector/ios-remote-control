---
name: ios-remote-control
description: Inspect and operate a paired physical iPhone or iPad over a directly routable hostname or IP address, including Tailscale. Use for screenshots, launching apps, taps, and swipes on a real remote iOS device; not for Simulator automation.
---

# iOS Remote Control

Use the `ios-remote` CLI. It connects directly to a previously paired device and creates its own rootless userspace tunnel.

## Connect

Start with `ios-remote list`, then check the selected alias with:

```sh
ios-remote doctor --device ALIAS
```

Developer Mode is necessary but does not establish trust. If the device is not configured or lacks a RemotePairing record, connect and unlock it over USB and run:

```sh
ios-remote setup ALIAS --host HOST
```

This uses the single connected USB device, bootstraps RemotePairing, stores the alias, and verifies the remote path. If several USB devices are connected, select one with `--udid`. Never display or copy a pairing record. Do not attempt network autopairing as a substitute for initial trust.

## Operate

Use an observe-act-verify loop:

```sh
ios-remote screenshot --device ALIAS /absolute/path/before.png
ios-remote launch --device ALIAS com.example.app
ios-remote tap --device ALIAS X Y
ios-remote swipe --device ALIAS X1 Y1 X2 Y2
ios-remote screenshot --device ALIAS /absolute/path/after.png
```

Coordinates are pixels in the most recent screenshot. Inspect a fresh screenshot before selecting them. Perform one UI action at a time and verify the result with another screenshot. A successful command only proves delivery; the screenshot proves the UI outcome.

Treat launching an app or manipulating its UI as a device mutation requiring the user's authorization. Do not type secrets, approve purchases, change accounts, install profiles, delete data, or alter security settings unless the user explicitly requests that exact action.

Screenshots can contain private information. Keep them local, use temporary or user-approved output paths, and do not publish them.

## Diagnose

- `ios-remote doctor --device ALIAS` reports whether configuration, pairing, and connectivity are ready.
- `ios-remote info --device ALIAS` checks the complete RemotePairing and RSD path.
- A connection failure usually means the device is asleep/offline, the host or port is stale, Tailscale has no route, or the RemotePairing record is missing.
- Do not replace direct IP routing with public port forwarding. Prefer a private Tailnet or equivalent trusted network.
- If pairing has gone stale, reconnect over USB and run `ios-remote pair-usb`; do not delete existing pairing records without explicit approval.
