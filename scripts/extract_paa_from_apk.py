#!/usr/bin/env python3
"""Extract a Matter PAA (Product Attestation Authority) X.509 certificate
embedded in an Android app's native library.

Some vendors never publish their PAA to the CSA Distributed Compliance
Ledger (DCL) nor to the community-maintained list in
project-chip/connectedhomeip. When that happens, Matter commissioning fails
at the attestation step with an error that names the missing certificate by
its Subject/Authority Key Identifier (SKID/AKID), e.g.:

    Unable to find PAA ... CA certificate not found,
    PAI's AKID: 48:A4:33:8A:7E:CA:B0:98:0C:98:22:5C:F4:61:0A:7A:D9:35:8A:B4

The vendor's own official companion app almost always embeds this exact
certificate (it needs it to talk to the device at all). This script looks
for the raw SKID bytes inside a directory tree (typically an extracted APK)
and, when found immediately followed by a DER SEQUENCE, extracts it as a
standalone certificate you can feed to your Matter controller's
--paa-root-cert-dir.

Usage
-----
1. Get the APK (and any split APKs) of the vendor's app, e.g. via `adb pull`
   from a device where it's installed, or downloaded directly.
2. Unzip it (an APK is a plain ZIP):

     python3 -c "import zipfile; zipfile.ZipFile('base.apk').extractall('extracted')"

   Repeat for any split_config.*.apk and extract into the same tree (or
   separate subdirectories) — this script scans a directory recursively.
3. Run this script with the AKID from your commissioning failure log:

     python3 extract_paa_from_apk.py --skid 48:A4:33:8A:7E:CA:B0:98:0C:98:22:5C:F4:61:0A:7A:D9:35:8A:B4 --apk-dir extracted/ -o vendor_paa.der

4. Validate the result:

     openssl x509 -inform DER -in vendor_paa.der -noout -text

   Check that it's self-signed (Issuer == Subject), has
   `Basic Constraints: CA:TRUE`, `Key Usage: Certificate Sign`, and that its
   own Subject Key Identifier matches the AKID you searched for. If all of
   that holds, you've found a legitimate, self-signed root certificate — a
   PAA is public data by design (no private key involved), so republishing
   and trusting it locally is not a security bypass, it's just providing the
   trust anchor the vendor should have published themselves.

Notes
-----
- Only .der files are read by the native CHIP attestation trust store
  (FileAttestationTrustStore.cpp filters by ".der" extension) — this script
  writes DER; convert to PEM separately if you want a human-readable copy
  (`openssl x509 -inform DER -in out.der -outform PEM -out out.pem`).
- This script handles the common case where the SKID bytes are immediately
  followed by the certificate's own DER SEQUENCE header (0x30 0x82 ...) —
  i.e. a [SKID][cert] indexed trust-store layout, which is what at least one
  vendor's Android CHIP bindings use internally. If your target embeds
  things differently, you'll need to adapt the boundary-detection logic
  below (search backward/forward for `0x30 0x82` and validate candidates
  with `openssl x509` until one parses).
"""

from __future__ import annotations

import argparse
import os
import sys


def find_skid_hits(root_dir: str, target: bytes) -> list[tuple[str, bytes, int]]:
    """Walk root_dir, return (path, file_bytes, offset) for every file containing target."""
    hits = []
    for dirpath, _dirnames, filenames in os.walk(root_dir):
        for fn in filenames:
            path = os.path.join(dirpath, fn)
            try:
                with open(path, "rb") as f:
                    data = f.read()
            except OSError:
                continue
            idx = data.find(target)
            if idx != -1:
                hits.append((path, data, idx))
    return hits


def extract_der_sequence(data: bytes, offset: int) -> bytes | None:
    """If data[offset:] starts with a long-form DER SEQUENCE (30 82 LL LL), return the whole TLV."""
    if data[offset : offset + 2] != b"\x30\x82":
        return None
    length = (data[offset + 2] << 8) | data[offset + 3]
    end = offset + 4 + length
    if end > len(data):
        return None
    return data[offset:end]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--skid",
        required=True,
        help="Target SKID/AKID, colon-separated hex (e.g. from the commissioning failure log)",
    )
    parser.add_argument(
        "--apk-dir",
        default="extracted",
        help="Directory containing the unzipped APK contents (default: extracted)",
    )
    parser.add_argument(
        "-o", "--output", default="extracted_paa.der", help="Output DER file path"
    )
    args = parser.parse_args()

    target = bytes.fromhex(args.skid.replace(":", "").replace(" ", ""))
    if len(target) != 20:
        print(
            f"warning: SKID is {len(target)} bytes, expected 20 (SHA-1-sized key identifier)",
            file=sys.stderr,
        )

    hits = find_skid_hits(args.apk_dir, target)
    if not hits:
        print("No file contains those SKID bytes. Nothing found.", file=sys.stderr)
        sys.exit(1)

    for path, data, idx in hits:
        print(f"Match in {path} at offset {idx}")
        cert = extract_der_sequence(data, idx + len(target))
        if cert is not None:
            with open(args.output, "wb") as out:
                out.write(cert)
            print(f"Wrote {len(cert)}-byte DER certificate to {args.output}")
            print(f"Validate with: openssl x509 -inform DER -in {args.output} -noout -text")
            return

    print(
        "SKID found, but no DER SEQUENCE immediately follows any occurrence.\n"
        "Your target likely uses a different layout — inspect the hex around the\n"
        "match manually (e.g. with `xxd` or a Python hexdump) and adapt the\n"
        "boundary detection above.",
        file=sys.stderr,
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
