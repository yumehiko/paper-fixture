#!/usr/bin/env python3
"""Validate a placement file and write its resolved transforms as JSON."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.panel_input import InputError
from tools.assembly_input import evaluate_checks, load_placement


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="placement JSON")
    parser.add_argument("--repo-root", default=".", help="repository root for source paths")
    parser.add_argument("--report", help="optional resolved JSON report")
    arguments = parser.parse_args()
    try:
        resolved = load_placement(arguments.input, arguments.repo_root)
        report = evaluate_checks(resolved)
    except InputError as error:
        parser.error(str(error))
    output = {"placement": resolved, "verification": report}
    rendered = json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    if arguments.report:
        Path(arguments.report).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
