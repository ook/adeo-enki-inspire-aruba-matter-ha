#!/usr/bin/env python3
"""Build (and decode) Matter onboarding codes.

From a setup passcode (27-bit) and discriminator (12-bit), produce:
  - the 11-digit manual pairing code (what you type into a controller such as
    Home Assistant's "add device manually"),
  - the "MT:..." QR onboarding payload (needs VID/PID as well).

Can also decode an "MT:..." payload for cross-checking.

No dependencies (stdlib only).

Refs: Matter Core Specification, section 5.1.3 (Onboarding Payload / QR) and
5.1.4 (Manual Pairing Code).
"""

import argparse
import sys

# -- Base38 (alphabet and direction fixed by the Matter spec) ---------------
B38 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-."

def base38_encode(data: bytes) -> str:
    out = []
    i = 0
    while i < len(data):
        chunk = data[i:i + 3]
        if len(chunk) == 3:
            val = chunk[0] | (chunk[1] << 8) | (chunk[2] << 16); n = 5
        elif len(chunk) == 2:
            val = chunk[0] | (chunk[1] << 8); n = 4
        else:
            val = chunk[0]; n = 2
        for _ in range(n):
            out.append(B38[val % 38]); val //= 38
        i += 3
    return "".join(out)

def base38_decode(s: str) -> bytes:
    out = bytearray()
    i = 0
    while i < len(s):
        chunk = s[i:i + 5]
        if len(chunk) == 5: nbytes = 3
        elif len(chunk) == 4: nbytes = 2
        elif len(chunk) == 2: nbytes = 1
        else: raise ValueError("invalid base38 length")
        val = 0
        for c in reversed(chunk):
            val = val * 38 + B38.index(c)
        for _ in range(nbytes):
            out.append(val & 0xFF); val >>= 8
        i += 5
    return bytes(out)

# -- Verhoeff check digit for the manual code -------------------------------
_D = [[0,1,2,3,4,5,6,7,8,9],[1,2,3,4,0,6,7,8,9,5],[2,3,4,0,1,7,8,9,5,6],
      [3,4,0,1,2,8,9,5,6,7],[4,0,1,2,3,9,5,6,7,8],[5,9,8,7,6,0,4,3,2,1],
      [6,5,9,8,7,1,0,4,3,2],[7,6,5,9,8,2,1,0,4,3],[8,7,6,5,9,3,2,1,0,4],
      [9,8,7,6,5,4,3,2,1,0]]
_P = [[0,1,2,3,4,5,6,7,8,9],[1,5,7,6,2,8,3,0,9,4],[5,8,0,3,7,9,6,1,4,2],
      [8,9,1,6,0,4,3,5,2,7],[9,4,5,3,1,2,6,8,7,0],[4,2,8,6,5,7,3,9,0,1],
      [2,7,9,3,8,0,6,4,1,5],[7,0,4,6,9,1,3,2,5,8]]
_INV = [0,4,3,2,1,5,6,7,8,9]

def verhoeff_check(number: str) -> str:
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _D[c][_P[(i + 1) % 8][int(ch)]]
    return str(_INV[c])

