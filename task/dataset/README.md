# dataset

The dataset of a program run: an artifact of the `dataset` category chosen by name or by tags, and the file of it
a program takes. A program's `_desc.yaml` asks for it in its run pipeline, usually with the name and the file
given on the command line:

```yaml
- task: dataset,30e20c7489f14f84
  dataset_tags: image,pgm
  name: '{{params.dataset|$None}}'
  filename: '{{params.dataset_file|$None}}'
```

```bash
cx task run dataset <dataset> [<file>] -q
cx program run cbench-automotive-susan cpu --dataset=ctuning-image-pgm-0001 -q
```

The result (`{{local.dataset.*}}` of the program): `path` and `qpath` - the file; `files` - the files of the
dataset in its order (the first is the default); `path_files` - their folder; `number` - the number the dataset
stands for; `artifact_au` - the dataset; `tags` and `desc` of a sub-dataset.

## What a dataset is

- **Files kept with the artifact**: `files/` holds them. `files:` of its `_desc.yaml` gives their order (the
  first is what a program takes by default; without the list, by name), `number:` the number it stands for (a
  dataset that is a number on a command line). Several files and no name asked for: a choice (`-q`: the first).
- **Files prepared on demand**: no `files/`; `_desc.yaml` (or several `_desc-<name>.yaml`, chosen with
  `--filedesc=<name>`) says in `uses:` which task prepares them - a download into the cache, as `get-hf-dataset`
  does - and in `result_from_ctx:` where that task's result is (`'{{global.<storage key>}}'`); the result gives
  `path` and, when it can, `files`.
- **Sub-datasets**: one artifact for a whole set of inputs, each input a sub-dataset. `sub_datasets:` of its
  `_desc.yaml` names them in order (the first is the default), each with its `files` - all of them, in the order a
  program takes them (a folder may hold more, a meta file for instance: not taken, but a program can ask for one
  by name); without the list, the folder's files by name - its `number`, its `tags` and a `desc`:

  ```yaml
  sub_datasets:
    adpcm-0001:
      files: [data.adpcm]
      tags: [small]
      desc: the small input of cBench
    adpcm-0002:
      files: [data.adpcm]
  uses:
    - task: get-ctuning-dataset,e4bfa3539ac64d5f
      capsule: adpcm
  result_from_ctx: '{{global.get-ctuning-dataset}}'
  ```

  The files of a sub-dataset are in `files/<name>/` of the artifact when they are kept with it (`files/adpcm-0001/
  data.adpcm`); for the others, the task of `uses:` prepares a folder with a folder per sub-dataset and names it
  in `path_root` of its result (one download for the whole set, once) - `sub_datasets_folder: adpcm` says where
  inside it when what is prepared holds several sets, one folder each (a Hugging Face repository with a folder
  per kind, fetched with `get-hf-dataset ... filename: adpcm/*`). A sub-dataset is asked for with the
  dataset - `<dataset>/<name>`, `<dataset>/<name>/<file>` - or as the file: `<name>`, `<name>/<file>`, or
  `<file>` alone for a file of the default one; without a name the first, or a choice (`-q`: the first). The
  result adds `sub_dataset` (the one taken) and `sub_datasets` (all of them, in order):

  ```bash
  cx program run cbench-telecom-adpcm-c cpu --dataset=ctuning-adpcm/adpcm-0007 -q
  cx program run cbench-telecom-adpcm-c cpu --dataset=ctuning-adpcm --dataset_file=adpcm-0007 -q
  cx task run dataset ctuning-adpcm adpcm-0007/data.adpcm -q
  ```

  A set grows by a folder in `files/` (or in what `uses:` prepares) and a line in `sub_datasets:`.

- **A file**: `filename` that is an existing path takes that file, no artifact looked up.
