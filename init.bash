#!/usr/bin/bash

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
if grep -q -F -e '/mnt/data/dvcstore' <<<"$DVC_REMOTES"; then
    echo "DVC storage looks to be configured correctly:"
    echo "    $DVC_REMOTES"
else
    echo "Adding local storage to .dvc/config.local"
    cat <<-EOF >>.dvc/config.local
    [core]
        remote = local
    ['remote "local"']
        url = /mnt/data/dvcstore
EOF
fi

# getting data from DVC
echo "Retrieving data from DVC"
dvc pull
