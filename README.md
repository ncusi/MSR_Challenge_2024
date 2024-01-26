# How I Learned to Stop Worrying and Love ChatGPT
Replication package for MSR'24 Mining Challenge

https://2024.msrconf.org/track/msr-2024-mining-challenge

The code can be found in the following repository on GitHub:<br>
<https://github.com/ncusi/MSR_Challenge_2024><br>
The data will be also available on [DagsHub][]:<br>
<https://dagshub.com/ncusi/MSR_Challenge_2024>

[DagsHub]: https://dagshub.com/docs/index.html "DagsHub: A Single Source of Truth for your AI Projects"

## First time setup

You can set up the environment for this package, following
the recommended practices (described later in this document),
by running the [`init.bash`](init.bash) Bash script, and following
its instructions.

Note that this script assumes that it is run on Linux, or Linux-like
system.  For other operating systems, following the steps described 
in this document manually.

### Virtual environment

To avoid dependency conflicts, it is strongly recommended to create
a [virtual environment][venv], for example with:
```cli
python3 -m venv venv
```

This needs to be done only once, from the top directory of the project.  
For each session, you should activate the environment:
```cli
source venv/bin/activate
```
This would make command line prompt include "(venv) " as prefix,
thought it depends on the shell used.

A virtual environment, either directly like shown above or
by using `pipx`, might be required if you cannot install system
packages, but Python is configured in a very specific way:

> error: externally-managed-environment
>
> × This environment is externally managed

[venv]: https://python.readthedocs.io/en/stable/library/venv.html

### Installing dependencies

You can install dependencies defined in [requirements.txt][] file
with `pip` using the following command:
```cli
python -m pip install -r requirements.txt
```
Note: the above assumes that you have activated virtual environment (venv). 

[requirements.txt]: https://pip.pypa.io/en/stable/reference/requirements-file-format/


## Running with DVC

You can re-run whole computation pipeline with `dvc repro`, or at least
those parts that were made to use **[DVC][]** (Data Version Control) tool.

[DVC]: https://dvc.org/

You can also run experiments with `dvc exp run`.

