# Android CPU target

Existing serial selection remains supported. To select and reconnect an Android
fleet device, pass its host name instead of remembering a changing Wi-Fi serial:

```bat
cx task run target--android-cpu --device_host=my-watch -q
cx program run test-nmm-c-cpu android-cpu --use.target--android-cpu.device_host=my-watch -q
```

The optional device_host setting calls cx host connect before enumerating ADB
transports, then selects the returned serial. This also feeds the Android GPU
and NPU targets that depend on the selected Android CPU target. Without
--device_host the existing selection behavior is unchanged.

Pairing/keep-alive and wireless fleet declaration are documented in
[keep-adb-connection-alive](../keep-adb-connection-alive/README.md).
