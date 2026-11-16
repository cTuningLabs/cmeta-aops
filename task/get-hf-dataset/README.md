# get-hf-dataset

A dataset of the Hugging Face Hub downloaded once into the cache with the hf CLI (`hf download`), and the
files of it a program takes. A dataset artifact asks for it in its `_desc.yaml`:

```yaml
uses:
  - task: get-hf-dataset,9865f4ce243f4984
    repo: ylecun/mnist
    filename: mnist//train-00000-of-00001.parquet        # the file a program takes by default
    filenames:                                           # the files by name ({{local.dataset.features.paths.test}})
      train: mnist//train-00000-of-00001.parquet
      test: mnist//test-00000-of-00001.parquet
result_from_ctx: '{{global.get-hf-dataset}}'
```

```bash
cx task run get-hf-dataset ctuning/OpenMLPerf -q                       # the whole repository
cx task run get-hf-dataset ctuning/cTuning-MiDataSets "adpcm/*" -q     # one folder of it (a glob of hf download --include)
cx task run get-hf-dataset --auth                                      # hf auth login first (a gated or private repository)
```

- `repo` (arg2): the repository, `<owner>/<name>`; `filename` (arg3): the file, or a glob (`adpcm/*`: the
  folder `adpcm`), that `hf download --include` fetches - without it the whole repository; `filenames`: files
  by name, fetched too; `directory`: a local folder instead of a download (`filename` relative to it).
- The result: `path` - the file (`path_root/filename`), `path_root` - the folder of the download, `features.paths`
  - the files of `filenames` by name. A dataset made of sub-datasets (`sub_datasets:` of its `_desc.yaml`, see
  `task/dataset`) takes them from `path_root` - `sub_datasets_folder: adpcm` when the repository holds several
  sets, one folder each.
- The cache: one entry per repository and `filename` (two folders of one repository are two entries); the files
  themselves go to the file cache (`file_cache` of the `task` config: a folder outside the cache entries, shared
  by the entries of one repository, so a second folder of a repository adds to the same download folder) or
  into the entry (`content/`). A data repository (`cache_repo_key: data`) keeps them inside the entry.
- A gated or private repository needs a login once on the machine: `cx tool run hf -- auth login` (or
  `--auth`), or the token in `HF_TOKEN` of the environment; a gated one also needs the access request
  accepted on the Hub. Uploads go through `task/upload-to-hf`.
