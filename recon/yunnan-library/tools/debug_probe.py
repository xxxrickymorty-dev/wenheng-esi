# -*- coding: utf-8 -*-
"""Find meshes intersecting given world-space probe boxes."""
from __future__ import annotations

import json

from playwright.sync_api import sync_playwright

SCRIPT = """
() => {
  const viewer = window.__SCULPT_VIEWER__;
  const THREE = viewer.THREE;
  const probes = {
    roof: new THREE.Box3(new THREE.Vector3(-20, 33.4, -33), new THREE.Vector3(20, 34.5, -2)),
    edge: new THREE.Box3(new THREE.Vector3(-90, 4, -20), new THREE.Vector3(-60, 26, 10)),
    treewall: new THREE.Box3(new THREE.Vector3(-20, 2, 10), new THREE.Vector3(20, 16, 60)),
  };
  const out = {};
  for (const key of Object.keys(probes)) out[key] = [];
  viewer.root.traverse((obj) => {
    const mesh = obj;
    if (!mesh.isMesh && !mesh.isInstancedMesh) return;
    const box = new THREE.Box3().setFromObject(mesh);
    for (const key of Object.keys(probes)) {
      if (probes[key].intersectsBox(box)) {
        const spec = mesh.material && mesh.material.userData ? mesh.material.userData.sculptMaterial : null;
        out[key].push({
          name: mesh.name,
          mat: spec ? spec.id : (mesh.material ? mesh.material.type : null),
          min: box.min.toArray().map(v => Math.round(v)),
          max: box.max.toArray().map(v => Math.round(v)),
        });
      }
    }
  });
  for (const key of Object.keys(out)) out[key] = out[key].slice(0, 12);
  return out;
}
"""


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True, args=["--use-angle=swiftshader"])
        page = browser.new_page(viewport={"width": 1440, "height": 810})
        page.goto("http://127.0.0.1:5199/?view=front-elevation", wait_until="load", timeout=30000)
        page.wait_for_function("() => window.__SCULPT_READY__ === true", timeout=30000)
        data = page.evaluate(SCRIPT)
        for key, rows in data.items():
            print("==", key)
            for row in rows:
                print(" ", json.dumps(row, ensure_ascii=False))
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
