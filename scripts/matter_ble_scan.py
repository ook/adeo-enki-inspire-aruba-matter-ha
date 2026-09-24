#!/usr/bin/env python3
"""Scan for Matter devices advertising a commissionable BLE beacon.

A Matter-over-Wi-Fi device in commissioning mode broadcasts a BLE
advertisement carrying service UUID 0xFFF6, whose payload (8 bytes) contains
the discriminator, VID and PID. This tool scans, filters to Matter only, and
decodes them.

Used here to establish that the Inspire Aruba fans do NOT advertise over BLE
(nothing shows up even on a fresh boot right next to the scanner), which is
what pointed to Wi-Fi PAF as their commissioning transport.

    pip install bleak
    python3 matter_ble_scan.py                       # plain scan
    python3 matter_ble_scan.py --expect-short 15     # + match a short discriminator

Ref: Matter Core Spec 5.4.2.5.6 (Commissionable BLE advertisement).
"""

import argparse
import asyncio
from bleak import BleakScanner

MATTER_SVC = "0000fff6-0000-1000-8000-00805f9b34fb"

def decode(sd: bytes):
    # byte 0: opcode (0x00 = commissionable)
    # bytes 1-2: u16 LE -> bits 0-11 discriminator, bits 12-15 version
    # bytes 3-4: VID (LE); bytes 5-6: PID (LE); byte 7: flags
    if len(sd) < 7:
        return None
    disc = int.from_bytes(sd[1:3], "little") & 0x0FFF
    vid = int.from_bytes(sd[3:5], "little")
    pid = int.from_bytes(sd[5:7], "little")
    return disc, vid, pid

async def main(expect_short):
    seen = {}
    def cb(dev, adv):
        sd = adv.service_data.get(MATTER_SVC)
        if not sd:
            return
        d = decode(bytes(sd))
        if not d or dev.address in seen:
            return
        disc, vid, pid = d
        seen[dev.address] = disc
        short = disc >> 8
        print(f"[MATTER] {dev.address}  RSSI={adv.rssi}dBm  "
              f"discriminator={disc} (0x{disc:03X}, short={short})  "
              f"VID=0x{vid:04X} PID=0x{pid:04X}")
        if expect_short is not None:
            ok = (short == expect_short)
            print(f"         -> matches expected short discriminator ({expect_short}): "
                  f"{'YES' if ok else 'no'}")

    print("Scanning for commissionable Matter BLE devices... (Ctrl-C to stop)")
    scanner = BleakScanner(detection_callback=cb)
    await scanner.start()
    try:
        await asyncio.sleep(3600)
    finally:
        await scanner.stop()

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--expect-short", type=int, default=None,
                    help="expected short (4-bit) discriminator, e.g. 15 for test vector 3497-011-2332")
    a = ap.parse_args()
    try:
        asyncio.run(main(a.expect_short))
    except KeyboardInterrupt:
        print("\nstopped.")
