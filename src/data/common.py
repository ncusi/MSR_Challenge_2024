"""Common code for scripts in src/data/ directory (remaining bits)"""
from pathlib import Path

from src.utils.files import load_json_with_checks

# constants
ERROR_ARGS = 1


def load_repositories_json(repositories_info_path: Path) -> dict:
    """Load <repositories.json> and convert into dict with project name as key

    The returned dict has the following structure:

    {
        '<project_name>': {  # e.g. "sqlalchemy"
            'project': <project_name>,  # e.g. "sqlalchemy"
            'repository_url': <repository_url>,  # e.g. "https://github.com/sqlalchemy/sqlalchemy.git"
            'repository_path': <repository_dir>,  # e.g. "/mnt/data/MSR_Challenge_2024/repositories/sqlalchemy"
        }, ...
    }

    :param Path repositories_info_path:  path to <repositories.json> file
    :return: data extracted from <repositories.json> file
    :rtype: dict
    """
    repo_clone_info = load_json_with_checks(repositories_info_path,
                                            file_descr="<repositories.json>",
                                            data_descr="info about cloned repos",
                                            err_code=ERROR_ARGS, expected_type=list)
    repo_clone_data = {
        repo_info['project']: {
            key: value
            for key, value in repo_info.items()
            if key != 'project'
        }
        for repo_info in repo_clone_info
    }

    return repo_clone_data
