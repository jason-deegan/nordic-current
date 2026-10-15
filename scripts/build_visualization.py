"""Generate the local Nordic Current HTML visualization report."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nordic_current.visualization import (  # noqa: E402
    REPORT_PATH,
    VisualizationDataError,
    build_report,
)


def main() -> int:
    try:
        report_path = build_report(PROJECT_ROOT)
    except VisualizationDataError as error:
        print(f"Could not build visualization: {error}", file=sys.stderr)
        return 1
    print(f"HTML report: {report_path}")
    print("Open that file in a web browser. The report is local and excluded from Git.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
