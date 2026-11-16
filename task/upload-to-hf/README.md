# upload-to-hf

A folder or a file uploaded to a repository of the Hugging Face Hub - a dataset (the default) or a model - with
the hf CLI, the access token coming from a cMeta secret. The repository is made when it does not exist
(`--create=no` refuses instead), a `.gitattributes` of the folder goes up first and alone (the Hub then stores
the files that follow as it says - LFS for the binary kinds it names - instead of guessing from their first
bytes, a guess that gets a commit rejected when a file it took for text holds binary), the files go up with
`hf upload` (a big folder in several commits; the same command again resumes an interrupted upload) and, when
asked, the gating of the repository is set.

```bash
cxt upload-to-hf <folder> ctuning/<name>                                   # the token secret with "service: huggingface"
cxt upload-to-hf <folder> ctuning/<name> --secret=<alias> --gated=manual --message="first upload"
cxt upload-to-hf <folder> ctuning/<name> --type=model --private
cxt upload-to-hf <file> ctuning/<name> --path_in_repo=docs/<file>
cxt upload-to-hf <folder> ctuning/<name> --include=*.json,README.md --exclude=tmp/*
cxt upload-to-hf <folder> ctuning/<name> --delete=LICENSE,old/*      # files of the repository removed in the same commit
cxt upload-to-hf <folder> ctuning/<name> --dry_run                         # the commands; nothing made or uploaded
```

Every hf command runs with the variables of `secret_env` (`_desc.yaml`) in its environment alone - `HF_TOKEN` gets
the token - through `cx secret run`: never on a command line, in a file or in the environment of cMeta. The token
comes from the secret `--secret` names, else from the one token secret whose `_desc.yaml` declares
`service: huggingface`. A password-protected secret asks for its password at each command; on Windows, without
a terminal (an AI agent) or with `--window`, in a console window of its own that shows SUCCESS or FAILED until
Enter.

## The token as a secret

A write token of the Hub (Settings > Access Tokens: a fine-grained token with write access to the repositories
of the organization, or a classic "write" token), kept by cMeta:

```bash
cx secret add <secrets repository>:my-hf-token --yaml --desc.service=huggingface
cx secret store my-hf-token                      # the token at a hidden prompt (--password_protected: encrypted)
```

## Gating

`--gated=manual` (access requests approved by hand), `--gated=auto` (granted at once) or `--gated=no`; the form
users fill and the text they accept are in the dataset card (`extra_gated_prompt`, `extra_gated_fields` ... of
the README's header). A repository to be gated is made private, filled, then made gated and public in one
step (`hf repos settings --gated ... --public`), so nothing is public in between; with `--private` it stays
private. Reading a gated repository needs a login once on the machine (`cx tool run hf -- auth login`), as
`get-hf-dataset` says.
