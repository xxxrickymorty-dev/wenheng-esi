# -*- coding: utf-8 -*-
"""Run extract_pbr_evidence for every material crop in material-evidence/crops.json."""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
EXT = r"C:\Users\damn\.agents\skills\img2threejs\forge\stage1_intake\extract_pbr_evidence.py"


def main() -> int:
    manifest = json.loads((HERE / "material-evidence" / "crops.json").read_text(encoding="utf-8"))
    fails = []
    for mid in manifest:
        crop = str(HERE / "material-evidence" / "crops" / f"{mid}.png")
        out = HERE / "material-evidence" / mid
        rep = out / "report.json"
        proc = subprocess.run(
            [sys.executable, EXT, crop, "--out-dir", str(out), "--material-id", mid, "--report", str(rep)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            fails.append(mid)
            print("FAIL", mid, proc.returncode, (proc.stderr or proc.stdout)[-200:])
        else:
            data = json.loads(rep.read_text(encoding="utf-8"))
            print(f"{mid:20s} conf={data.get('confidence')} verdict={data.get('verdict')}")
    print("fails:", fails)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
