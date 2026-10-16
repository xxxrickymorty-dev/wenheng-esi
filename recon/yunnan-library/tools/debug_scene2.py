# -*- coding: utf-8 -*-
"""Deeper debug: world boxes of every named sculptRuntime node."""
from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> int:
    script = """
    () => {
      const viewer = window.__SCULPT_VIEWER__;
      const THREE = viewer.THREE;
      const nodes = viewer.root.userData.sculptRuntime?.nodes || {};
      const meshes = viewer.root.userData.sculptRuntime?.meshes || {};
      const out = [];
      Object.keys(nodes).forEach((key) => {
        const node = nodes[key];
        const box = new THREE.Box3().setFromObject(node);
        const mesh = meshes[key];
        let geomBox = null;
        if (mesh && mesh.geometry) {
          mesh.geometry.computeBoundingBox();
          const b = mesh.geometry.boundingBox;
          geomBox = [b.min.toArray().map(v => Math.round(v * 100) / 100), b.max.toArray().map(v => Math.round(v * 100) / 100)];
        }
        out.push({
          key,
          type: node.type,
          pos: node.position.toArray().map(v => Math.round(v * 10) / 10),
          world: [box.min.toArray().map(v => Math.round(v * 10) / 10), box.max.toArray().map(v => Math.round(v * 10) / 10)],
          geomBox,
          visible: node.visible,
        });
      });
      return out;
    }
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True, args=["--use-angle=swiftshader"])
        page = browser.new_page(viewport={"width": 1440, "height": 810})
        page.goto("http://127.0.0.1:5199/?view=front-elevation", wait_until="load", timeout=30000)
        page.wait_for_function("() => window.__SCULPT_READY__ === true", timeout=30000)
        data = page.evaluate(script)
        for row in data:
            print(json.dumps(row, ensure_ascii=False))
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
