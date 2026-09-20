#!/usr/bin/env python3
"""Typeset a reading: report.md → report.html → report.pdf.

Thin wrapper around ``jyotish build``, kept so the documented command keeps
working. The code lives in ``jyotish.report``, where it has tests.

    python3 scripts/build-report.py clients/ivan --pdf
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "plugins" / "jyotish"))

from jyotish.report import BuildError, main  # noqa: E402

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    target = Path(args[0] if args else ".")
    try:
        print(main(target, pdf="--pdf" in sys.argv))
    except BuildError as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
