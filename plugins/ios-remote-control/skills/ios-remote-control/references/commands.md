# Command reference

Every command is `ios-remote COMMAND ...`. Run `ios-remote COMMAND --help` for the same details.

## Rules for all commands

- **Output:** each command prints one JSON object on one line, on stdout.
- **Exit codes:** `0` means success. `1` means the command failed and printed JSON with `status`, as below. `2` means the arguments were wrong, and argparse printed plain text to stderr.
- **Errors:** failures print `{"status": "error", "error": "explanation", "type": "ExceptionName"}`. `doctor` is the exception and has its own format.
- **One at a time:** run commands sequentially. Each one opens its own tunnel, and parallel screen captures can fail.
- **Time:** a command takes 2–4 seconds on a direct Tailscale path, and 8–17 seconds on a relayed one.
- **Coordinates:** pixels in the screenshot as displayed, with the origin at the top left. The range is `0..width-1` and `0..height-1`. The tool handles device rotation. If your viewer downscaled the image, convert back using the reported `width` and `height`.

## Check the device

### `doctor`

Checks that the alias exists, a pairing record exists, and the device answers. Start here.

```sh
ios-remote doctor --device ALIAS
```

| Argument | Required | Meaning |
| --- | --- | --- |
| `--device` | Yes | Saved device alias |

The result's `status` tells you what to do next:

| `status` | Exit code | Meaning | Next step |
| --- | --- | --- | --- |
| `ready` | 0 | Connected. `connection` holds the same fields as `info`. | Continue. |
| `needs_pairing` | 1 | No pairing record on this computer. `next` holds the command to run. | Run `setup` on a device already paired with this Mac. |
| `unreachable` | 1 | A record exists, but the connection failed. `error` and `error_type` explain why. | Check that the device is awake and Tailscale is running on it. |

An unknown alias prints the standard error format.

### `info`

Connects and reports the device's state.

```sh
ios-remote info --device ALIAS
```

| Argument | Required | Meaning |
| --- | --- | --- |
| `--device` | Yes | Saved device alias |

```json
{"orientation": "landscapeLeft", "rotation": 270, "backlight": "activeOn", "passcode_required": false, "alias": "ipad", "identifier": "DEVICE-ID", "product": "iPad7,5", "os": "17.7.11", "host": "HOST", "port": 49152}
```

| Field | Meaning |
| --- | --- |
| `orientation` | `portrait`, `portraitUpsideDown`, `landscapeLeft`, or `landscapeRight` |
| `rotation` | Interface rotation in degrees: 0, 90, 180, or 270 |
| `backlight` | Display state. `activeOn` means on and `off` means off. |
| `passcode_required` | `true` means the device is locked. Commands still run: see "On a locked device" below. |
| `alias`, `host`, `port` | The saved settings used for this connection |
| `identifier`, `product`, `os` | Device identifier, model, and OS version |

## Operate the device

These commands change what is on the device. Take a fresh screenshot before each one, and another afterwards to check the result: success only proves delivery. Someone else may be using the device.

### `screenshot`

Saves the current screen as a PNG. This does not change anything on the device.

```sh
ios-remote screenshot --device ALIAS /absolute/path/screen.png
```

| Argument | Required | Meaning |
| --- | --- | --- |
| `--device` | Yes | Saved device alias |
| `output` | Yes | PNG file to write. Missing folders are created. |

Prints `{"status": "saved", "path": "...", "width": 2048, "height": 1536}`. Screenshots can contain private information, so keep them local.

### `tap`

Touches one point.

```sh
ios-remote tap --device ALIAS X Y
```

| Argument | Required | Default | Meaning |
| --- | --- | --- | --- |
| `--device` | Yes | | Saved device alias |
| `x` | Yes | | Pixels from the left of the screenshot |
| `y` | Yes | | Pixels from the top of the screenshot |
| `--hold` | No | `0.08` | Seconds to keep the finger down. Must not be negative. |

Prints `{"status": "tapped", "x": 492.0, "y": 1389.0, "screen": [2048, 1536]}`. A coordinate off the screen is refused before any touch is sent.

### `swipe`

Drags one finger in a straight line.

```sh
ios-remote swipe --device ALIAS X1 Y1 X2 Y2
```

| Argument | Required | Default | Meaning |
| --- | --- | --- | --- |
| `--device` | Yes | | Saved device alias |
| `x1`, `y1` | Yes | | Start point, in screenshot pixels |
| `x2`, `y2` | Yes | | End point, in screenshot pixels |
| `--duration` | No | `0.6` | Seconds the swipe takes. Must be positive. |
| `--steps` | No | `30` | Touch updates along the path. Must be at least 1. |

