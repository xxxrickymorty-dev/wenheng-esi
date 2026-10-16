# -*- coding: utf-8 -*-
"""Merge material-evidence/*/report.json referencePbr blocks into object-sculpt-spec.json.

Idempotent: run after tools/build_spec.py whenever the spec is rebuilt from source.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SPEC_PATH = HERE / "object-sculpt-spec.json"
EVIDENCE = HERE / "material-evidence"


def main() -> int:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    merged = 0
    for material in spec.get("materials", []):
        mid = material.get("id")
        report_path = EVIDENCE / str(mid) / "report.json"
        if not report_path.exists():
            print("no report for", mid)
            continue
        report = json.loads(report_path.read_text(encoding="utf-8"))
        maps = {}
        for channel in ("albedo", "roughness", "height", "normal", "ao"):
            entry = (report.get("maps") or {}).get(channel)
            if isinstance(entry, dict) and entry.get("path"):
                filename = entry.get("url") or Path(entry["path"]).name
                maps[channel] = {
                    "path": entry["path"],
                    # Served route: the preview (and any local harness) maps /material-evidence/*
                    # to the on-disk folder; the generated factory loads this URL directly.
                    "url": f"/material-evidence/{mid}/{filename}",
                    "channel": channel,
                    "source": "reference-pixel-extraction",
                }
        material["referencePbr"] = {
            "usable": bool(report.get("verdict") == "pass" and float(report.get("confidence", 0)) >= 0.7),
            "confidence": report.get("confidence"),
            "estimatedFidelity": report.get("estimatedFidelity"),
            "extractionTool": "forge/stage1_intake/extract_pbr_evidence.py",
            "sourceCrop": report.get("sourceImage"),
            "palette": report.get("palette"),
            "maps": maps,
            "diagnostics": {
                "roughnessBase": (report.get("diagnostics") or {}).get("mapStats", {}).get("roughnessBase"),
                "roughnessVariation": (report.get("diagnostics") or {}).get("mapStats", {}).get("roughnessVariation"),
                "normalStrength": (report.get("diagnostics") or {}).get("mapStats", {}).get("normalStrength"),
            },
            "limitation": report.get("limitation"),
        }
        merged += 1
    SPEC_PATH.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"merged referencePbr for {merged} materials")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
