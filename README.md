# Inspire Aruba (Enki/Adeo) ceiling fans on Home Assistant via Matter

How to get Leroy Merlin "Inspire Aruba" ceiling fans (Enki brand, made by
Adeo) working with a self-hosted Home Assistant / `matter-server`, with no
cloud dependency on the Enki app after the initial setup.

**Status**: the attestation blocker below is solved and verified (the PAA
certificate has been extracted and validated). End-to-end commissioning with
the corrected trust store is being retested — this README will be updated
once confirmed. If you get here independently and it works (or doesn't) for
you, please open an issue.

This almost certainly also applies to **other Enki/Adeo Matter devices**,
not just this fan — the actual blocker (missing PAA) is a property of
Adeo's whole Matter product line (shared Vendor ID), not of this specific
fan model.

## The problem, in short

These fans are genuine Matter-over-Wi-Fi devices — no hub, no bridge,
no Zigbee. Commissioning them into a standards-compliant Matter controller
(Home Assistant's `matter-server`, `chip-tool`, etc.) other than the
official Enki app fails at the very last step, **device attestation**:

```
Unable to find PAA, err: .../FileAttestationTrustStore.cpp:177:
CHIP Error 0x0000004A: CA certificate not found,
PAI's AKID: 48:A4:33:8A:7E:CA:B0:98:0C:98:22:5C:F4:61:0A:7A:D9:35:8A:B4
Failed Device Attestation (err 101: PAA not found in DCL and/or local PAA trust store)
```

Matter's attestation model chains a device certificate (DAC) up through an
intermediate (PAI) to a vendor's self-signed root (PAA). Controllers fetch
known PAAs from the CSA's Distributed Compliance Ledger (DCL) and a
community-maintained mirror in `project-chip/connectedhomeip`. **Adeo's PAA
is in neither** — checked against DCL production, DCL test-net, and the
connectedhomeip community cert list. It's simply never been submitted
anywhere public.

## The fix: Adeo's own app already has it

A PAA is *public data by design* — it's a certificate with no private key,
whose entire purpose under the Matter spec is to let anyone verify a device
attestation chain. Trusting one locally isn't bypassing security — it's
providing the trust anchor the vendor omitted to publish.

Adeo's official Enki Android app needs this exact certificate to talk to
its own devices, so it ships it — bundled inside the native library of the
official Android CHIP SDK bindings the app links against
(`libCHIPController.so`). It's stored as a flat, indexed trust store:
`[20-byte SKID][DER certificate]` pairs, back to back.

**This repo does not redistribute the extracted certificate file itself.**
Extracting it involves inspecting Adeo's compiled app binary; doing that on
your own device, on a copy of the app you already legitimately run, for the
sole purpose of interoperating with hardware you own, is squarely what the
EU Software Directive's decompilation-for-interoperability exception (and
its national transpositions, e.g. French CPI art. L122-6-1) is for.
Redistributing an already-extracted binary pulled from a third party's app
is a different, less clearly-covered act — so instead, this repo gives you
the tool and the exact bytes to search for, and you extract your own copy
in about thirty seconds. See below.

For verification without extracting anything yourself, here's what the
certificate *is* — plain facts about a public key, not a reproduction of it:

```
Subject / Issuer: CN = Adeo Matter PAA, 1.3.6.1.4.1.37244.2.1 (VID) = 1277
Self-signed:      yes (Issuer == Subject)
Basic Constraints: critical, CA:TRUE, pathlen:1
Key Usage:         critical, Certificate Sign, CRL Sign
Public key:        EC prime256v1 (P-256)
Subject Key Identifier:
  48:A4:33:8A:7E:CA:B0:98:0C:98:22:5C:F4:61:0A:7A:D9:35:8A:B4
SHA-256 fingerprint:
  F8:53:17:95:B6:4E:81:57:AB:40:75:F4:81:B2:75:4F:E1:FC:BC:66:97:DF:DD:27:C5:97:B1:10:EC:50:7C:64
```

The Subject Key Identifier matches, byte for byte, the AKID cited in the
commissioning failure above. Once you've extracted your own copy (next
section), compare its SHA-256 fingerprint against the one above to confirm
you found the right certificate.

### Extracting your own copy

```bash
# 1. Get the APK (adb pull from a device where it's installed, or download it)
# 2. Unzip it (it's a plain ZIP) — repeat for any split_config.*.apk
python3 -c "import zipfile; zipfile.ZipFile('base.apk').extractall('extracted')"

# 3. Search for the certificate by the AKID from your own commissioning failure log
python3 scripts/extract_paa_from_apk.py \
  --skid 48:A4:33:8A:7E:CA:B0:98:0C:98:22:5C:F4:61:0A:7A:D9:35:8A:B4 \
  --apk-dir extracted/ -o adeo_matter_paa.der

# 4. Validate and compare against the fingerprint published above
openssl x509 -inform DER -in adeo_matter_paa.der -noout -fingerprint -sha256
```

