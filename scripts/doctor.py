#!/usr/bin/env python3
"""Check that this machine can build and run Janitor, and say how to fix whatever isn't ready.

Usage: python3 scripts/doctor.py   (or make doctor)
Stdlib only, so it runs even when .venv is broken. It changes no file and never calls AWS.
"""

import json
import os
import re
import socket
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIN_NODE = (22, 12)

# A validation error prints as "field: message", one per line, without pydantic's links.
LOAD_CONFIG = """
import sys
from janitor.config import load_config
try:
    config = load_config()
except Exception as exc:
    if hasattr(exc, "errors"):
        for e in exc.errors():
            where = ".".join(map(str, e["loc"])) or "janitor.yaml"
            print(f"{where}: {e['msg'].removeprefix('Value error, ')}", file=sys.stderr)
    else:
        print(exc, file=sys.stderr)
    sys.exit(1)
print(config.provider)
"""

CHECK_PROFILES = """
import sys
from janitor.config import load_config
from janitor.providers.session import check_profiles
try:
    check_profiles(load_config())
except Exception as exc:
    print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
    sys.exit(1)
"""


@dataclass
class Result:
    level: str  # "ok", "fail", or "note"
    what: str
    fix: str = ""


def parse_version(text: str) -> tuple[int, ...]:
    """'v22.12.0' or 'Python 3.12.4' -> (22, 12, 0). Empty when there is no version."""
    match = re.search(r"\d+(?:\.\d+)+", text)
    return tuple(int(part) for part in match.group().split(".")) if match else ()


def run(*cmd: str, cwd: Path = ROOT) -> tuple[int, str]:
    """(exit code, output), or (127, "") when the program isn't installed."""
    try:
        done = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=60, check=False
        )
    except (FileNotFoundError, PermissionError):
        return 127, ""
    except subprocess.TimeoutExpired:
        return 124, f"{cmd[0]} didn't answer within 60 seconds"
    return done.returncode, (done.stdout + done.stderr).strip()


def last_line(text: str) -> str:
    lines = text.strip().splitlines()
    return lines[-1] if lines else "no output"


def venv_python(root: Path) -> Path:
    return root / ".venv" / "bin" / "python"


def check_python(root: Path, run=run) -> list[Result]:
    py = venv_python(root)
    if not py.exists():
        return [Result("fail", "There is no Python environment in .venv.", "Run make setup.")]
    _, out = run(str(py), "--version")
    version = parse_version(out)
    if version[:2] != (3, 12):
        found = ".".join(map(str, version)) or "a Python that doesn't start"
        return [
            Result(
                "fail",
                f".venv has {found}; Janitor needs Python 3.12.",
                "Delete the .venv folder, then run make setup.",
            )
        ]
    code, out = run(str(py), "-c", "import janitor, fastapi, boto3, pytest, ruff")
    if code != 0:
        return [
            Result(
                "fail",
                f"Backend packages are missing ({last_line(out)}).",
                "Run make setup to reinstall them. A pull may have added one.",
            )
        ]
    return [Result("ok", "Python 3.12 environment with the backend installed.")]


def stale_packages(lock: dict, installed: dict) -> list[str]:
    """Packages package-lock.json wants that node_modules lacks or holds at another version.

    npm skips optional packages built for other platforms, so those don't count.
    """
    have = installed.get("packages", {})
    stale = []
    for path, info in lock.get("packages", {}).items():
        if not path.startswith("node_modules/") or info.get("optional"):
            continue
        if have.get(path, {}).get("version") != info.get("version"):
            stale.append(path.removeprefix("node_modules/"))
    return stale


