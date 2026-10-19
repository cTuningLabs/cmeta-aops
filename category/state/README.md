# Mutable state

`state` holds durable working data: deployed sources, application data, private environments and service
volumes. `result` holds completed outputs or recovery snapshots. `cache` holds replaceable intermediates.

~~~sh
cx state get local:website-example-production
cx state ls
cx state info local:website-example-production
~~~

New state artifacts default to `permanent: true`. Ordinary removal retains protected artifacts, including
forced batch removal, through the engine's existing permanent-artifact behavior. Explicitly unprotect a
selected artifact with `cx state update <name> --meta.permanent-` before deleting it.
Protection is a deletion guard; retain independent backups too.

This category is an AOps plugin using the existing base category API. Existing cache/result artifacts and
their behavior are unchanged. Docker artifact mounts accept contained state subdirectories, for example
`state::local:website-example-production/volumes/app`.

See [run-website](../../task/run-website/README.md) for the first consumer.

An entry may also own engine-backed Linux volumes. For example, Windows can retain the deployment's
metadata/source in its local state entry while `volumes/app/.cmeta-volume.json` records a Docker volume
holding Linux-only files. That registration is a handle, not a copy of the live volume. Removing a
container retains its volume. Transfer completed `result` backups to move the data between engines or
machines; copying/bisyncing the state directory alone does not copy engine-backed data.
The resolver verifies ownership labels and refuses silent recreation of missing registered storage.
