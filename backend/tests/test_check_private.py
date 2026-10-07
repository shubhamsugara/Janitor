import importlib.util

from helpers import ROOT

spec = importlib.util.spec_from_file_location(
    "check_private", ROOT / "scripts" / "check_private.py"
)
check_private = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_private)

REAL_LOOKING = "1234567" + "89012"  # split so this file passes the check itself


def test_flags_real_looking_account_id(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text(f"account {REAL_LOOKING}\n")
    problems = check_private.check([path], [])
    assert len(problems) == 1 and "a.txt:1" in problems[0]


def test_allows_fake_ids_and_other_numbers(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text(
        '"111111111111" arn:aws:rds:us-east-1:222222222222:snapshot:x '
        "base-linux-20260101000000 ami-0000123456789abcd 12345678901\n"
    )
    assert check_private.check([path], []) == []


def test_flags_private_terms_without_printing_them(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("Built for ExampleCorp\n")
    problems = check_private.check([path], ["examplecorp"])
    assert len(problems) == 1 and "examplecorp" not in problems[0].lower()


def test_repository_is_clean():
    assert check_private.check(check_private.git_files(), check_private.private_terms()) == []


def test_flags_console_formatted_account_id(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text(
        "acct " + "1234-5678" + "-9012\nid " + "1234 5678" + " 9012\nok 1111-1111-1111\n"
    )
    assert len(check_private.check([path], [])) == 2
