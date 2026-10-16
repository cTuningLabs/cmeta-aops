# sync

A reusable synchronization relationship between two directories or CMETA homes.
Definitions live in `sync/<name>/_desc.yaml`; they can reference registered hosts.

```text
cxt sync
cxt sync my-pair --plan
cxt sync my-pair
cxt sync my-pair --live
cx sync run my-pair
```

See [task::sync](../../task/sync/README.md) for the schema, modes, first-run
initialization, live file output, permanent result state, backups, recovery and ordered multi-pair workflows.
