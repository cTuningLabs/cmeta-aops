# Wireless Android connections and keep-alive

The existing task now also serves cx host connect for an adb fleet host. Its
original positional endpoint/period loop remains supported:

```bat
cxt keep-adb-connection-alive 192.0.2.10:43291 10
cxt keep-adb-connection-alive 192.0.2.10:43291 --once -q
```

For a registered wireless host:

```bat
cx host connect my-watch --pair
cx host connect my-watch --endpoint=192.0.2.10:43291
cx host connect my-watch --keepalive
cx host connect my-watch --keepalive --duration=600 --period=10
cx host connect my-watch --instructions
```

Watch and computer must share a Wi-Fi network allowing peer traffic. Enable
ADB debugging and Wireless debugging on the watch. Pair new device displays
a PAIRING IP:port and temporary PIN; --pair asks for the address, then adb reads
the PIN directly from the terminal. Return to the main Wireless debugging screen
for the separate CONNECTION IP:port. Use --pairing_endpoint to supply the first
address and --endpoint to supply the second in advance. Pairing requires a
terminal and cannot be completed by -q; no PIN parameter/configuration is stored.

The current implementation connects on the host's declared local ADB controller
(via). Android Studio can use that same adb connection. A foreground keep-alive
loop continues until Ctrl+C; --duration bounds it. There is no background daemon,
server reset, forced device disconnect, watch reboot or change to device power
settings. A watch that disables its radio/debugging service cannot be reached
until it is enabled again. If discovery is unavailable, supply its current port.

## Fleet declaration

```yaml
type: adb
os: android
via: host::my-laptop,0123456789abcdef

access:
  serial: ''
  shell: none
  wireless:
    auto_connect: true
    endpoint: ''
    required_features: [android.hardware.type.watch]
```

The endpoint is optional declarative configuration; the first successful
connection observes the hardware serial, model, manufacturer, transport and
endpoint under adb_connection in this host's state.yaml. A later connection
must match that identity and the required features. Connection observations
survive normal fleet probes and cache cleanup; adb retains pairing credentials
in its own user profile. A saved configured device_serial takes precedence over
an observed identity if explicitly declared in access.wireless.

Discovery only uses _adb-tls-connect._tcp, never the pairing port. It matches
the saved service/hardware identity or the previous address, then verifies the
hardware identity before selecting the device. An explicit initial endpoint
cannot be replaced with a random connected phone. Ordinary host commands
reconnect when auto_connect is enabled; status remains a bounded observation.
Existing USB/non-wireless hosts keep their behavior.

Direct task parameters include --host=<alias,UID>, --ip=<endpoint>,
--serial=<transport>, --once, --pair, --pairing_endpoint=<endpoint>,
--period=<seconds>, --timeout=<1..60 seconds>, --duration=<seconds> and
--instructions. A legacy bare address retains adb's default TCP port 5555;
modern Wear OS wireless debugging normally supplies its own connection port.
All durations/retries use the monotonic clock.

[Official Wear OS Wi-Fi debugging and pairing](https://developer.android.com/training/wearables/get-started/debug-wifi)
explains the two ports and on-watch setup. [ADB documentation](https://developer.android.com/tools/adb)
covers wireless debugging and mDNS discovery.
