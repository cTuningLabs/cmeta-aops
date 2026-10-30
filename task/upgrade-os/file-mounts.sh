#!/bin/sh
# upgrade-os: the files of packages that something else mounts over, moved aside for an upgrade and back after it.
#
#   sh file-mounts.sh aside    (root) bind each such file mount to a place of its own under /run, then unmount it
#   sh file-mounts.sh back     (root) bind each one back over its file and drop its place
#
# A package manager cannot replace a file that is a mount point: the WSL kernel mounts its own perf read-only over
# /usr/bin/perf, which linux-tools-common owns, and dpkg could neither link its backup ("Invalid cross-device link")
# nor rename onto it - the run ended with dozens of packages unpacked and not configured (2026-10-29). With the mount
# aside the package's own file underneath is upgraded, and the mount comes back as it was (as WSL would mount it at
# its next start). Only regular files under the system folders and owned by a package: not /etc (a package manager
# keeps a changed configuration file instead of replacing it, and a container's /etc/hosts or resolv.conf must stay).
# Where nothing can be mounted (a container without the right) the run goes on as before, with a warning.
#
# Licensed under the Apache License, Version 2.0.
# See the COPYRIGHT and LICENSE files in the project root for details.

STATE=/run/cmeta-upgrade-os
LIST=$STATE/file-mounts
TAB=$(printf '\t')

# A file that a package owns: dpkg, rpm, pacman or apk say so
owned() {
    if command -v dpkg >/dev/null 2>&1 && dpkg -S "$1" >/dev/null 2>&1; then return 0; fi
    if command -v rpm >/dev/null 2>&1 && rpm -qf "$1" >/dev/null 2>&1; then return 0; fi
    if command -v pacman >/dev/null 2>&1 && pacman -Qo "$1" >/dev/null 2>&1; then return 0; fi
    if command -v apk >/dev/null 2>&1 && apk info --who-owns "$1" >/dev/null 2>&1; then return 0; fi
    return 1
}

back() {
    if [ ! -s "$LIST" ]; then
        rm -f "$LIST"
        rmdir "$STATE" 2>/dev/null
        return 0
    fi
    failed=
    while IFS="$TAB" read -r place path; do
        # the package may have dropped its file: the mount point comes back as it was
        [ -e "$path" ] || : > "$path"
        if mount --bind "$place" "$path" && umount "$place"; then
            rm -f "$place"
            echo "upgrade-os: mounted back over $path"
        else
            echo "upgrade-os: cannot mount $path back - it stays at $place until a reboot" >&2
            failed=1
        fi
    done < "$LIST"
    [ -n "$failed" ] && return 1
    rm -f "$LIST"
    rmdir "$STATE" 2>/dev/null
    return 0
}

aside() {
    # a run that was cut short first puts its mounts back
    back || return 1
    mkdir -p "$STATE" && : > "$LIST" || return 1

    # the mount points of /proc/self/mountinfo (its fifth field; a name with an escaped space is left alone)
    n=0
    for path in $(awk '{print $5}' /proc/self/mountinfo | sort -u); do
        case "$path" in
            *\\*) continue ;;
            /usr/*|/bin/*|/sbin/*|/lib/*|/lib32/*|/lib64/*|/libx32/*|/opt/*) ;;
            *) continue ;;
        esac
        [ -f "$path" ] && owned "$path" || continue
        n=$((n + 1))
        place="$STATE/$n"
        if : > "$place" && mount --bind "$path" "$place" && umount "$path"; then
            printf '%s\t%s\n' "$place" "$path" >> "$LIST"
            echo "upgrade-os: moved aside for the upgrade: the mount over $path (a file of a package)"
        else
            umount "$place" 2>/dev/null
            rm -f "$place"
            echo "upgrade-os warning: cannot move the mount over $path aside - its package may fail to upgrade"
        fi
    done
    return 0
}

if [ "$(id -u)" != 0 ]; then
    echo "upgrade-os: file-mounts.sh needs root" >&2
    exit 1
fi

case "$1" in
    aside) aside ;;
    back) back ;;
    *) echo "usage: sh file-mounts.sh aside|back" >&2; exit 2 ;;
esac
