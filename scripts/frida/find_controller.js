/*
 * find_controller.js
 *
 * Locate the CHIP device-controller class inside the Enki app if a future app
 * update obfuscates it. At the time of testing the class was shipped
 * unobfuscated as chip.devicecontroller.ChipDeviceController, so this is only a
 * fallback. JNI-bound method names (openPairingWindowWithPIN*,
 * getConnectedDevicePointer) usually survive R8 obfuscation even when the class
 * name is renamed.
 *
 * Run:
 *   frida -U -p <PID of Enki> -l find_controller.js
 *
 * Then set CTRL_CLASS in open_commissioning_window.js to the class it reports.
 */
Java.perform(function () {
  console.log("[*] Scanning loaded classes for openPairingWindow* / getConnectedDevicePointer ...");
  Java.enumerateLoadedClassesSync().forEach(function (name) {
    try {
      var k = Java.use(name);
      var methods = k.class.getDeclaredMethods();
      for (var i = 0; i < methods.length; i++) {
        var m = methods[i].getName();
        if (m.indexOf("openPairingWindow") !== -1 || m.indexOf("getConnectedDevicePointer") !== -1) {
          console.log("[+] " + name + "  ->  " + m);
        }
      }
    } catch (e) {}
  });
  console.log("[*] scan complete.");
});