def verhoeff_valid(number: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0

# -- Validation -------------------------------------------------------------
INVALID_PASSCODES = {
    0, 11111111, 22222222, 33333333, 44444444, 55555555, 66666666,
    77777777, 88888888, 99999999, 12345678, 87654321,
}

def check_inputs(passcode: int, discriminator: int):
    if not (1 <= passcode <= 0x7FFFFFF) or passcode in INVALID_PASSCODES:
        raise ValueError(f"invalid passcode ({passcode}): out of range or trivial")
    if not (0 <= discriminator <= 0xFFF):
        raise ValueError(f"invalid discriminator ({discriminator}): must be 0..4095")

# -- Manual pairing code (11 digits) ----------------------------------------
def manual_code(passcode: int, discriminator: int, vid_pid_present: bool = False) -> str:
    check_inputs(passcode, discriminator)
    short = (discriminator >> 8) & 0xF          # short discriminator = top 4 bits
    disc_msb = short >> 2
    disc_lsb = short & 0x3
    pin_lsb = passcode & 0x3FFF                 # low 14 bits
    pin_msb = (passcode >> 14) & 0x1FFF         # high 13 bits
    chunk1 = ((1 if vid_pid_present else 0) << 2) | disc_msb   # 3 bits -> 1 digit
    chunk2 = pin_lsb | (disc_lsb << 14)                        # 16 bits -> 5 digits
    chunk3 = pin_msb                                           # 13 bits -> 4 digits
    body = f"{chunk1:d}{chunk2:05d}{chunk3:04d}"               # 10 digits
    return body + verhoeff_check(body)                         # + check digit -> 11

def group_manual(code: str) -> str:
    return f"{code[0:4]}-{code[4:7]}-{code[7:11]}"

def decode_manual(code: str) -> dict:
    code = "".join(ch for ch in code if ch.isdigit())
    if len(code) != 11:
        raise ValueError("manual pairing code must be 11 digits")
    ok = verhoeff_valid(code)
    c1 = int(code[0]); c2 = int(code[1:6]); c3 = int(code[6:10])
    passcode = (c2 & 0x3FFF) | (c3 << 14)
    short_disc = ((c1 & 0x3) << 2) | ((c2 >> 14) & 0x3)
    return {"verhoeff_ok": ok, "vid_pid_present": c1 >> 2,
            "short_discriminator": short_disc, "passcode": passcode}

# -- QR onboarding payload ("MT:...") ---------------------------------------
def qr_payload(passcode: int, discriminator: int, vid: int, pid: int,
               disc_caps: int = 0x04, custom_flow: int = 0, version: int = 0) -> str:
    """disc_caps bitmask: bit0=SoftAP, bit1=BLE, bit2=OnIP. 0x04 = already on IP."""
    check_inputs(passcode, discriminator)
    acc, pos = 0, 0
    def put(value, width):
        nonlocal acc, pos
        acc |= (value & ((1 << width) - 1)) << pos
        pos += width
    put(version, 3)
    put(vid, 16)
    put(pid, 16)
    put(custom_flow, 2)
    put(disc_caps, 8)
    put(discriminator, 12)       # full 12-bit discriminator here
    put(passcode, 27)
    put(0, 4)                    # padding -> 88 bits = 11 bytes
    return "MT:" + base38_encode(acc.to_bytes(11, "little"))

def qr_decode(payload: str) -> dict:
    if payload.startswith("MT:"):
        payload = payload[3:]
    acc = int.from_bytes(base38_decode(payload), "little")
    pos = 0
    def take(width):
        nonlocal pos
        v = (acc >> pos) & ((1 << width) - 1); pos += width; return v
    return {
        "version": take(3), "vendor_id": take(16), "product_id": take(16),
        "custom_flow": take(2), "discovery_caps": take(8),
        "discriminator": take(12), "passcode": take(27),
    }

# -- CLI --------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Matter onboarding codes.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("gen", help="passcode+discriminator -> manual code (+ QR)")
    g.add_argument("--passcode", type=int, required=True)
    g.add_argument("--discriminator", type=int, required=True)
    g.add_argument("--vid", type=lambda x: int(x, 0))
    g.add_argument("--pid", type=lambda x: int(x, 0))
    g.add_argument("--disc-caps", type=lambda x: int(x, 0), default=0x04,
                   help="discovery capability bitmask (0x02=BLE, 0x04=IP). Default 0x04.")

    d = sub.add_parser("decode", help="MT:... -> fields")
    d.add_argument("payload")

    m = sub.add_parser("decode-manual", help="11-digit manual code -> fields")
    m.add_argument("code")

    a = ap.parse_args()

    if a.cmd == "gen":
        mc = manual_code(a.passcode, a.discriminator)
        print(f"passcode       : {a.passcode}")
        print(f"discriminator  : {a.discriminator} (0x{a.discriminator:03X}, short=0x{(a.discriminator>>8)&0xF:X})")
        print(f"manual code    : {mc}   ->  {group_manual(mc)}")
        if a.vid is not None and a.pid is not None:
            print(f"QR (MT:)       : {qr_payload(a.passcode, a.discriminator, a.vid, a.pid, a.disc_caps)}")
        else:
            print("QR (MT:)       : (pass --vid and --pid to get it; the manual code is enough for HA)")

    elif a.cmd == "decode":
        for k, v in qr_decode(a.payload).items():
            print(f"{k:16}: {v}" + (f"  (0x{v:X})" if isinstance(v, int) and v > 9 else ""))

    elif a.cmd == "decode-manual":
        for k, v in decode_manual(a.code).items():
            print(f"{k:20}: {v}")


if __name__ == "__main__":
    main()
