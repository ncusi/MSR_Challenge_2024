# How I Learned to Stop Worrying and Love the ChatGPT
Replication package for MSR'24 Mining Challenge

https://2024.msrconf.org/track/msr-2024-mining-challenge

## First time setup

You can set up the environment for using this project, following
the recommended practices (described in later part of this document),
by running the [`init.bash`](init.bash) Bash script, and following
its instructions.

Note that this script assumes that it is run on Linux, or Linux-like
system.  For other operating systems, you are probably better following
the steps described in this document manually.

### Virtual environment

To avoid dependency conflicts, it is strongly recommended to create
a [virtual environment][venv], for example with:
```cli
python3 -m venv venv
```

This needs to be done only once, from top directory of the project.  
For each session, you should activate the environment:
```cli
source venv/bin/activate
```
This would make command line prompt include "(venv) " as prefix,
thought it depends on the shell used.

Using virtual environment, either directly like shown above, or
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
to require it.  If you cloned this project with Git, it should work out of
the box; if you got this project from Figshare (<https://figshare.com/s/c88797dd7db323886442>)
you would need to either:
- use [DVC without Git][initializing-dvc-without-git]
  by setting `core.no_scm` config option value to true in the [DVC configuration][dvc-configuration]
  with `dvc config --local core.no_scm true`, or
- run `git init` inside unpacked directory with replication package

Currently, the [`init.bash`](init.bash) script does not handle this
issue automatically.

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

Then you would be able to download computed data with `dvc pull`,
and upload your results for others in the team with `dvc push`.
This assumes that you all have access to `/mnt/data/dvcstore`,
either via doing the work on the same host (perhaps remotely),
or it is network storage available for all people in the team.

[dvc-cache-dir]: https://dvc.org/doc/command-reference/cache/dir
[dvc-remote-storage]: https://dvc.org/doc/user-guide/data-management/remote-storage

### Description of DVC stages

DVC pipeline is composed of 14 stages (see [`dvc.yaml`](dvc.yaml) file).
The stages for analyzing commit data, pull request (PR) data, and issues data
have similar dependencies. The graph of dependencies shown below
(created from the output of `dvc dag --md`) is therefore
simplified for readability.

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

Each of the stages is described in [`dvc.yaml`](dvc.yaml) using `desc`;
you can get list of stages with their descriptions with `dvc stage list`:

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
like requiring Internet access, or having `git` installed, or a valid
GitHub API key.

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

Because DVC does not handle well dangling symlinks (which happens
in some repositories) inside directories to be put in DVC storage[^1] ,
and because of the space limitations, cloned repositories of projects
included in the DevGPT dataset are not stored in DVC.

To make it possible to depend on repositories being cloned,
the clone_repos stage in addition to cloning repositories also
creates JSON file containing the summary of the results.  This file
(`data/repositories_download_status.json`) is then used to mark
that certain stages of DVC pipeline need to have those repositories
cloned.  This file is stored neither in Git (thanks to `data/.gitignore`),
not in DVC (thanks to being marked as `cache: false`).

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

The commit_similarities, pr_similarities, and issue_similarities take
a long time to run.  Therefore, to avoid having to re-run them if they
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
_"How I Learned to Stop Worrying and Love the ChatGPT"_ paper
was done with Jupyter Notebooks in the [`notebooks/`](notebooks/)
directory.

To be able to use [installed dependencies](#installing-dependencies),
it is recommended to start [JupyterLab][] from this project top directory
with
```cli
jupyter lab --notebook-dir='.'
```

<!-- The `notebooks/` directory includes the following Jupyter Notebooks: -->

[JupyterLab]: https://jupyterlab.readthedocs.io/ "JupyterLab Documentation"