# select-src-by-tool-version: one program, sources for several versions of a tool

Languages and libraries change in ways that break old sources: Mojo 1.0 removed `fn` and `len()` of a
`String`, so a program written for Mojo 0.25 no longer compiles, and one written for 1.0 does not compile
with 0.25. This step lets one program artifact keep both and take the right one for the tool that the
run set up, so the newest tool works and an older one still does.

## Layout of the program

```
program/test-nmm-mojo-cpu/
  _desc.yaml
  src/         program.mojo, matmul.mojo     the default sources (here: before Mojo 1.0)
  src-v2/      program.mojo, matmul.mojo     the sources for Mojo 1.0 and later
```

The default sources stay where `local_vars.src_dir` and `src_file_names` point. Each further generation
is a sibling folder with the same file names.

## The step

After the setup of the tool, before `setup-compile` or `setup-run`:

```yaml
- task: setup,a2f9b61079ce4333
  name: mojo,666e926f670a4dbc

- task: select-src-by-tool-version,0ad29e6691b94cd2
  tool: mojo                                        # the tool's key in the global context
  program_path: '{{local.selected-program.path}}'
  src_file_names: '{{local.src_file_names}}'
  rules:                                            # the first rule that matches wins
    - version: '>=1.0.0'
      src_dir: src-v2
```

- `version` is one comparator or several joined by commas, all of which must hold: `>=1.0.0`,
  `>=0.26.2,<1.0.0`, `1.1.0` (the same as `==1.1.0`), `!=1.0.0`. A rule without `version` matches every
  version.
- A rule may give its own `src_file_names` when the files of that generation have other names.
- When no rule matches, nothing changes: the program runs its default sources.
- The run prints which folder it took and why (`INFO: sources from "src-v2": mojo 1.1.0 matches ">=1.0.0"`),
  and the result of the step has `tool_version`, `src_dir` and `rule`.
- It fails when the tool's version is unknown (the step is before the tool's setup), when a rule's folder or
  a source file is missing, and on a rule that is not `<comparator><version>`.

It sets `src_dir`, `src_path`, `src_file_names_str`, `src_file_names_str_with_path` and
`src_file_names_list` in the local context, which the compile and run steps read.

## Trying the other generation

```bash
cx program run test-nmm-mojo-cpu cpu                                # the Mojo that pip installs today
cx program run test-nmm-mojo-cpu cpu --use.mojo.version=0.26.1.0    # an older Mojo and the older sources
```

A build folder is reused across such runs only for interpreted programs like this one; a compiled
program needs `--target_tmp=<name>` or `--recompile` when the tool version changes the sources.