Prints `{"status": "swiped", "from": [x1, y1], "to": [x2, y2], "screen": [width, height]}`.

On the home screen, a horizontal swipe changes pages. A swipe down opens Spotlight.

### `launch`

Opens an app.

```sh
ios-remote launch --device ALIAS com.apple.mobiletimer
```

| Argument | Required | Meaning |
| --- | --- | --- |
| `--device` | Yes | Saved device alias |
| `bundle_id` | Yes | App bundle identifier |

Prints `{"status": "launched", "bundle_id": "..."}`. An app that does not exist gives a `CoreDeviceError`. `com.apple.springboard` is refused, because launching it restarts the home screen.

### `home`

Presses the Home button. Use it to leave an app.

```sh
ios-remote home --device ALIAS
```

| Argument | Required | Meaning |
| --- | --- | --- |
| `--device` | Yes | Saved device alias |

Prints `{"status": "pressed", "button": "home"}`. If Spotlight is open, this may not close it. A swipe on the screen does. Tested on an iPad with a Home button, but not on a device without one.

### `unlock`

**DANGER ZONE.** A person types the passcode, and the tool enters it on the device once. An agent can start this command in the user's terminal, but must never ask for, see, type, or store the passcode.

```sh
ios-remote unlock --device ALIAS
```

| Argument | Required | Meaning |
| --- | --- | --- |
| `--device` | Yes | Saved device alias |

There is deliberately no passcode argument. The command works only at a real terminal: it asks the person to type `UNLOCK`, then reads the passcode at a hidden prompt.

| `status` | Meaning |
| --- | --- |
| `unlocked` | The device reports that it is unlocked. |
| `already_unlocked` | It was not locked, so nothing was typed. |

It refuses, without entering any digits, when:

- there is no terminal, such as when run by an agent's shell;
- the passcode is not numeric, or is not 4 to 16 digits long;
- the screen size has no measured keypad, or the device is not in portrait;
- a check of the screenshot does not find the keypad.

If the device is still locked after the attempt, the command reports an error and does not retry, because repeated wrong passcodes disable the device. Do not run it again without asking the user.

Codes of 4 or 6 digits submit themselves, and other lengths press the OK button after the last digit. The keys stop appearing in screenshots once typing starts, but they still work. Tested once with an 8-digit code on an iPhone with iOS 27.2 over Wi-Fi, not yet over Tailscale. Keypad layouts are measured per screen. Only 1290×2796 (iPhone 15 Pro Max) is included so far.

## On a locked device

Tested on an iPhone with iOS 27.2 from another country over a relayed Tailscale path. Without `unlock`, the tool cannot get past the lock. Everything else still reaches the device:

| Command | Screen off | Screen on |
| --- | --- | --- |
| `info`, `doctor` | Work | Work |
| `screenshot` | Works, but the image is black | Shows the screen |
| `launch` | Reports success. The app appears when the screen next wakes. | Opens the app over the lock screen |
| `tap`, `swipe` | Delivered, with no visible effect | **Work inside an app opened over the lock screen** |
| `home` | Wakes the screen | Can show the passcode screen, or turn the screen black |

**Opening an app this way can show its data while the device is locked.** In our test, Clock's alarms were visible and its tabs responded. Other apps have not been tried. Never use this to get into a user's private apps unless they ask for that exact thing, and never tap digits on a passcode screen.

## Set up a device

The device must already be paired with this Mac. See [devices.md](devices.md).

### `setup`

Creates this tool's pairing record, saves an alias, and checks the connection. Use this for a new device.

```sh
ios-remote setup ALIAS --host HOST
```

| Argument | Required | Default | Meaning |
| --- | --- | --- | --- |
| `name` | Yes | | Local alias for the device |
| `--host` | Yes | | Tailscale name, IP address, or other routable host |
| `--port` | No | `49152` | RemotePairing TCP port on the device |
| `--udid` | No | | Device to pair. Required only when several devices are visible. |
| `--skip-verify` | No | Off | Do not connect after saving. Use this when the host is not reachable yet. |

Prints `{"status": "configured", "device": "...", "host": "...", "port": 49152, "identifier": "...", "connection": {...}}`. `connection` holds the same fields as `info`, and is left out with `--skip-verify`.

The command waits up to 20 seconds for a device to appear, because devices on Wi-Fi drop in and out of the list. If it verifies and fails, the alias is already saved: fix the connection and run `doctor`.

### `pair`

Creates only the pairing record, without saving an alias. `pair-usb` is the older name for the same command. It works over any trusted connection, not only USB.

```sh
ios-remote pair
```

| Argument | Required | Meaning |
| --- | --- | --- |
| `--udid` | No | Device to pair. Required only when several devices are visible. |

