# -*- coding: utf-8 -*-
"""Raycast straight down over the central roof to identify the top surface mesh."""
from __future__ import annotations

import json

from playwright.sync_api import sync_playwright

SCRIPT = """
() => {
  const viewer = window.__SCULPT_VIEWER__;
  const THREE = viewer.THREE;
  const ray = new THREE.Raycaster();
  const dir = new THREE.Vector3(0, -1, 0);
  const hits = [];
  for (const [x, z] of [[6, -12], [-6, -22], [12, -26], [-14, -8], [0, -17]]) {
    ray.set(new THREE.Vector3(x, 80, z), dir);
    const result = ray.intersectObject(viewer.root, true).slice(0, 3).map((h) => ({
      n: h.object.name,
      y: Math.round(h.point.y * 10) / 10,
      mat: h.object.material && h.object.material.userData && h.object.material.userData.sculptMaterial
        ? h.object.material.userData.sculptMaterial.id
        : (h.object.material ? h.object.material.type : null),
    }));
    hits.push({ x, z, result });
  }
  return hits;
}
"""


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True, args=["--use-angle=swiftshader"])
        page = browser.new_page(viewport={"width": 1440, "height": 810})
        page.goto("http://127.0.0.1:5199/?view=front-elevation", wait_until="load", timeout=30000)
        page.wait_for_function("() => window.__SCULPT_READY__ === true", timeout=30000)
        for row in page.evaluate(SCRIPT):
            print(json.dumps(row, ensure_ascii=False))
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
