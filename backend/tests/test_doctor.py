import importlib.util
import json

from helpers import ROOT

spec = importlib.util.spec_from_file_location("doctor", ROOT / "scripts" / "doctor.py")
doctor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(doctor)


def fake_run(outputs: dict[str, tuple[int, str]]):
    """A run() that answers by the command's first two words; anything else isn't installed."""

    def run(*cmd, cwd=None):
        return outputs.get(" ".join(str(c) for c in cmd[:2]), (127, ""))

    return run


def make_venv(root):
    py = root / ".venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.touch()
    return str(py)


def write_locks(root, wanted: dict, installed: dict | None):
    frontend = root / "frontend"
    (frontend / "node_modules").mkdir(parents=True)
    (frontend / "package-lock.json").write_text(json.dumps({"packages": {"": {}, **wanted}}))
    if installed is not None:
        hidden = frontend / "node_modules" / ".package-lock.json"
        hidden.write_text(json.dumps({"packages": installed}))


def levels(results):
    return [r.level for r in results]


def test_parse_version():
    assert doctor.parse_version("v22.12.0") == (22, 12, 0)
    assert doctor.parse_version("Python 3.12.4") == (3, 12, 4)
    assert doctor.parse_version("command not found") == ()


def test_python_missing_venv_says_run_setup(tmp_path):
    [result] = doctor.check_python(tmp_path, fake_run({}))
    assert result.level == "fail" and "make setup" in result.fix


def test_python_wrong_version(tmp_path):
    py = make_venv(tmp_path)
    [result] = doctor.check_python(tmp_path, fake_run({f"{py} --version": (0, "Python 3.13.1")}))
    assert result.level == "fail" and "3.13.1" in result.what


def test_python_missing_package_names_it(tmp_path):
    py = make_venv(tmp_path)
    run = fake_run(
        {
            f"{py} --version": (0, "Python 3.12.4"),
            f"{py} -c": (1, "Traceback ...\nModuleNotFoundError: No module named 'boto3'"),
        }
    )
    [result] = doctor.check_python(tmp_path, run)
    assert result.level == "fail" and "boto3" in result.what


def test_python_ready(tmp_path):
    py = make_venv(tmp_path)
    run = fake_run({f"{py} --version": (0, "Python 3.12.4"), f"{py} -c": (0, "")})
    assert levels(doctor.check_python(tmp_path, run)) == ["ok"]


def test_node_not_installed(tmp_path):
    [result] = doctor.check_node(tmp_path, fake_run({}))
    assert result.level == "fail" and "22.12" in result.fix


def test_node_too_old(tmp_path):
    [result] = doctor.check_node(tmp_path, fake_run({"node --version": (0, "v20.11.1")}))
    assert result.level == "fail" and "v20.11.1" in result.what


def test_frontend_packages_not_installed(tmp_path):
    write_locks(tmp_path, {"node_modules/vite": {"version": "8.3.3"}}, installed=None)
    run = fake_run({"node --version": (0, "v22.12.0")})
    [result] = doctor.check_node(tmp_path, run)
    assert result.level == "fail" and "npm install" in result.fix


def test_frontend_packages_out_of_date(tmp_path):
    write_locks(
        tmp_path,
        {"node_modules/vite": {"version": "8.3.3"}},
        installed={"node_modules/vite": {"version": "8.2.0"}},
    )
    run = fake_run({"node --version": (0, "v22.12.0")})
    [result] = doctor.check_node(tmp_path, run)
    assert result.level == "fail" and "vite" in result.what


def test_frontend_packages_match_when_optional_ones_are_skipped(tmp_path):
    # npm skips optional packages built for other platforms; that isn't a stale install.
    write_locks(
        tmp_path,
        {
            "node_modules/vite": {"version": "8.3.3"},
            "node_modules/@rollup/rollup-linux-x64-gnu": {"version": "4.0.0", "optional": True},
        },
        installed={"node_modules/vite": {"version": "8.3.3"}},
    )
    run = fake_run({"node --version": (0, "v22.12.0")})
    assert levels(doctor.check_node(tmp_path, run)) == ["ok"]


def test_hooks_not_set(tmp_path):
    [result] = doctor.check_hooks(tmp_path, fake_run({"git config": (1, "")}))
    assert result.level == "fail" and "core.hooksPath .githooks" in result.fix


def test_hooks_set(tmp_path):
    assert levels(doctor.check_hooks(tmp_path, fake_run({"git config": (0, ".githooks")}))) == [
        "ok"
    ]


def test_config_error_shows_the_message(tmp_path):
    py = make_venv(tmp_path)
    message = "ConfigError: account 222222222222 is listed twice in janitor.yaml (line 9)."
    [result] = doctor.check_config(tmp_path, fake_run({f"{py} -c": (1, message)}), env={})
    assert result.level == "fail" and "line 9" in result.what


def test_config_without_real_file_uses_example(tmp_path):
    py = make_venv(tmp_path)
    [result] = doctor.check_config(tmp_path, fake_run({f"{py} -c": (0, "mock")}), env={})
    assert result.level == "ok" and "janitor.example.yaml" in result.what


def test_real_config_also_checks_aws_profiles(tmp_path):
    py = make_venv(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "janitor.yaml").touch()
    calls = []

    def run(*cmd, cwd=None):
        calls.append(cmd)
        if "check_profiles" in cmd[-1]:
            return 1, "ProfileError: admin profile example-tools isn't in your AWS config"
        return 0, "mock"

    config_ok, profiles = doctor.check_config(tmp_path, run, env={})
    assert config_ok.level == "ok" and str(py) == calls[0][0]
    assert profiles.level == "fail" and "example-tools" in profiles.what
