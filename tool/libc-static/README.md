# tool `libc-static`

The static C library of a Linux system (`libc.a`) - what a static link (`gcc -static`, `clang -static`)
takes. Debian and Ubuntu install it with the C library's development package. Fedora, the RHEL family,
Amazon Linux, Azure Linux and openSUSE keep it in a package of its own that is not installed by default,
and a static link stops there with `ld: cannot find -lc`.

```
cx tool setup libc-static        # asks the C compiler where its libc.a is; missing: the distribution's package (sudo)
```

A program that links statically on Linux sets it up before its compile:

```yaml
- task: setup,a2f9b61079ce4333
  if: '{{global.target.compute|$[]}} == ["cpu"] and "{{global.host.os.uname}}" == "linux" and "{{local.params.compile.static|False}}" == "True"'
  name: libc-static,34fbaa2deedb448a
```

## How it works

- **Found by the compiler.** The tool asks the C compiler of the run (the program's, else the one cMeta
  selects) with `-print-file-name=libc.a`: the compiler's own search, the same one its linker makes. gcc
  and clang both answer it. `--tool_path=<libc.a>` names a file instead.
- **Installed by the distribution.** When there is none, the package of the distribution is installed with
  its package manager (`package_name_os_id` of `_desc.yaml`): `glibc-static` on Fedora, the RHEL family,
  Amazon Linux and Azure Linux, `glibc-devel-static` on openSUSE, `libc6-dev` on Debian and Ubuntu,
  `musl-dev` on Alpine. Rocky Linux, AlmaLinux and CentOS Stream keep the package in the CRB repository,
  which is off by default: it is enabled for this one install (`package_repo_os_id`).
- **Nothing is added to the link.** The compiler finds its own C library; the tool's key (`libc-static`)
  does not start with `lib-`, so task `setup-compile` leaves it alone.
- **It needs root** (the system's package manager). A quiet run (`-q`) without passwordless sudo fails at
  once and prints the command; the cure is to run that command, or to link dynamically.

Linux only: macOS has no static C library, and Windows links its run time statically with a compiler
flag. The version is the one of the system's C library, so the tool pins none.
