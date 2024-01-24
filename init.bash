#!/usr/bin/bash

# configuration
DVCSTORE_DIR='/mnt/data/dvcstore'
DEVGPT_DIR='/mnt/data/MSR_Challenge_2024/DevGPT-data.v9'


# initialize virtualenv, if needed
echo "Checking for virtualenv (venv)"
if [ ! -e venv/bin/activate ]; then
    python3 -m venv venv
fi

if [ -z "$VIRTUAL_ENV" ]; then
    echo "Run 'source venv/bin/activate'"
    echo "then re-run this script '$0'"
    exit
fi

# virtualenv is initialized
echo "Installing Python packages"
pip install -q -r requirements.txt
#pip install -q --upgrade --editable .  # Not needed because of first line in requirements.txt

# configuring DVC remote
DVC_REMOTES="$(dvc remote list)"
if grep -q -F -e "$DVCSTORE_DIR" <<<"$DVC_REMOTES"; then
    echo "DVC storage looks to be configured correctly:"
    echo "    $DVC_REMOTES"
else
    echo "Adding local storage to .dvc/config.local"
    cat <<-EOF >>.dvc/config.local
    [core]
        remote = local
    ['remote "local"']
        url = $DVCSTORE_DIR
EOF
fi

# try to create symlink to externally downloaded DevGPT dataset,
# if possible, instead of having each user to re-download it
if [ ! -e 'data/external/DevGPT' ]; then
    if [ -d "$DEVGPT_DIR" ]; then
        echo "Linking '$DEVGPT_DIR'"
        ln -s "$DEVGPT_DIR" data/external/DevGPT
    else
        echo "Could not find '$DEVGPT_DIR' directory with DevGPT dataset"
    fi
else
    echo "'data/external/DevGPT' already exists"
fi

# check if we are inside Git repository, and if it is not the case,
# configure DVC to not require to be run from inside git repo
INIT_SCRIPT_DIR="$(realpath "${0%/*}")"  # "$(realpath $(dirname "$0")"
if [ "$(git rev-parse --is-inside-work-tree)" = "true" ]; then
    GIT_REPO_TOPDIR="$(realpath "$(git rev-parse --show-toplevel)")"
    if [ "$INIT_SCRIPT_DIR" = "$GIT_REPO_TOPDIR" ]; then
        echo "WARNING: possibly incorrect git repository found:"
        echo "- top directory of git repo:  $GIT_REPO_TOPDIR"
        echo "- directory with this script: $INIT_SCRIPT_DIR"
    fi
else
    echo "Not inside Git repository; configuring DVC to handle this case"
    dvc config --local core.no_scm true
fi


# getting data from DVC
echo "Retrieving data from DVC"
dvc pull
