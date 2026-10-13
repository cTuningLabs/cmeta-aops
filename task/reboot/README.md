# reboot

Reboot the current Windows, Linux or macOS machine. In a terminal, `cxt reboot` asks for
confirmation and reboots immediately only after `y` or `yes`.

```text
cxt reboot                                  # ask before rebooting
cxt reboot --dry_run                        # show the selected command
cxt reboot --yes --delay_seconds=30         # noninteractive, reboot after 30 seconds
```

On Linux with systemd, the task uses `systemctl reboot -i` to override active desktop-session
inhibitors after confirmation. A delayed Linux reboot uses a transient systemd timer. On other
Linux systems and on macOS it uses `shutdown -r`; those platforms round a nonzero delay up to a
whole minute. Windows uses `shutdown.exe /r /t`. Save open work before confirming a reboot.

Noninteractive runs require `--yes`; `--dry_run` never schedules a reboot.
