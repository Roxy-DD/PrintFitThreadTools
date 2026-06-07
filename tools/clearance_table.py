"""Print an XY scale table for common metric threaded print-fit cutters."""

from __future__ import annotations

import argparse
import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "fusion", "PrintFitThreadTools", "lib")
if LIB not in sys.path:
    sys.path.insert(0, LIB)

from threadfit_core import METRIC_COARSE_PRESETS, clearance_scale_ratio  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clearance", type=float, default=0.20, help="single-side radial clearance in mm")
    parser.add_argument("specs", nargs="*", default=list(METRIC_COARSE_PRESETS), help="metric specs, e.g. M3 M4 M5")
    args = parser.parse_args()

    print("| Spec | Diameter mm | Clearance mm | XY scale |")
    print("| ---- | ----------- | ------------ | -------- |")
    for spec in args.specs:
        key = spec.upper()
        if key not in METRIC_COARSE_PRESETS:
            raise SystemExit("unknown spec: %s" % spec)
        diameter = METRIC_COARSE_PRESETS[key]["diameter"]
        scale = clearance_scale_ratio(diameter, args.clearance)
        print("| {spec} | {diameter:g} | {clearance:g} | {scale:.6f} |".format(
            spec=key,
            diameter=diameter,
            clearance=args.clearance,
            scale=scale,
        ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
