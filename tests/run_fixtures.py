"""Run validate.py against every fixture and compare with expected.json.

Usage: python tests/run_fixtures.py [--idle SECONDS]
Exits non-zero if any fixture doesn't behave as expected.
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIX = HERE / "fixtures"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--idle", type=int, default=12)
    a = ap.parse_args()
    expected = json.loads((FIX / "expected.json").read_text())
    failures = 0
    for name, exp in expected.items():
        out = Path(tempfile.mkstemp(suffix=".json")[1])
        subprocess.run([sys.executable, str(HERE.parent / "scripts" / "validate.py"),
                        "--repo", name, "--pr-dir", str(FIX / name), "--license", str(FIX / "LICENSE"),
                        "--out", str(out), "--idle", str(a.idle)], check=True, capture_output=True)
        r = json.loads(out.read_text())
        problems = []
        if r["crashed"]:
            problems.append(f"crashed: {r['crashed']}")
        if "blocks" in exp and len(r["blocks"]) != exp["blocks"]:
            problems.append(f"expected {exp['blocks']} blocks, got {len(r['blocks'])}")
        if "blocks_min" in exp and len(r["blocks"]) < exp["blocks_min"]:
            problems.append(f"expected at least {exp['blocks_min']} blocks, got {len(r['blocks'])}")
        if "block_contains" in exp and not any(exp["block_contains"] in b for b in r["blocks"]):
            problems.append(f"no block mentions {exp['block_contains']!r}")
        if "alerts" in exp and len(r["alerts"]) != exp["alerts"]:
            problems.append(f"expected {exp['alerts']} alerts, got {len(r['alerts'])}")
        if "alerts_min" in exp and len(r["alerts"]) < exp["alerts_min"]:
            problems.append(f"expected at least {exp['alerts_min']} alerts, got {len(r['alerts'])}")
        if "warns" in exp and len(r["warns"]) != exp["warns"]:
            problems.append(f"expected {exp['warns']} warnings, got {len(r['warns'])}")
        if "warns_contains" in exp and not any(exp["warns_contains"] in w for w in r["warns"]):
            problems.append(f"no warning mentions {exp['warns_contains']!r}")
        cpu = (r.get("runtime") or {}).get("cpu_cores")
        status = "ok  " if not problems else "FAIL"
        failures += bool(problems)
        print(f"{status} {name:13} blocks={len(r['blocks'])} warns={len(r['warns'])} alerts={len(r['alerts'])} cpu={cpu}")
        for p in problems:
            print(f"       {p}")
        if problems:
            for k in ("blocks", "warns", "alerts"):
                for item in r[k]:
                    print(f"       {k[:-1]}: {item}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