**NOTE** that DVC works best in a Git repository, and is by default configured
to require it.  If you clone this project with Git, it will work out of
the box; if you get this project from Figshare (<https://doi.org/10.6084/m9.figshare.24771117>)
you will need to either:
- use [DVC without Git][initializing-dvc-without-git]
  by setting `core.no_scm` config option value to true in the [DVC configuration][dvc-configuration]
  with `dvc config --local core.no_scm true`, or
- run `git init` inside unpacked directory with replication package

[initializing-dvc-without-git]: https://dvc.org/doc/command-reference/init#initializing-dvc-without-git "dvc init | Initializing DVC without Git"
[dvc-configuration]: https://dvc.org/doc/user-guide/project-structure/configuration


### Configuring local DVC cache _(optional)_

Because the initial external DevGPT dataset is quite large (it is 650 MB
as *.zip file, and 3.9 GB uncompressed into directory), you might want
to store DVC cache in some other place than your home repository.

You can do that with [`dvc cache dir`][dvc-cache-dir] command:
```cli
dvc cache dir --local /mnt/data/username/.dvc/cache
```
where you need to replace `username` with your login (on Linux you can
find it with the help of `whoami` command).

### Configuring local DVC storage

To avoid recomputing results, which takes time, you can configure
local [dvc remote storage][dvc-remote-storage], for example:

```cli
cat <<EOF >>.dvc/config.local
[core]
    remote = local
['remote "local"']
    url = /mnt/data/dvcstore
EOF
```

Then you will be able to download computed data with `dvc pull`,
and upload your results for others in the team with `dvc push`.
This assumes that all of you have access to `/mnt/data/dvcstore`,
either via doing the work on the same host (perhaps remotely),
or it is network storage available for the whole team.

[dvc-cache-dir]: https://dvc.org/doc/command-reference/cache/dir
[dvc-remote-storage]: https://dvc.org/doc/user-guide/data-management/remote-storage

### Description of DVC stages

DVC pipeline is composed of 14 stages (see [`dvc.yaml`](dvc.yaml) file).
The stages for analyzing commit data, pull request (PR) data, and issues data
have similar dependencies. The graph of dependencies shown below
(created from the output of `dvc dag --md`) is therefore simplified
for readability.

```mermaid
flowchart TD
        node1["clone_repos"]
        node13["repo_stats_git"]
        node14["repo_stats_github"]
        node2["{commit,pr,issues}_agg"]
        node3["{commit,pr,issues}_similarities"]
        node4["{commit,pr,issues}_survival"]
        node5["download_DevGPT"]
        node5-->node13
        node1-->node2
        node1-->node4
        node1-->node13
        node5-->node14
        node1-->node14
        node2-->node4
        node5-->node1
        node5-->node2
        node2-->node3
        node1-->node3
        node5-->node3
```

The notation used to describe the acyclic directed graph (DAG) of DVC pipeline
dependencies (the goal of which is to reduce the `dvc dag` graph size)
is to be understood as _brace expansion_.  For example, `{c,d,b}e` expands
to `ce`, `de`, `ce`.  This means that the following graph fragment:
```mermaid
flowchart LR
    node0["clone_repos"]
    node1["{commit,pr,issues}_agg"]
    node2["{commit,pr,issues}_survival"]
    node0-->node1
    node1-->node2
```
expands in the following way:
```mermaid
flowchart LR
    node0["clone_repos"]
    node1a["commit_agg"]
    node2a["commit_survival"]
    node1b["pr_agg"]
    node2b["pr_survival"]
    node1c["issues_agg"]
    node2c["issues_survival"]
    node0-->node1a
    node0-->node1b
    node0-->node1c
    node1a-->node2a
    node1b-->node2b
    node1c-->node2c
```

Each of the stages is described in [`dvc.yaml`](dvc.yaml) using `desc` field.
You can get list of stages with their descriptions with the `dvc stage list`
command:

| **Stage**           | **Description**                                                     |
|---------------------|---------------------------------------------------------------------|
| download_DevGPT     | Download DevGPT dataset v9 from Zenodo                              |
| clone_repos         | Clone all repositories included in DevGPT dataset                   |
| commit_agg          | Latest commit sharings to CSV + per-project aggregates              |
| pr_agg              | Latest pr (pull request) sharings to CSV + per-project aggregates   |
| issue_agg           | Latest issue sharings to CSV + per-project aggregates               |
| commit_survival     | Changes and lines survival (via blame) for latest commit sharings   |
| pr_survival         | Changes and lines survival (via blame) for latest pr sharings       |
| pr_split_survival   | Changes and lines survival (via blame) for pr sharings, all commits |
| issue_survival      | Changes and lines survival (via blame) for latest issue sharings    |
| repo_stats_git      | Repository stats from git for all cloned project repos              |
| repo_stats_github   | Repository info from GitHub for all cloned project repos            |
| commit_similarities | ChatGPT <-> commit diff similarities for commit sharings            |
| pr_similarities     | ChatGPT <-> commit diff similarities for PR sharings                |
| issue_similarities  | ChatGPT <-> commit diff similarities for issue sharings             |

### Additional stages' requirements

Running some of the DVC pipeline stages have additional requirements,
like Internet access, or `git` installed, or a validGitHub API key.

The following DVC stages require Internet access to work:
- download_DevGPT
- clone_repos
- pr_agg
- issue_agg
- repo_stats_github

The following DVC stages require `git` installed to work:
- clone_repos
- commit_survival
- pr_survival
- pr_split_survival
- issue_survival
- repo_stats_git

The following DVC stage requires GitHub API token to work,
because it uses GitHub's GraphQL API (which requires authentication):
- issue_agg

The following DVC stages would run faster with GitHub API token,
because of much increased limits for authenticated GitHub REST API access:
- pr_agg
- issue_agg
- repo_stats_github

To update or replace GitHub API token, _currently_ you will need to
edit the following line in [`src/utils/github.py`](src/utils/github.py):
```python
GITHUB_API_TOKEN = "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"  # from jnareb
```
The token shown above expires on Mon, Apr 15 2024.

### No cloned repositories in DVC

Cloned repositories of projects included in the DevGPT dataset 
are not stored in DVC. This is caused by space limitations and 
DVC inability to handle dangling symlinks inside directories 
to be put in DVC storage[^1].

Therefore, the clone_repos stage clones the repositories and
creates JSON file containing the summary of the results.  

The file (`data/repositories_download_status.json`) indicates
that certain stages of DVC pipeline need to have those repositories
cloned.  This file is neither stored in Git (thanks to 
`data/.gitignore`), nor in DVC (since it is marked as `cache: false`).

If you are interested only in modifying those stages that do not
require cloned repositories (those that do not use `git`, see
["_Additional stages' requirenemts_"](#additional-stages-requirements)
section), to avoid re-running the whole DVC pipeline, you can use
either:
- `dvc repro --single-item <target>...`
  to reproduce only given stages
  by turning off the recursive search for changed dependencies, or
- `dvc repro --downstream <starting target>...` to only execute
  the stages after the given targets in their corresponding pipelines,
  including the target stages themselves
See [`dvc repro` documentation](https://dvc.org/doc/command-reference/repro).

[^1]: See issue [#9971](https://github.com/iterative/dvc/issues/9971) in dvc repository

### Stages with checkpoints

The commit_similarities, pr_similarities, and issue_similarities are 
sinficantly time consuming.  Therefore, to avoid having to re-run them if they
are interrupted, they save their intermediate state as checkpoint file:
`data/interim/commit_sharings_similarities_df.checkpoint_data.json`, etc.

These checkpoint files are marked as persistent DVC data files, and are
not removed at the start of the stage.

Therefore, if you want to re-run those stages from scratch, you need
to remove those checkpoint files before running the stage, for example
with
```cli
rm data/interim/*.checkpoint_data.json
```


## Jupyter Notebooks

The final part of computations, and the visualization presented in the
_"How I Learned to Stop Worrying and Love ChatGPT"_ paper
was done with Jupyter Notebooks in the [`notebooks/`](notebooks/)
directory.

Those notebooks are described in detail in [`notebooks/README.md`](notebooks/README.md).

To be able to use [installed dependencies](#installing-dependencies)
when running those notebooks, it is recommended to start [JupyterLab][]
from this project top directory with:
```cli
jupyter lab --notebook-dir='.'
```

[JupyterLab]: https://jupyterlab.readthedocs.io/ "JupyterLab Documentation"
