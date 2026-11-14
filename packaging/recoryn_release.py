"""Frozen dispatch only; importing this module does not open devices or install."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(*, gui: bool) -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--release-smoke":
        from release_smoke import run

        print(json.dumps(run(), ensure_ascii=True, sort_keys=True))
        return 0
    if len(sys.argv) > 1 and sys.argv[1] in (
        "--release-install",
        "--release-rollback",
        "--release-uninstall",
    ):
        from release_manager import ReleaseError, default_root, install, rollback, uninstall

        action = sys.argv[1]
        parser = argparse.ArgumentParser(description="Recoryn 사용자 범위 설치 관리")
        parser.add_argument("--destination", type=Path, default=None)
        options = parser.parse_args(sys.argv[2:])
        try:
            root = options.destination or default_root()
            if action == "--release-install":
                result = install(Path(sys.executable).parent, root)
            elif action == "--release-rollback":
                result = rollback(root)
            else:
                result = uninstall(root)
        except ReleaseError as exc:
            print(json.dumps({"error": str(exc)}))
            return 2
        except (OSError, ValueError):
            print(json.dumps({"error": "INSTALL_OPERATION_FAILED"}))
            return 2
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return 0 if result.get("uninstalled", True) else 2
    if gui:
        from recoryn.ui import launch

        return launch()
    from recoryn.cli import main as cli_main

    return cli_main()
