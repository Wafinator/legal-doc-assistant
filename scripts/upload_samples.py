"""Upload the sample documents in tests/data to a running server.

uv run python scripts/upload_samples.py [--url http://localhost:8000]
"""

import argparse
import json
import urllib.request
from pathlib import Path

SAMPLES = {
    "services_agreement": "Master Services Agreement (Northwind / Harbor Freight)",
    "motion_to_dismiss": "Motion to Dismiss: Harbor Freight v. Northwind",
}
DATA_DIR = Path(__file__).resolve().parent.parent / "tests" / "data"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://localhost:8000")
    args = parser.parse_args()

    for name, title in SAMPLES.items():
        content = (DATA_DIR / f"{name}.txt").read_text(encoding="utf-8")
        request = urllib.request.Request(
            f"{args.url}/documents",
            data=json.dumps({"title": title, "content": content}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request) as response:
            doc = json.load(response)
        print(f"uploaded document_id={doc['id']}: {doc['title']}")


if __name__ == "__main__":
    main()
