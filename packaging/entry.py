"""Frozen application entry point. Self-test is explicit and available only with a tiny local fixture."""

import argparse
import sys
from pathlib import Path

from spike.launcher.app import main

if __name__ == "__main__":
    if "--package-smoke" in sys.argv:
        from package_smoke import run

        parser = argparse.ArgumentParser()
        parser.add_argument("--package-smoke", type=Path, required=True)
        parser.add_argument("--report", type=Path, required=True)
        args = parser.parse_args()
        raise SystemExit(run(args.package_smoke, args.report))
    main()
