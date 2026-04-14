20260414:
 FGG uses it to keep WiFi connection with Samsung Watch.

 Watch setup:
  * Connect to the same WiFi as computer!
  * Go to Settings -> Developer Options -> Wireless Debugging -> TURN IT ON
  * Write down IP address and port
  * Run this task with "IP:PORT" and optional period (in sec): `cxt keep-adb-connection-alive 10.66.251.140:43291 10`
