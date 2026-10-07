import importlib.util
import io
import zipfile

from helpers import ROOT

spec = importlib.util.spec_from_file_location("fetch_icons", ROOT / "scripts" / "fetch_icons.py")
fetch_icons = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch_icons)


def _zip(names):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in names:
            archive.writestr(name, f"<svg>{name}</svg>")
    return buffer.getvalue()


def test_picks_48px_icons_by_pattern(tmp_path):
    data = _zip(
        [
            "Resource-Icons/Res_Compute/Res_Amazon-EC2_AMI_32.svg",
            "Resource-Icons/Res_Compute/Res_Amazon-EC2_AMI_48.svg",
            "Architecture-Service-Icons/Arch_Compute/48/Arch_Amazon-EC2-Auto-Scaling_48.svg",
            "__MACOSX/Res_Amazon-EC2_Instance_48.svg",
        ]
    )
    missing = fetch_icons.extract(data, tmp_path)
    assert (
        tmp_path / "ami.svg"
    ).read_text() == "<svg>Resource-Icons/Res_Compute/Res_Amazon-EC2_AMI_48.svg</svg>"
    assert (tmp_path / "asg.svg").exists()
    assert "instance" in missing  # the __MACOSX copy doesn't count


def test_finds_the_package_link():
    html = '<a href="https://d1.awsstatic.com/webteam/architecture-icons/q3-2026/Icon-package_07312026.zip">Icons</a>'
    assert fetch_icons.package_url(html).endswith("Icon-package_07312026.zip")
    assert fetch_icons.package_url('<a href="//d1.awsstatic.com/x/Icon-package_1.zip">').startswith(
        "https://"
    )
    assert fetch_icons.package_url("<html></html>") is None
