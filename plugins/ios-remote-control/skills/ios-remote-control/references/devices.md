# Devices, systems, and connections

Read this before trying to connect a device. Do not experiment with pairing: it only works in the ways listed here.

## What this tool supports

| Device | Minimum system | Status |
| --- | --- | --- |
| iPad | iPadOS 17 | **Tested in full** on iPadOS 17.7.11: screenshots, touch in all four orientations, app launch, Home, and control over Tailscale. |
| iPhone | iOS 17 | **Tested** on iOS 27.2: `setup`, `info`, screenshots, app launch, tap, Home, and `export`/`import`, from another country over Tailscale. Tested on a locked device only. Swipes and an unlocked device are not tested. |
| iPhone or iPad on iOS 16 or earlier | | **Not supported.** This tool needs CoreDevice, which starts at iOS 17. |
| Apple Watch, Apple TV, Apple Vision Pro | | **Not supported or tested.** They can pair with a Mac, as below, but this tool has not been made to work with them. |

The computer must be a Mac. That is the only platform tested.

Between iOS 17.0 and 17.3.1, `pymobiledevice3` reaches devices differently than on 17.4 and later. These versions are not tested.

## First pairing with a Mac

This is the step a person must do. **This tool cannot do it, and iOS refuses it from a program over the network.**

| Device | System | By cable | Without a cable |
| --- | --- | --- | --- |
| iPhone, iPad | iOS or iPadOS 27 and later | Yes | Yes, on the same Wi-Fi |
| iPhone, iPad | iOS or iPadOS 26 and earlier | Yes | **No** |
| Apple Watch | Companion iPhone comes first | Through the paired iPhone | watchOS 27 and later |
| Apple TV | tvOS | Not described by Apple | Yes, on the same Wi-Fi with IPv6, using a PIN |
| Apple Vision Pro | visionOS | Not described by Apple | Yes, on the same Wi-Fi with IPv6, using a PIN |

Apple's wording: "Upgrade your iPhone or iPad to iOS or iPadOS 27 or later to wirelessly pair it; otherwise, use a cable."

The first pairing always needs someone at the device, because it has to be confirmed there.

### By cable

1. Connect the device to the Mac.
2. If **Trust This Computer** appears on the device, tap **Trust**.
3. In Device Hub, select the device. If a **Pair** button appears, click it.
4. Turn on Developer Mode if asked.

Open Device Hub from Xcode with **Xcode > Open Developer Tool > Device Hub**.

### Without a cable: iPhone or iPad on iOS 27 and later

1. Put the device on the same Wi-Fi as the Mac.
2. In Device Hub, choose **File > Pair Nearby Device…**, and choose the device type.
3. On the device, open **Settings > Privacy & Security > Developer Mode**. Developer Mode may only appear there after you start pairing.
4. Tap **Trust** when asked.

We have not completed this route ourselves.

### Apple Watch

1. Pair the companion iPhone first.
2. Turn on Developer Mode on both the iPhone and the watch.
3. Tap **Trust** on both.

For Series 5 or older, the Mac must be on the same Bonjour-compatible Wi-Fi as the watch.

### Apple TV and Apple Vision Pro

1. Make sure the Wi-Fi network has IPv6 enabled.
2. Open the pairing screen on the device:
   - tvOS: **Settings > Remotes and Devices > Remote App and Devices**
   - visionOS: **Settings > General > Remote Devices**
3. In Device Hub, choose **File > Pair Nearby Device…**, select the device, and enter the PIN it shows.

tvOS has no Developer Mode.

## After pairing

| Tool | How it connects | Network needed |
| --- | --- | --- |
| Xcode and Device Hub | Find the device with Bonjour | Same Wi-Fi with IPv6, or a cable |
| This tool | Connects directly to the device's address | Any route to it, including Tailscale from anywhere |

So the order is:

1. A person pairs the device with the Mac, as above.
2. `ios-remote setup`, on the same network or by cable, creates this tool's own pairing record. It uses the Mac's trust and shows nothing on the device.
3. `ios-remote set-host` switches to the Tailscale name. The device can then be anywhere on the Tailnet.

## What breaks a pairing

- **Removing the device from Xcode or Device Hub.** On our iPad this also made it refuse this tool, and it needed a cable to recover. Never do this to a device out of reach.
- **Updating the device's system.** Apple says the device has to be paired again afterwards.
- **Changing the Mac's name.** Aliases saved by current versions of this tool are protected from this.
- **VPN software on the Mac** can block Xcode's connection to a cabled device. See Apple's TN3158.

## When a person is needed

| Situation | Why |
| --- | --- |
| First pairing | iOS requires it to be confirmed at the device |
| Unlocking the device | The owner must type the passcode, either on the device or through `ios-remote unlock` at a terminal. An agent never handles it. `info` reports `passcode_required`. |
| Touch ID or Face ID prompt | Touch input cannot satisfy it |
| Tailscale stopped on the device, or the device restarted | The device has no route until Tailscale runs again |

## Security: a pairing works on a locked device

Whoever holds a pairing record can read the device's state and take screenshots while it is locked. They can also open an app over the lock screen and use it by touch, which can expose that app's data. In our test, this worked on Clock on iOS 27.2. Other apps have not been tried.

Treat the pairing record and `export` files like a key to the device. Turning off Developer Mode stops these services, according to Apple's description of what it protects, but we have not tested this.

## What was tried and refused

Do not repeat these on a device that does not trust the Mac. On iPadOS 17.7.11 each failed over both Tailscale and Wi-Fi:

- Direct RemotePairing from a new computer: the device closes the connection.
- `lockdownd` pairing: the device withholds the key that pairing needs.
- `devicectl manage pair` by address or name: the device is not found.

## Sources

Read on 2 November 2026.

- [Managing your simulated and physical devices in Device Hub](https://developer.apple.com/documentation/xcode/managing-your-simulated-and-physical-devices-in-device-hub) (Apple)
- [Enabling Developer Mode on a device](https://developer.apple.com/documentation/xcode/enabling-developer-mode-on-a-device) (Apple)
- [TN3158: Resolving Xcode 15 device connection issues](https://developer.apple.com/documentation/technotes/tn3158-resolving-xcode-15-device-connection-issues) (Apple)
- [iOS 17+ tunnels guide](https://doronz88.github.io/pymobiledevice3/guides/ios17-tunnels/) (pymobiledevice3)
- [RemoteXPC notes](https://github.com/doronz88/pymobiledevice3/blob/master/misc/RemoteXPC.md) (pymobiledevice3)
