# Machine retirement

A machine is the asset; its host artifacts are its login endpoints. Set
`retired: true` in the machine's `_desc.yaml` when that asset has been retired.
`cx machine ls` shows `retired` in its STATUS column. Unmarked assets show `-`;
this is an inventory declaration, not a live availability check. JSON listings
and `show` include the `retired` boolean and status.

Set the flag separately on its retired host artifacts so `cx host ls/status`
and the local host dashboard also recognize retirement and skip endpoint checks.
An individual host can retire while its machine and other hosts remain usable.
Keep the historical connection and probe records; clear the retirement flags
and update connection details before reusing these records for a replacement.
