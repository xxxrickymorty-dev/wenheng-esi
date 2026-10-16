# -*- coding: utf-8 -*-
"""Deeper debug: world boxes of selected sculptRuntime nodes (double-offset check)."""
from __future__ import annotations

import json

from playwright.sync_api import sync_playwright

WATCH = [
    "dome-assembly", "dome-shell", "dome-drum", "west-roof", "east-roof",
    "tower-roof-west", "tower-belfry-west", "rear-roof-west", "pavilion-roof-west",
    "west-hall", "tower-west", "central-block", "pavilion-west",
]


def main() -> int:
    script = """
    (watch) => {
      const viewer = window.__SCULPT_VIEWER__;
      const THREE = viewer.THREE;
      const nodes = viewer.root.userData.sculptRuntime?.nodes || {};
      const out = [];
      watch.forEach((key) => {
        const node = nodes[key];
        if (!node) { out.push({ key, missing: true }); return; }
        const box = new THREE.Box3().setFromObject(node);
        out.push({
          key,
          parent: node.parent ? node.parent.name : null,
          localPos: node.position.toArray().map(v => Math.round(v * 10) / 10),
          world: [box.min.toArray().map(v => Math.round(v * 10) / 10), box.max.toArray().map(v => Math.round(v * 10) / 10)],
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
        for row in page.evaluate(script, WATCH):
            print(json.dumps(row, ensure_ascii=False))
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
