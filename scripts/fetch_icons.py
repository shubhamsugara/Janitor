#!/usr/bin/env python3
"""Download the official AWS Architecture Icons and keep the few Janitor uses. Stdlib only.

Usage: python3 scripts/fetch_icons.py [zip-url]
Writes frontend/public/aws-icons/<kind>.svg, which is gitignored: AWS allows these icons in
architecture diagrams, and keeping them out of the public repo avoids redistributing them.
"""

import io
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

PAGE = "https://aws.amazon.com/architecture/icons/"
OUT = Path(__file__).resolve().parents[1] / "frontend" / "public" / "aws-icons"
# File-name patterns per kind; the first match wins. AWS renames files between releases.
PATTERNS = {
    "ami": [r"^Res_Amazon-EC2_AMI_48\.svg$"],
    "snapshot": [
        r"^Res_Amazon-Elastic-Block-Store_Snapshot_48\.svg$",
        r"Elastic-Block-Store.*Snapshot.*48\.svg$",
    ],
    "volume": [
        r"^Res_Amazon-Elastic-Block-Store_Volume_48\.svg$",
        r"Elastic-Block-Store.*Volume.*48\.svg$",
    ],
    "rds_snapshot": [r"^Arch_Amazon-RDS_48\.svg$"],
    "database": [r"^Arch_Amazon-RDS_48\.svg$"],
    "instance": [r"^Res_Amazon-EC2_Instance_48\.svg$"],
    "asg": [r"^Arch_Amazon-EC2-Auto-Scaling_48\.svg$"],
    "launch_template": [r"^Arch_Amazon-EC2_48\.svg$"],
    "launch_config": [r"^Arch_Amazon-EC2_48\.svg$"],
    "account": [
        r"^Res_AWS-Organizations_Account_48\.svg$",
        r"Organizations.*Account.*48\.svg$",
    ],
}


def package_url(html: str) -> str | None:
    match = re.search(r'href="([^"]*Icon-package[^"]*\.zip)"', html)
    if not match:
        return None
    url = match.group(1)
    return "https:" + url if url.startswith("//") else url


def pick(names: list[str]) -> dict[str, str]:
    """kind -> zip member, by pattern order."""
    svgs = {
        n: n.rsplit("/", 1)[-1]
        for n in names
        if n.lower().endswith(".svg") and "__MACOSX" not in n
    }
    chosen = {}
    for kind, patterns in PATTERNS.items():
        for pattern in patterns:
            hit = next(
                (
                    n
                    for n, base in svgs.items()
                    if re.search(pattern, base, re.IGNORECASE)
                ),
                None,
            )
            if hit:
                chosen[kind] = hit
                break
    return chosen


def extract(data: bytes, out: Path = OUT) -> list[str]:
    """Write the chosen icons; return the kinds that had no match."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        chosen = pick(archive.namelist())
        out.mkdir(parents=True, exist_ok=True)
        for kind, member in chosen.items():
            (out / f"{kind}.svg").write_bytes(archive.read(member))
    return [kind for kind in PATTERNS if kind not in chosen]


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "janitor-fetch-icons"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def main(argv: list[str]) -> int:
    url = argv[0] if argv else package_url(download(PAGE).decode("utf-8", "replace"))
    if not url:
        print(
            f"Couldn't find the Icon package link on {PAGE}. Pass the zip URL as an argument."
        )
        return 1
    missing = extract(download(url))
    print(f"Wrote icons to {OUT}")
    if missing:
        print(
            "No icon found for: "
            + ", ".join(missing)
            + ". The UI shows a plain tile for these."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
