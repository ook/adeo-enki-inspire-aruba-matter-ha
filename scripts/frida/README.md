# Frida scripts — open a second-admin commissioning window

These scripts drive the official Enki Android app, through its own official
(unobfuscated) Android CHIP SDK, to open a Matter Enhanced Commissioning (ECM)
window on a fan the app already administers — so a **second** controller (e.g.
Home Assistant's `matter-server`) can join it over IP. This is Matter's
standard multi-admin flow; it is *not* an exploit (see the "Commissioning"
section of the main [README](../../README.md)).

## Files

- **`open_commissioning_window.js`** — the one you run. Attaches to the live
  controller in the Enki app, establishes a CASE session to the target fan, and
  opens an ECM window with a passcode/discriminator *you* choose; the success
  callback prints a standard Matter manual pairing code + QR payload.
- **`find_controller.js`** — fallback only. If a future app update obfuscates
  the controller class, this locates it by its JNI-bound method names; set
  `CTRL_CLASS` in `open_commissioning_window.js` accordingly.

## Prerequisites

- Rooted Android phone; `frida-server` (matching your `frida` client version)
  running as root.
- Enki app signed into your account, with the fan **commissioned by this app
  instance** (so it is the fabric admin for that device).
- On a machine on the same L2 segment: `matter-server` / Home Assistant ready
  to add a Matter device.

## Steps

1. Commission a fan from the Enki app on the rooted phone (that app instance
   becomes the Matter fabric admin for the device).
2. Get the fan's node ID from its operational mDNS record:
   ```bash
   avahi-browse -rt _matter._tcp
   # instance is "<compressed-fabric-id>-<NODE_ID>"; take NODE_ID (2nd hex group)
   ```
3. Edit `open_commissioning_window.js`: set `NODE_ID` (and, if you like,
   `PASSCODE` / `DISCRIMINATOR` — they default to the public test vector
   `20202021` / `3840`).
4. Open the fan's detail page in Enki (establishes a live CASE session), then
   attach Frida (attach, do **not** spawn):
   ```bash
   frida-ps -U | grep -i enki            # note the PID
   frida -U -p <PID> -l open_commissioning_window.js
   ```
   Expected:
   ```
   [+] ChipDeviceController found -> getConnectedDevicePointer(...) ...
   [+] CASE established, devicePtr=...
   [+] COMMISSIONING WINDOW OPEN (300s)
       manual pairing code : 34970112332
   ```
5. Confirm the window is open (on the controller host):
   ```bash
   avahi-browse -rt _matterc._udp        # the fan should appear, CM=2 D=3840
   ```
6. In Home Assistant: **Add Matter device → enter code manually**, and type the
   manual pairing code from step 4.

## Notes

- Use the `...Callback` overload (`openPairingWindowWithPINCallback`). The
  non-callback `openPairingWindowWithPIN` returns `true` without actually
  opening a window — its real result is only delivered via the callback.
- The controller class was **not** obfuscated at the time of testing
  (`chip.devicecontroller.ChipDeviceController`), so `find_controller.js` is
  only insurance against future app updates.
- The fan stays in the Enki app too (multi-admin) — you don't lose the original
  pairing.

## Helper

`../matter_setupcode.py` builds/decodes Matter manual pairing codes and `MT:`
QR payloads (useful to recompute the code for your chosen passcode/discriminator,
or to sanity-check one).