See [`scripts/extract_paa_from_apk.py`](scripts/extract_paa_from_apk.py) —
it's generic, not Adeo-specific: it should work for any vendor whose app
embeds its PAA the same way (search-by-SKID, extract the DER that follows).

## Wiring the certificate into your own `matter-server`

`matter-server` (the controller behind Home Assistant's Matter integration)
loads trusted PAAs from whatever directory you pass to
`--paa-root-cert-dir`, in addition to what it fetches from the DCL. Two
things to know:

1. **Only `.der` files are read.** The native CHIP attestation trust store
   (`FileAttestationTrustStore.cpp`) filters by extension — a `.pem` sitting
   next to it is silently ignored.
2. **The default `--paa-root-cert-dir` points inside the container image**,
   not a persistent volume — anything you drop there is lost on the next
   container recreation. Point it at a bind-mounted, persistent directory
   instead.
3. `matter-server` purges this directory **once**, the very first time it
   runs against it, if a `.version` sentinel file isn't already present
   (`paa_certificates.py`: *"Old PAA root certificate store found, removing
   certificates"*). After that first run, it only ever *adds* certificates
   fetched from the DCL/git — it never deletes anything again. So: either
   let it run once untouched before adding your custom cert, or pre-create
   an old-dated `.version` file yourself so the purge never triggers and the
   normal DCL/git fetch still happens on schedule.

Minimal `docker-compose.yml` example:

```yaml
services:
  matter-server:
    image: ghcr.io/matter-js/python-matter-server:stable
    container_name: matter-server
    restart: unless-stopped
    network_mode: host          # needed for mDNS
    security_opt:
      - apparmor=unconfined     # needed for Bluetooth via D-Bus, if you use it
    command: >-
      --storage-path /data
      --paa-root-cert-dir /data/paa-root-certs
    volumes:
      - ./data:/data
```

Before first start, pre-seed the sentinel so your custom cert survives the
one-time purge while still letting the normal DCL fetch happen, then drop in
the certificate you extracted above:

```bash
mkdir -p ./data/paa-root-certs
echo 1 > ./data/paa-root-certs/.version
touch -d '2020-01-01' ./data/paa-root-certs/.version
cp adeo_matter_paa.der ./data/paa-root-certs/
```

(If you manage this with Ansible, Puppet, etc., translate the same three
steps: directory + cert file + pre-dated sentinel, in that order, before the
container's first start against this path.)

## Commissioning: getting a pairing window without the Enki hub

These fans are Matter-over-Wi-Fi devices whose *very first* commissioning
can, as far as has been determined, only be done through the official Enki
app — no BLE advertisement was observed, no SoftAP network appears; it
looks like the app uses Wi-Fi PAF (Wi-Fi Aware / NAN) rather than either of
the more commonly supported transports. Google Home, Apple Home, and other
BLE-only commissioners can't be the first admin.

Once a fan is commissioned into the Enki app, though, the Matter spec's
multi-admin model applies: any Matter fabric admin can open a commissioning
window for a **second** controller, over IP, no BLE/PAF required. The Enki
app's UI doesn't expose this, but the app is built on the *official*,
unobfuscated Android CHIP SDK (`chip.devicecontroller.ChipDeviceController`)
— so the same API the app itself would use internally can be invoked
directly, on your own rooted phone, using your own account, via
instrumentation (Frida). This is not exploiting a vulnerability: it's
calling the vendor's own public commissioning API through its own
official SDK, just without going through a UI screen the app doesn't
provide.

**Frida scripts for this step**: [`scripts/frida/`](scripts/frida/) —
`open_commissioning_window.js` (with `find_controller.js` as a fallback if
a future app update obfuscates the controller class). See that directory's
[README](scripts/frida/README.md) for the full step-by-step.

## Not affiliated with Adeo / Leroy Merlin / Enki / CSA

This repository is independent, unofficial, community documentation. It
does not redistribute any part of Adeo's app or firmware — only a
description of a public certificate's contents (facts, not an artifact) and
the tooling to extract your own copy from your own legitimately-installed
software, for interoperability with hardware you own.

**The actual long-term fix** is for Adeo to submit this PAA to the CSA's
production DCL, like any compliant Matter vendor. If you hit this issue,
consider also filing a support request with Adeo/Leroy Merlin referencing
third-party Matter controller interoperability — the more people ask, the
more likely it gets fixed upstream and this whole repository becomes
unnecessary.

## License

MIT — see [LICENSE](LICENSE).
