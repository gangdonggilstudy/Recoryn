"""Check separate statement/branch budgets; combined percentages can hide gaps."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main(path: Path) -> int:
    report = json.loads(path.read_text(encoding="utf-8"))
    groups: dict[str, list[int]] = {
        name: [0, 0, 0, 0]
        for name in ("domain", "capture", "jobs", "storage", "security", "content")
    }
    for name, data in report["files"].items():
        normalized = name.replace("\\", "/")
        for package, counts in groups.items():
            if f"recoryn/{package}/" in normalized:
                summary = data["summary"]
                counts[0] += summary["covered_lines"]
                counts[1] += summary["num_statements"]
                counts[2] += summary["covered_branches"]
                counts[3] += summary["num_branches"]
    total = report["totals"]
    groups["all"] = [
        total["covered_lines"],
        total["num_statements"],
        total["covered_branches"],
        total["num_branches"],
    ]
    passed = True
    for name, (lines, statements, branches, decisions) in groups.items():
        line_percent = lines * 100 / statements if statements else 0
        branch_percent = branches * 100 / decisions if decisions else 100
        line_min, branch_min = (85, 80) if name == "all" else (95, 90)
        ok = line_percent >= line_min and branch_percent >= branch_min
        passed = passed and ok
        print(
            f"{name}: line={line_percent:.2f}%/{line_min}% "
            f"branch={branch_percent:.2f}%/{branch_min}% {'PASS' if ok else 'FAIL'}"
        )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("coverage.json")))
