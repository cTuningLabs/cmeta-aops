<!--
Licensed under the Apache License, Version 2.0. See the COPYRIGHT and LICENSE files in the project root for details.
-->

# Compatibility: what every tool, task, program and page keeps

The artifacts of this repository wrap programs, systems and hardware that keep changing, and they are used on
machines that do not change at the same pace. Five concepts decide **how** an artifact is written or changed, so
that what worked before keeps working. They come from the author of cMeta; the engine holds the same five for
itself ([design-concepts.md](https://github.com/cTuningLabs/cmeta/blob/main/docs/design-concepts.md)). A change
that cannot keep one of them is discussed with the maintainers first; it is not settled silently in code.

The working brief for AI agents is [`AGENTS.md`](../../AGENTS.md) §8.2.

---

## 1. A connector and an adaptor, never a replacement

A tool, a task, a program or a page wraps what exists on a machine, whatever its version, system and hardware,
and what was made before: older artifacts, cache entries, records. It adapts to them. It does not require them to
be updated first.

## 2. Backwards compatible, by extension

| Add | Do not |
|-----|--------|
| a new key in `_desc.yaml` or in a result | change what an existing key means, or remove one a caller, a cache entry or a saved record may still read |
| a new parameter whose default keeps the old behaviour | change the default of an existing parameter |
| a new task, or an `api_v2.py` beside `api_v1.py` | rewrite a task in a way its callers notice |
| a new dated folder or record | move or rename what artifacts and scripts already point to |

A task or a tool that relies on other tasks or tools keeps this for them too: it does not start to need the newest
version of what it uses.

## 3. Follow the version of what is wrapped

- **A tool is version-agnostic.** It takes the version a system has; the code that needs a feature asks for a
  version (`--version=">=X"`) or adapts ([tool-abstraction.md](tool-abstraction.md)). A program whose version
  command behaves differently on one system declares it (`cmd_get_version_exit_codes`) instead of being dropped.
- **Code that depends on a version asks cMeta for it.** The tool's own detection gives the version (the `setup`
  task with `skip_install`: nothing is installed). The code then takes the mechanism for that version.
- **A program that changed gets a mechanism added.** The mechanisms for its older versions stay, and stay tested.
  Never "the newest only": the machines that still run the older version are users too.

A worked case is `task/ai-account-status`. Its `_desc.yaml` lists, per AI harness, the cMeta tool that finds it and
the ways its account is read, the newest first, each with the harness version it starts at:

```yaml
harnesses:
  codex:
    tool: codex,cdbf5f6e6882460f
    ways:
      - name: codex-app-server      # the reader of that name in api_v1.py
        reads: the installed program itself (codex app-server --stdio) ...
        verified:
          - {harness: '0.170.0', os: windows, date: '2026-11-20'}
```

The task asks cMeta for the installed harness's version, takes the first way whose `since` is not above it, and
says in its answer which way it used (`mechanism`, `harness_version`). When a harness moves its login or changes
how its usage is asked, a way is added above the others with `since: <the first version that needs it>`; the ways
below stay as they are.

## 4. Works everywhere: old, current and not yet seen

Windows, Linux, macOS, Android and iOS targets, old and new distributions, CPUs, GPUs and NPUs, Python 3.9 to 3.15,
and versions of tools nobody has tried. Where something is missing or too old, do what still works and say plainly
what does not (reduced functionality), rather than fail:

- a version that is not known takes the documented default and the result says so;
- a feature a system lacks is left out, and the summary names it;
- an unknown newer version is tried the newest way, not refused because it is not on a list.

Failing is right in three cases: a real bug, a security issue, and what the user explicitly forced. A forced
version or configuration that is not available must fail, never be quietly replaced by another.

## 5. Never guess

A task, a tool or a page finds what it needs the way cMeta defines it:

| What | How it is found |
|------|-----------------|
| an artifact, a task, a tool | `alias,UID`; the UID decides |
| a repository | `cx repo find <alias>` (in code: the `repo` category's `find`), never `<home>/repos/<alias>` |
| a tool's program | the `path` of its `setup` result, never a search of likely folders |
| a file inside an artifact | from the artifact's own path |

Never by searching for a likely name, taking the first or last match, relying on the order of a listing, or
falling back to a second heuristic. When the defined way does not hold, stop with an error that says what was
expected; two candidates are an error that lists them, not a choice. Tests check results by names and cRefs, never
by positions.

---

## Before you propose a change

1. Does it replace something instead of adding beside it?
2. Does it stop an older artifact, caller, system or tool version from working?
3. Does any step guess?

If one answer is yes, say so in the pull request and ask before going further.
