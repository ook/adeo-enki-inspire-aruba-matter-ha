/*
 * open_commissioning_window.js
 *
 * Ask the official Enki Android app to open a Matter Enhanced Commissioning
 * (ECM) window on a fan IT already administers, so a SECOND Matter controller
 * (e.g. Home Assistant's matter-server) can join over IP — Matter's standard
 * multi-admin flow. This is not an exploit: it calls the vendor's own public
 * commissioning API, through its own official (unobfuscated) Android CHIP SDK
 * (chip.devicecontroller.ChipDeviceController), on your own rooted phone, with
 * your own account — just without a UI screen the app doesn't provide.
 *
 * Prerequisites
 *   - rooted Android phone, frida-server (matching your frida client version)
 *     running as root
 *   - Enki app signed into your account, with the fan already commissioned BY
 *     THIS app instance (so it is the fabric admin for that device)
 *   - the fan's detail page OPEN in Enki (establishes a live CASE session)
 *
 * Run (ATTACH, do not spawn):
 *   frida-ps -U | grep -i enki                 # note the PID
 *   frida -U -p <PID> -l open_commissioning_window.js
 *
 * Get the fan's node ID from its operational mDNS record:
 *   avahi-browse -rt _matter._tcp
 *   # instance is "<compressed-fabric-id>-<NODE_ID>"; take the NODE_ID (2nd hex group)
 *
 * In ECM you choose the passcode and discriminator yourself; the onSuccess
 * callback returns the corresponding standard Matter manual pairing code and
 * QR payload, usable by any compliant controller.
 */

// ---- configure ----
var PACKAGE       = "com.leroymerlin.enki";
var NODE_ID       = "0x0000000000000000"; // fan node ID from _matter._tcp
var DURATION_S    = 300;                   // window lifetime, seconds
var ITERATION     = 1000;                  // SPAKE2+ PBKDF iterations (1000..10000)
var DISCRIMINATOR = 3840;                  // 12-bit, your choice
var PASSCODE      = 20202021;              // 27-bit, your choice (avoid trivial values)
// -------------------

Java.perform(function () {
  var CTRL_CLASS = "chip.devicecontroller.ChipDeviceController"; // not obfuscated in Enki
  var CONN_IFACE = "chip.devicecontroller.GetConnectedDeviceCallbackJni$GetConnectedDeviceCallback";
  var OCC_IFACE  = "chip.devicecontroller.OpenCommissioningCallback";

  var nodeId = int64(NODE_ID);                         // > 2^53, must be int64
  var pin    = Java.use("java.lang.Long").valueOf(PASSCODE);

  // Result callback: hands back the manual pairing code + QR payload directly.
  var Occ = Java.registerClass({
    name: "org.interop.OccCb",
    implements: [Java.use(OCC_IFACE)],
    methods: {
      onError:   function (status, dev) { console.log("[!] OpenCommissioning onError status=" + status); },
      onSuccess: function (dev, manual, qr) {
        console.log("\n[+] COMMISSIONING WINDOW OPEN (" + DURATION_S + "s)");
        console.log("    manual pairing code : " + manual);
        console.log("    QR payload          : " + qr);
        console.log("    -> In HA: Add Matter device -> enter code manually -> " + manual + "\n");
      }
    }
  });

  // CASE connection callback: on success, open the ECM window.
  var Conn = Java.registerClass({
    name: "org.interop.ConnCb",
    implements: [Java.use(CONN_IFACE)],
    methods: {
      onDeviceConnected: function (devicePtr) {
        console.log("[+] CASE established, devicePtr=" + devicePtr);
        try {
          globalThis.__CTRL.openPairingWindowWithPINCallback
            .overload('long', 'int', 'long', 'int', 'java.lang.Long', OCC_IFACE)
            .call(globalThis.__CTRL, devicePtr, DURATION_S, ITERATION, DISCRIMINATOR, pin, Occ.$new());
          console.log("[*] openPairingWindowWithPINCallback dispatched");
        } catch (e) { console.log("[!] openPairingWindow error: " + e); }
      },
      onConnectionFailure: function (node, err) { console.log("[!] connection failure: " + err); }
    }
  });

  // Grab a live controller instance from the app's own session.
  Java.choose(CTRL_CLASS, {
    onMatch: function (inst) { if (!globalThis.__CTRL) globalThis.__CTRL = inst; },
    onComplete: function () {
      if (!globalThis.__CTRL) {
        console.log("[!] No live " + CTRL_CLASS + " instance. Open the fan's page in Enki, then retry.");
        console.log("    If the class was renamed by an app update, run find_controller.js first.");
        return;
      }
      console.log("[+] ChipDeviceController found -> getConnectedDevicePointer(node=" + NODE_ID + ") ...");
      globalThis.__CTRL.getConnectedDevicePointer
        .overload('long', CONN_IFACE)
        .call(globalThis.__CTRL, nodeId, Conn.$new());
    }
  });
});
