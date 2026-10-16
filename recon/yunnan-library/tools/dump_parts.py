# -*- coding: utf-8 -*-
"""Dump the built model's part tree from the preview into a check_part_coverage manifest."""
from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent.parent

SCRIPT = """
() => {
  const viewer = window.__SCULPT_VIEWER__;
  const parts = [];
  viewer.root.traverse((obj) => {
    if (!obj.name) return;
    const meshFlag = !!(obj.isMesh || obj.isInstancedMesh);
    const componentId = obj.userData && obj.userData.sculptComponent && obj.userData.sculptComponent.id
      ? obj.userData.sculptComponent.id
      : null;
    if (meshFlag || componentId) {
      parts.push({ name: obj.name, mesh: meshFlag, componentId });
    }
  });
  return { parts };
}
"""


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True, args=["--use-angle=swiftshader"])
        page = browser.new_page(viewport={"width": 1440, "height": 810})
        page.goto("http://127.0.0.1:5199/?view=front-elevation", wait_until="load", timeout=30000)
        page.wait_for_function("() => window.__SCULPT_READY__ === true", timeout=30000)
        data = page.evaluate(SCRIPT)
        out = HERE / "render" / "parts-manifest.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"parts: {len(data['parts'])} -> {out}")
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
