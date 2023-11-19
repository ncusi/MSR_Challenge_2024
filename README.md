# Code for MSR'24 Mining Challenge

https://2024.msrconf.org/track/msr-2024-mining-challenge

## Virtual environment

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

## Installing dependencies

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
$ cat <<EOF >.dvc/config.local
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
