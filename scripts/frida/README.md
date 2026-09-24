# Frida scripts — pending

This directory will hold the Frida instrumentation scripts used to open a
second-admin Matter commissioning window from the official Enki Android app
(see the "Commissioning" section of the main [README](../../README.md)).

Not yet added — contributions welcome.

Expected approach, for reference until the scripts land here:

1. Commission a fan from the Enki app on a rooted phone (making that app
   instance the Matter fabric admin for that device).
2. Attach Frida to the running Enki app process (attach, not spawn).
3. `Java.choose` on `chip.devicecontroller.ChipDeviceController` to get a
   live instance from the app's own commissioning session.
4. Call `getConnectedDevicePointer(nodeId, callback)` to get a live device
   pointer.
5. In the connection callback, call
   `openPairingWindowWithPINCallback(devicePtr, durationSeconds, iteration,
   discriminator, setupPinCode, callback)` — note the `...Callback` variant;
   the non-callback overload returns `true` without actually opening
   anything.
6. The success callback hands back a standard Matter manual pairing code
   and QR payload, usable by any standards-compliant controller (e.g. Home
   Assistant's "add device manually").
