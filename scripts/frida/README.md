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

- Rooted Android phone with `frida-server` **matching your `frida` client
  version** running as root (see below — it does not survive a reboot).
- Enki app signed into your account, with the fan **commissioned by this app
  instance** (so it is the fabric admin for that device), and **that same Enki
  process still running** — see the key rule below.
- On a machine on the same L2 segment: `matter-server` / Home Assistant ready
  to add a Matter device.

### Starting frida-server

`frida-server` must run on the phone with the **same version** as your desktop
`frida` client, and it does **not** persist across reboots — relaunch it each
session.

```sh
frida --version                      # note the version, e.g. 17.18.0

# One-time: push a matching server. Download frida-server-<VER>-android-arm64.xz
# from https://github.com/frida/frida/releases (android-arm64, NOT linux-arm64), then:
unxz frida-server-<VER>-android-arm64.xz
adb push frida-server-<VER>-android-arm64 /data/local/tmp/frida-server
adb shell su -c 'chmod 755 /data/local/tmp/frida-server'

# Each session: launch it as root, detached. The redirection matters: without
# it, adb keeps the session open (the daemon still holds its stdout/stderr) and
# the command never returns.
adb shell "su -c '/data/local/tmp/frida-server -D >/dev/null 2>&1'"
# If your ROM kills it, use setsid instead:
#   adb shell su -c "setsid /data/local/tmp/frida-server >/dev/null 2>&1 &"

# Verify from the desktop (also gives you the live Enki PID)
frida-ps -U | grep -i enki
```

Troubleshooting:

- `unable to connect to remote frida-server: closed` → the server is not
  running; relaunch it with the commands above.
- `Unable to start: Error binding to address 127.0.0.1:27042: Address already
  in use` → it is already running; nothing to do.
- `/system/bin/sh: /data/local/tmp/frida-server: No such file or directory`
  although the push succeeded → you pushed the `linux-arm64` build. It needs
  glibc's loader, which Android doesn't have; push `android-arm64` instead.
- Several phones plugged in (`adb: more than one device`) → target the rooted
  one explicitly: `export ANDROID_SERIAL=<serial from adb devices>` (or
  `adb -s <serial>`) for adb, and `-D <serial>` instead of `-U` for
  `frida` / `frida-ps`.

## Key rule: commission, then Frida — in the same Enki process

Enki only keeps a live `ChipDeviceController` **right after it has commissioned
a device**. Day-to-day control of an already-paired fan does not go through it:
in a freshly (re)started Enki the class is loaded but there are **0 instances**,
and nothing brings one back — opening the fan's page, changing its speed,
cycling Wi-Fi, hooking `getConnectedDevicePointer`, or spawning with `-f`.

So: commission the fan in Enki, then attach Frida **without closing, swiping
away or force-stopping Enki in between** (the PID must not change). If the
process is gone, the only known way back is to remove the fan from Enki
(or factory-reset it) and commission it again.

Quick go/no-go check before attaching — while the controller is alive, the
phone itself advertises operationally:

```sh
avahi-browse -rt _matter._tcp | grep -A4 Android_
```

- An `Android_<hex>.local` record (instance `<FABRIC>-000000000001B669`,
  `txt=["T=2"]`) → controller alive → go.
- No such record → no live controller; `open_commissioning_window.js` will
  report "No live instance". Re-commission instead of retrying.

## Steps

1. Commission a fan from the Enki app on the rooted phone (that app instance
   becomes the Matter fabric admin for the device). **Leave Enki running** from
   now until step 6.
2. Find the fan's node ID **as the Enki app's fabric knows it**:
   ```bash
   avahi-browse -rt _matter._tcp
   ```
   Each record's instance name is `<compressed-fabric-id>-<NODE_ID>` (two
   16-hex groups). Three traps:
   - A device commissioned into several fabrics appears **once per fabric**,
     with the **same hostname/IP but a different NODE_ID each time** — the
     node ID is fabric-specific, not a property of the device.
   - `000000000001B669` (= 112233) is the **default controller node ID**;
     both the Enki app and HA's `matter-server` use it, so it does **not**
     identify a fabric.
   - The Enki fabric is the one the phone advertises under while its
     controller is alive (see the key rule): its record is
     `<FABRIC>-000000000001B669` on hostname `Android_<hex>.local`.

   So: take the `<FABRIC>` prefix of the `Android_…` record, then the **fan**
   record with the same prefix (hostname is a device MAC such as
   `AABBCCDDEEFF.local`, LAN IP, `txt=["="]`) — its 2nd group is your
   `NODE_ID`. No `Android_…` record → stop and re-read the key rule. If several
   fan records still qualify, step 4 tells you which one is right, with no
   guessing.
3. Edit `open_commissioning_window.js`: set `NODE_ID` to a candidate (and, if
   you like, `PASSCODE` / `DISCRIMINATOR` — they default to the public test
   vector `20202021` / `3840`).
4. Attach Frida to the **same** Enki process that commissioned the fan
   (attach, do **not** spawn — the PID must be unchanged since step 1):
   ```bash
   frida-ps -U | grep -i enki            # note the PID
   frida -U -p <PID> -l open_commissioning_window.js
   ```
   The script drives the Enki controller, which only knows the fan under
   **its own** fabric's node ID — so a candidate is self-verifying:
   - `[+] CASE established ...` → correct node ID (the Enki fabric); continue.
   - `[!] connection failure ...` → wrong candidate; set `NODE_ID` to the next
     one and re-run.

   Success looks like:
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
- `[!] No live ... instance`: the Enki process that commissioned the fan is
  gone (app closed, phone rebooted, crash). See the key rule — re-commission.
- Do **not** hook the controller's constructor (`$init`) to catch an instance:
  it crashes Enki (SIGSEGV in the ART heap).
- The script can be re-run in the same Enki process (e.g. after the 300 s
  window expires): its Java callback classes get unique names on each run.

## Helper

`../matter_setupcode.py` builds/decodes Matter manual pairing codes and `MT:`
QR payloads (useful to recompute the code for your chosen passcode/discriminator,
or to sanity-check one).
