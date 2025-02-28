import os
from pathlib import Path

from .args import parse_args
from .aur import find_aur_packages, get_repo_url
from .aur_deps import get_aur_deps_list
from .core import check_runtime_deps, interactive_spawn
from .exceptions import PackagesNotFoundInRepoError
from .i18n import translate
from .pacman import PackageDB
from .pprint import print_stdout
from .print_department import print_not_found_packages
from .urllib import wrap_proxy_env


def cli_getpkgbuild() -> None:
    args = parse_args()
    pwd = Path(os.path.curdir).resolve()
    aur_pkg_names = args.positional

    aur_pkgs, not_found_aur_pkgs = find_aur_packages(aur_pkg_names)
    repo_pkgs = []
    not_found_repo_pkgs = []
    for pkg_name in not_found_aur_pkgs:
        try:
            repo_pkg = PackageDB.find_repo_package(pkg_name)
        except PackagesNotFoundInRepoError:
            not_found_repo_pkgs.append(pkg_name)
        else:
            repo_pkgs.append(repo_pkg)

    if repo_pkgs:
        check_runtime_deps(["asp"])

    if not_found_repo_pkgs:
        print_not_found_packages(not_found_repo_pkgs)

    if args.deps:
        aur_pkgs = aur_pkgs + get_aur_deps_list(aur_pkgs)

    for aur_pkg in aur_pkgs:
        name = aur_pkg.name
        repo_path = pwd / name
        print_stdout()
        interactive_spawn(wrap_proxy_env([
            "git",
            "clone",
            get_repo_url(aur_pkg.packagebase),
            str(repo_path),
        ]))

    for repo_pkg in repo_pkgs:
        name = repo_pkg.name
        repo_path = pwd / name
        action = "checkout"
        if repo_path.exists():
            action = "update"
        print_stdout()
        print_stdout(translate(f"Package '{name}' going to be cloned into '{repo_path}'..."))
        interactive_spawn([
            "asp",
            action,
            name,
        ])