def check_node(root: Path, run=run) -> list[Result]:
    code, out = run("node", "--version")
    if code == 127:
        return [
            Result(
                "fail",
                "Node isn't installed.",
                "Install Node 22.12 or later, then run make setup.",
            )
        ]
    if parse_version(out)[:2] < MIN_NODE:
        return [
            Result(
                "fail",
                f"Node {out} is too old; the UI build needs 22.12 or later.",
                "Install a newer Node, then run cd frontend && npm install.",
            )
        ]
    frontend = root / "frontend"
    installed = frontend / "node_modules" / ".package-lock.json"
    if not installed.exists():
        return [
            Result(
                "fail",
                "Frontend packages aren't installed.",
                "Run make setup, or cd frontend && npm install.",
            )
        ]
    stale = stale_packages(
        json.loads((frontend / "package-lock.json").read_text()),
        json.loads(installed.read_text()),
    )
    if stale:
        names = ", ".join(stale[:3]) + (f" and {len(stale) - 3} more" if len(stale) > 3 else "")
        return [
            Result(
                "fail",
                f"Frontend packages are out of date ({names}).",
                "Run cd frontend && npm install.",
            )
        ]
    return [Result("ok", f"Node {out} with the frontend packages installed.")]


def check_hooks(root: Path, run=run) -> list[Result]:
    _, out = run("git", "config", "core.hooksPath")
    if out.strip() != ".githooks":
        return [
            Result(
                "fail",
                "The leak check doesn't run before commits.",
                "Run git config core.hooksPath .githooks.",
            )
        ]
    return [Result("ok", "The leak check runs before every commit.")]


def check_build(root: Path) -> list[Result]:
    if (root / "frontend" / "dist" / "index.html").exists():
        return [Result("ok", "The UI is built (frontend/dist).")]
    return [
        Result(
            "note",
            "The UI isn't built yet.",
            "make run builds it. make dev doesn't need it.",
        )
    ]


def check_config(root: Path, run=run, env=os.environ) -> list[Result]:
    py = venv_python(root)
    if not py.exists():
        return []  # check_python already says to run make setup
    real = root / env.get("JANITOR_CONFIG", "config/janitor.yaml")
    shown = real.relative_to(root) if real.is_relative_to(root) else real
    name = str(shown) if real.exists() else "config/janitor.example.yaml (mock data)"
    code, out = run(str(py), "-c", LOAD_CONFIG, cwd=root)
    if code != 0:
        return [
            Result(
                "fail",
                f"{name} can't be used. {out}",
                "Change what the message names in that file, then run make doctor again.",
            )
        ]
    provider = last_line(out)
    results = [Result("ok", f"{name} loads (provider: {provider}).")]
    if real.exists() or provider == "aws":
        code, out = run(str(py), "-c", CHECK_PROFILES, cwd=root)
        if code != 0:
            results.append(
                Result(
                    "fail",
                    f"make run-aws won't start. {out}",
                    "Fix the profile in ~/.aws/config as the message says; see README, "
                    "Run it against AWS.",
                )
            )
        else:
            results.append(Result("ok", "AWS profiles are ready for make run-aws."))
    return results


def listening(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def janitor_running() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=2) as response:
            return json.load(response).get("status") == "ok"
    except (OSError, ValueError):
        return False


def check_ports() -> list[Result]:
    results = []
    for port, use in ((8080, "the API"), (5173, "the dev UI")):
        if not listening(port):
            continue
        if port == 8080 and janitor_running():
            results.append(
                Result(
                    "note",
                    "Janitor is already running on port 8080.",
                    "Use it at http://127.0.0.1:8080, or stop it (Ctrl+C in its terminal) "
                    "before starting another.",
                )
            )
        else:
            results.append(
                Result(
                    "note",
                    f"Something is using port {port}, which {use} needs.",
                    f"Find it with lsof -iTCP:{port} -sTCP:LISTEN, then stop it.",
                )
            )
    return results


def main() -> int:
    results = (
        check_python(ROOT)
        + check_node(ROOT)
        + check_hooks(ROOT)
        + check_build(ROOT)
        + check_config(ROOT)
        + check_ports()
    )
    for r in results:
        print(f"{r.level.upper():5} {r.what}")
        if r.fix:
            print(f"      -> {r.fix}")
    failed = sum(r.level == "fail" for r in results)
    if failed:
        print(f"\n{failed} problem(s). Fix the first one, then run make doctor again.")
        return 1
    print("\nThis machine is ready: make dev, make run, or make run-aws.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
