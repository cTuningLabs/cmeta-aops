20260414:
 FGG uses it to keep WiFi connection with Samsung Watch.

 Watch setup:
  * Connect to the same WiFi as computer!
  * Go to Settings -> Developer Options -> Wireless Debugging -> TURN IT ON

  * OFTEN NEED TO PAIR FIRST:
    * Press "Pair new device" on Android watch
    * Then write down IP address and port
    * Run
        adb pair ip:port
        Enter CODE from the watch
    * should be paired successfully!


  * Write down IP address and port
  * Run this task with "IP:PORT" and optional period (in sec): `cxt keep-adb-connection-alive 10.66.251.140:43291 10`

 Troubles:
  * Sometimes need to do
    adb kill-server
    adb start-server
    adb connect ...

  * Sometimes need to restart watch!
