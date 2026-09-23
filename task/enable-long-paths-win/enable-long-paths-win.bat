@echo off
rem Enable Windows long paths. Run as administrator (right-click > Run as administrator).
rem The same switch as Settings > System > Advanced > "Enable long paths" on Windows 11.
rem
rem NOTE: keep this file plain ASCII with no UTF-8 BOM - cmd.exe reads a BOM as part of
rem the first command under every code page but 65001, and the command then fails.

reg add "HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\FileSystem" /v LongPathsEnabled /t REG_DWORD /d 1 /f
