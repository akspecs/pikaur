""" This file is licensed under GPLv3, see https://www.gnu.org/licenses/ """

import sys
import os
import tempfile
from subprocess import Popen
from unittest import TestCase
from typing import Optional, List, NoReturn

from pikaur.main import main
from pikaur.args import CachedArgs, parse_args  # pylint:disable=no-name-in-module
from pikaur.pacman import PackageDB  # pylint:disable=no-name-in-module


TEST_DIR = os.path.dirname(os.path.realpath(__file__))


WRITE_DB = bool(os.environ.get('WRITE_DB'))


class TestPopen(Popen):
    stderr_text: Optional[str] = None
    stdout_text: Optional[str] = None


def spawn(cmd: List[str], **kwargs) -> TestPopen:
    with tempfile.TemporaryFile() as out_file:
        with tempfile.TemporaryFile() as err_file:
            proc = TestPopen(cmd, stdout=out_file, stderr=err_file, **kwargs)
            proc.communicate()
            out_file.seek(0)
            err_file.seek(0)
            proc.stdout_text = out_file.read().decode('utf-8')
            proc.stderr_text = err_file.read().decode('utf-8')
            return proc


def color_line(line: str, color_number: int) -> str:
    result = ''
    if color_number >= 8:
        result += "\033[0;1m"
        color_number -= 8
    result += f"\033[03{color_number}m{line}"
    # reset font:
    result += "\033[0;0m"
    return result


class CmdResult:

    def __init__(
            self,
            returncode: Optional[int] = None,
            stdout: Optional[str] = None,
            stderr: Optional[str] = None
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def __repr__(self) -> str:
        return (
            f'<{self.returncode}>:\n'
            f'{self.stderr}\n'
            f'{self.stdout}\n'
        )

    def __eq__(self, other) -> bool:
        return ((
            self.stdout == other.stdout
        ) and (
            self.stderr == other.stderr
        ) and (
            self.returncode == other.returncode
        ))


class FakeExit(Exception):
    pass


class InterceptSysOutput():

    stdout_text: str
    stderr_text: str
    returncode: int

    def _fake_exit(self, code: int = 0) -> NoReturn:
        self.returncode = code
        raise FakeExit()

    def __init__(self, capture_stdout=True, capture_stderr=False) -> None:
        self.capture_stdout = capture_stdout
        self.capture_stderr = capture_stderr

    def __enter__(self) -> 'InterceptSysOutput':
        self.out_file = tempfile.TemporaryFile('w+', encoding='UTF-8')
        self.err_file = tempfile.TemporaryFile('w+', encoding='UTF-8')
        self.out_file.isatty = lambda: False  # type: ignore
        self.err_file.isatty = lambda: False  # type: ignore

        self._real_stdout = sys.stdout
        self._real_stderr = sys.stderr
        if self.capture_stdout:
            sys.stdout = self.out_file  # type: ignore
        if self.capture_stderr:
            sys.stderr = self.err_file  # type: ignore

        self._real_exit = sys.exit
        sys.exit = self._fake_exit  # type: ignore

        return self

    def __exit__(self, *_exc_details) -> None:
        sys.stdout = self._real_stdout
        sys.stderr = self._real_stderr
        sys.exit = self._real_exit

        self.out_file.flush()
        self.err_file.flush()
        self.out_file.seek(0)
        self.err_file.seek(0)
        self.stdout_text = self.out_file.read()
        self.stderr_text = self.err_file.read()
        self.out_file.close()
        self.err_file.close()


def pikaur(
        cmd: str, capture_stdout=True, capture_stderr=False, fake_makepkg=False
) -> CmdResult:

    PackageDB.discard_local_cache()

    # re-parse args:
    sys.argv = ['pikaur'] + cmd.split(' ') + (
        [
            '--noconfirm', '--hide-build-log',
        ] if '-S ' in cmd else []
    ) + (
        [
            '--makepkg-path=' + os.path.join(TEST_DIR, 'fake_makepkg'),
        ] if fake_makepkg else []
    )
    CachedArgs.args = None  # pylint:disable=protected-access
    parse_args()
    # monkey-patch to force always uncolored output:
    CachedArgs.args.color = 'never'  # type: ignore # pylint:disable=protected-access
    print(color_line('\n => ', 10) + ' '.join(sys.argv))

    intercepted: InterceptSysOutput
    with InterceptSysOutput(
            capture_stderr=capture_stderr,
            capture_stdout=capture_stdout
    ) as _intercepted:

        try:
            main()
        except FakeExit:
            pass
        intercepted = _intercepted

    return CmdResult(
        returncode=intercepted.returncode,
        stdout=intercepted.stdout_text,
        stderr=intercepted.stderr_text,
    )


def fake_pikaur(cmd_args: str):
    pikaur(
        f'{cmd_args} --mflags=--noextract',
        fake_makepkg=True, capture_stdout=True
    )


def pacman(cmd: str) -> CmdResult:
    args = ['pacman'] + cmd.split(' ')
    proc = spawn(args)
    return CmdResult(
        returncode=proc.returncode,
        stdout=proc.stdout_text,
        stderr=proc.stderr_text,
    )


class PikaurTestCase(TestCase):
    # pylint: disable=invalid-name

    def assertInstalled(self, pkg_name: str) -> None:
        self.assertEqual(
            pacman(f'-Qi {pkg_name}').returncode, 0
        )

    def assertNotInstalled(self, pkg_name: str) -> None:
        self.assertEqual(
            pacman(f'-Qi {pkg_name}').returncode, 1
        )

    def assertProvidedBy(self, dep_name: str, provider_name: str) -> None:
        cmd_result = pacman(f'-Qsq {dep_name}').stdout
        self.assertTrue(
            cmd_result
        )
        self.assertEqual(
            cmd_result.strip(),  # type: ignore
            provider_name
        )


class PikaurDbTestCase(PikaurTestCase):
    """
    tests which are modifying local package DB
    """

    def remove_packages(self, *pkg_names: str) -> None:
        pikaur('-Rs --noconfirm ' + ' '.join(pkg_names))
        for name in pkg_names:
            self.assertNotInstalled(name)

    def run(self, test_result):
        if WRITE_DB:
            return super().run(self, test_result)
        test_result.addSkip(
            self,
            test_result.getDescription(self) + '. Not writing to local package DB.'
        )