Prints `{"status": "paired", "identifier": "..."}`.

### `add`

Saves an alias for a device that already has a pairing record. Running it again on an older alias also saves this computer's identity, so the pairing survives a change of hostname.

```sh
ios-remote add ALIAS --host HOST --identifier DEVICE-ID
```

| Argument | Required | Default | Meaning |
| --- | --- | --- | --- |
| `name` | Yes | | Local alias for the device |
| `--host` | Yes | | Tailscale name, IP address, or other routable host |
| `--identifier` | Yes | | RemotePairing identifier, normally the device UDID. See `list-pairs`. |
| `--port` | No | `49152` | RemotePairing TCP port on the device |
| `--host-id` | No | This computer's | Identity the pairing was made with. `export` and `import` handle this for you. |

Prints `{"status": "saved", "device": "...", "host": "...", "port": 49152}`.

### `set-host`

Changes a saved device's address. Use it to move from a local name to a Tailscale name.

```sh
ios-remote set-host ALIAS TAILSCALE-NAME
```

| Argument | Required | Meaning |
| --- | --- | --- |
| `name` | Yes | Saved device alias |
| `host` | Yes | New Tailscale name, IP address, or other routable host |

Prints `{"status": "saved", "device": "...", "host": "..."}`.

## Manage saved devices

### `list`

Reports saved aliases. Takes no arguments.

```sh
ios-remote list
```

Prints `{"devices": [{"name": "...", "host": "...", "port": 49152, "identifier": "...", "host_id": "..."}]}`.

### `list-pairs`

Reports the devices with a pairing record on this computer. Takes no arguments.

```sh
ios-remote list-pairs
```

Prints `{"identifiers": ["..."]}`.

### `remove`

Deletes an alias. The pairing record stays on disk, so `add` can restore the alias.

```sh
ios-remote remove ALIAS
```

| Argument | Required | Meaning |
| --- | --- | --- |
| `name` | Yes | Saved device alias |

Prints `{"status": "removed", "device": "..."}`.

## Move a setup to another computer

Do this only when the user asks. The file gives full control of the device: never display it, commit it, or send it anywhere except the user's other computer over a private channel. Delete it after importing.

### `export`

Writes a device's pairing and settings to one file, readable only by its owner.

```sh
ios-remote export ALIAS /absolute/path/device.json
```

| Argument | Required | Meaning |
| --- | --- | --- |
| `name` | Yes | Saved device alias |
| `output` | Yes | File to write |

Prints `{"status": "exported", "device": "...", "path": "...", "warning": "this file gives control of the device"}`.

### `import`

Installs a file made by `export`. The new computer can then control the device, without pairing it again.

```sh
ios-remote import /absolute/path/device.json --host TAILSCALE-NAME
```

| Argument | Required | Default | Meaning |
| --- | --- | --- | --- |
| `path` | Yes | | File made by `export` |
| `--name` | No | Original alias | Save under this alias instead |
| `--host` | No | Original host | Reach the device at this address |
| `--force` | No | Off | Replace a different pairing for this device. Ask the user first. |

Prints `{"status": "imported", "device": "...", "host": "...", "port": 49152}`.

## Files and settings

| What | Where |
| --- | --- |
| Saved aliases | `~/.config/ios-remote-control/devices.json`, mode `0600`. Set `IOS_REMOTE_CONFIG` to use another file, or `XDG_CONFIG_HOME` to change the base folder. |
| Pairing records | `~/.pymobiledevice3/remote_IDENTIFIER.plist`. These give control of the device, so never display or copy them. |

## Common errors

| Message or type | Meaning | What to do |
| --- | --- | --- |
| `no local RemotePairing record` | This computer has no pairing record for the device. | Run `setup`, or `import` from a computer that has one. |
| `the RemotePairing record was rejected` | The device does not accept this record. The computer's name may have changed, or the record may come from another computer. | Run `add` with `--host-id` from the original computer's `list`, or use `export` and `import`. Otherwise run `pair`. |
| `ConnectionTerminatedError` | The device closed the connection immediately. It usually no longer trusts this computer, for example after being removed from Xcode or Device Hub. | Ask the user to pair it again. See [devices.md](devices.md). |
| `TimeoutError`, or `connection timed out` | The device did not answer. | Check that it is awake and that Tailscale is running on it. |
| `no trusted iPhone or iPad found` | `setup` or `pair` can see no paired device. | Ask the user to pair it. See [devices.md](devices.md). |
| `multiple devices found` | Several devices are visible. | Add `--udid` with one of the listed identifiers. |
| `coordinate ... is outside` | The point is off the screen. | Take a new screenshot. The device may have rotated. |
| `device reports rotation` | The rotation changed during the command. | Try again. |
