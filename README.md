# Code for MSR'24 Mining Challenge

https://2024.msrconf.org/track/msr-2024-mining-challenge

## Virtual environment

To avoid dependency conflicts, it is strongly recommended to create
a [virtual environment][venv], for example with:
```cli
$ python3 -m venv venv
```

This needs to be done only once, from top directory of the project.  
For each session, you should activate the environment:
```cli
$ source venv/bin/activate
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
$ python -m pip install -r requirements.txt
```
Note: the above assumes that you have activated virtual environment (venv). 

[requirements.txt]: https://pip.pypa.io/en/stable/reference/requirements-file-format/
