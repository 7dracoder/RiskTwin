"""Shared bootstrap for the operator scripts.

Every script in this directory is meant to be run directly (`python
scripts/<name>.py`), so the repository root has to be on `sys.path` before any
`packages.*` import resolves.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def configure_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )


def banner(title: str) -> None:
    print(f"\n=== {title} ===")


def field(label: str, value: object) -> None:
    print(f"  {label:<26} {value}")
