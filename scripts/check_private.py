#!/usr/bin/env python3
"""Fail if a file git would commit holds a real-looking account ID or a private term.

Usage: python3 scripts/check_private.py [files...]   (default: tracked + untracked, not ignored)
Private terms come from the gitignored .private-terms file, one per line. Stdlib only.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT_ID = re.compile(r"(?<![0-9A-Za-z])\d{12}(?![0-9A-Za-z])")


def is_fake(number: str) -> bool:
    return len(set(number)) == 1  # 111111111111-style


def git_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [ROOT / line for line in out.splitlines() if line]


def private_terms() -> list[str]:
    path = ROOT / ".private-terms"
    if not path.exists():
        return []
    lines = (line.strip().lower() for line in path.read_text().splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def check(paths: list[Path], terms: list[str]) -> list[str]:
    problems = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for match in ACCOUNT_ID.finditer(line):
                if not is_fake(match.group()):
                    problems.append(
                        f"{path}:{lineno}: 12-digit number that isn't a fake account ID"
                    )
            lower = line.lower()
            if any(term in lower for term in terms):
                problems.append(f"{path}:{lineno}: contains a term from .private-terms")
    return problems


def main(argv: list[str]) -> int:
    paths = [Path(arg) for arg in argv] if argv else git_files()
    problems = check(paths, private_terms())
    for problem in problems:
        print(problem)
    if problems:
        print(
            f"{len(problems)} problem(s). Replace them with fake values (111111111111-style), then commit."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
