"""Audit Humanoid Remap Studio preset catalog samples.

Run from the add-on source tree with regular Python:

    python tools/audit_preset_catalog.py --json
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path


def load_preset_catalog():
    here = Path(__file__).resolve()
    package_dir = here.parents[1]
    module_path = package_dir / "preset_catalog.py"
    spec = importlib.util.spec_from_file_location("humanoid_remap_preset_catalog", module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Print the full machine-readable audit report.")
    parser.add_argument("--min-core-hits", type=int, default=12)
    args = parser.parse_args(argv)

    preset_catalog = load_preset_catalog()
    report = preset_catalog.audit_preset_sample_sets(min_core_hits=args.min_core_hits)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1

    print(
        f"profiles={report['profileCount']} sources={report['sourceCount']} "
        f"samples={report['sampleCount']} passed={report['passed']} failed={report['failed']}"
    )
    for item in report["results"]:
        status = "OK" if item["status"] == "pass" else "FAIL"
        print(
            f"[{status}] {item['id']}: expected={item['expectedProfile']} "
            f"matched={item['matchedProfile']} confidence={item['confidence']} core={item['coreHits']}"
        )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
