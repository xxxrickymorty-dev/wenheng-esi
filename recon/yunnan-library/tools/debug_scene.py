# -*- coding: utf-8 -*-
"""Debug helper: dump the built model's node tree with world bounding boxes."""
from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent.parent


def main() -> int:
    script = """
    () => {
      const viewer = window.__SCULPT_VIEWER__;
      if (!viewer) return { error: 'no viewer' };
      const THREE = viewer.THREE;
      const out = [];
      viewer.root.children.forEach((child) => {
        const box = new THREE.Box3().setFromObject(child);
        out.push({
          name: child.name,
          children: child.children.length,
          min: box.min.toArray().map(v => Math.round(v * 100) / 100),
          max: box.max.toArray().map(v => Math.round(v * 100) / 100),
        });
      });
      const whole = new THREE.Box3().setFromObject(viewer.root);
      return { root: { min: whole.min.toArray(), max: whole.max.toArray() }, nodes: out };
    }
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True, args=["--use-angle=swiftshader"])
        page = browser.new_page(viewport={"width": 1440, "height": 810})
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto("http://127.0.0.1:5199/?view=front-elevation", wait_until="load", timeout=30000)
        page.wait_for_function("() => window.__SCULPT_READY__ === true", timeout=30000)
        data = page.evaluate(script)
        print(json.dumps(data, ensure_ascii=False, indent=1))
        for e in errors:
            print("PAGEERROR:", e)
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
