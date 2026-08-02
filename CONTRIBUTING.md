# Contributing to cMeta AOps

Thank you for your interest in contributing to **`cmeta-aops`** — an experimental
plugin repository and prototyping playground of reusable cMeta artifacts (tasks,
tools, programs, models and datasets) for AI Operations.

This is a research and prototyping project rather than a supported product, and
artifacts here vary in maturity — see [Project status](README.md#project-status).
That makes two kinds of contribution especially useful: **making an exploratory
artifact actually work on your platform**, and **reporting precisely where one
fails**.

`cmeta-aops` is released under the **Apache License 2.0** (see [`LICENSE`](LICENSE)
and [`NOTICE`](NOTICE)). By contributing, you agree that your contribution is
licensed under the same terms.

Please keep existing copyright and attribution notices intact in anything you
touch — including when an AI assistant helped you write the change. If you reuse
code or metadata from another project, bring its notices with it.

> **This repository is content, not the engine.** Changes to `access()` dispatch,
> artifact resolution, the fast index or the CLI belong in the
> [cMeta framework](https://github.com/cTuningLabs/cmeta) repository. Artifacts —
> recipes that install tools, build and benchmark programs, or fetch models and
> datasets — belong here.

---

## Sign-off: the Developer Certificate of Origin (DCO)

This project uses the **Developer Certificate of Origin (DCO) 1.1** as its
contribution agreement. There is **no separate CLA to sign**. Instead, you certify
that you have the right to submit your contribution by adding a `Signed-off-by`
line to every commit.

Read the full text in the [`DCO`](DCO) file.

### How to sign off

Add the `-s` (or `--signoff`) flag when you commit:

```bash
git commit -s -m "Add a tool artifact for ripgrep"
```

This appends a line using your configured `user.name` and `user.email`:

```
Signed-off-by: Jane Doe <jane@example.com>
```

Use your real name and a valid email address. Set them once with:

```bash
git config user.name "Jane Doe"
git config user.email "jane@example.com"
```

### If you forget to sign off

- Amend the most recent commit:
  ```bash
  git commit --amend -s --no-edit
  ```
- Sign off several commits:
  ```bash
  git rebase --signoff HEAD~N
  ```
- Then update your pull request:
  ```bash
  git push --force-with-lease
  ```

A DCO check runs on every pull request and must pass before a change can be
merged. Passing it is necessary but not sufficient — a maintainer still reviews
and approves each pull request.

### A note for contributors employed elsewhere

If your employer has rights to the intellectual property you create, please make
sure you have permission to contribute before signing off. Employers whose staff
contribute regularly can put a single **Corporate CLA** in place instead; see the
[`cTuningLabs/cla`](https://github.com/cTuningLabs/cla) repository or contact
**gfursin@gmail.com**.

---

## Third-party code — read this before vendoring anything

Parts of this repository are third-party works that are **not** Apache-2.0 and are
listed in [`THIRD-PARTY.md`](THIRD-PARTY.md). Some carry terms more restrictive
than Apache-2.0 (research-only, non-commercial, or GPL).

If your contribution includes source you did not write:

1. **Prefer fetching over vendoring.** A `clone-git-to-cache` or download task that
   pulls the source at run time avoids redistribution questions entirely. This is
   the preferred pattern for anything non-trivial.
2. If you must vendor it, keep the upstream copyright/licence header **verbatim** —
   never replace it with the cMeta header.
3. Ship the upstream licence text inside the artifact (e.g. `src/LICENSE.txt`).
4. Add an entry to [`THIRD-PARTY.md`](THIRD-PARTY.md) recording the path, the
   copyright holder, and the licence — and say so explicitly if its terms are more
   restrictive than Apache-2.0.
5. **Never vendor code whose licence forbids redistribution** (many vendor SDK
   samples do). If in doubt, ask in an issue before opening a pull request.

---

## Development setup

```bash
pip install cmeta                   # the engine (Apache-2.0, Python 3.9-3.14)
cx repo plug .                      # register this repository with cMeta (once)
cx <category> find                  # list artifacts in a category
```

Run the tests with:

```bash
uv run python -m pytest tests       # or: python -m pytest tests
```

The tests are hermetic — they build their own temporary `CMETA_HOME` and do not
touch the network or your real configuration.

---

## Authoring artifacts

Artifacts live at `<category>/<alias>/` as `_cmeta.yaml|json` (identity + tags)
plus an optional `_desc.yaml` (the automation pipeline) and `api_v1.py` (hooks).

- [`AGENTS.md`](AGENTS.md) — the canonical brief: layout, the `task` workflow
  engine, `tool`/`program` delegation, the category cache, conventions.
- [`docs/cmeta-aops/`](docs/cmeta-aops/) — architecture and internals.
- `.claude/skills/` — step-by-step authoring guides for
  [`add-tool`](.claude/skills/add-tool/SKILL.md),
  [`add-task`](.claude/skills/add-task/SKILL.md) and
  [`add-program`](.claude/skills/add-program/SKILL.md). These encode the
  scaffolding and the gotchas; start there.

Conventions that matter:

- Reference artifacts and categories by **`alias,UID`** — the UID is authoritative,
  which makes references rename-safe.
- Declare cross-category dependencies via `uses_categories:` in `_cmeta.*`, and
  dereference them at run time — never hard-code an alias.
- After editing an artifact's `_cmeta.*` **meta**, refresh the index with the
  narrowest command: `cx <cat> index <ref>` to register a hand-made folder,
  `cx <cat> update <ref>` after a meta edit. `cx --reindex` rebuilds every category
  and is slow. Payload-only edits (`api/`, `src/`, `_desc.yaml`) need no reindex.
- Copy the Apache-2.0 copyright header from a sibling file into any new file.

---

## Submitting changes

1. Open an issue first for anything beyond a small fix, so the approach can be
   agreed before you invest time.
2. Create a branch and make your change.
3. **Verify with a real run** — `cx tool run <name> -- --version`,
   `cx program run <name> cpu`, or the relevant `cx task run`. An artifact that has
   never been executed is not ready for review.
4. Ensure `python -m pytest tests` passes.
5. Commit with `-s` (DCO sign-off).
6. Open a pull request describing the change, the platforms you verified on, and
   any related issue.

Please do **not** include local paths, credentials, API keys, machine environment
dumps, or personal workflow scripts in commits. cMeta run artifacts
(`tmp*/`, `tmp-cmeta-*`, `cmeta-task-saved-*`, `_repro_ctx_*`) capture the full
environment of the machine that produced them and are gitignored for that reason —
please keep it that way.

---

## Portability expectations

Artifacts here are expected to adapt across operating systems and compute targets
rather than assume one machine. When contributing:

- State which platforms you actually tested on. "Linux only" is fine and useful —
  silently assuming everything works everywhere is not.
- Avoid hard-coded absolute paths, drive letters, and shell-specific syntax.
- Remember that tool binaries differ by platform (npm shims are `X.cmd` on Windows,
  not `X.exe`).

---

## Reporting security issues

Please do **not** open a public issue for a security vulnerability or a leaked
secret. Email **gfursin@gmail.com** directly.

---

## Questions

- General questions and design discussion: open a GitHub issue.
- Contributor agreements and licensing: **gfursin@gmail.com**.
