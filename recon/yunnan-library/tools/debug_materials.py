# -*- coding: utf-8 -*-
"""Inspect a mesh's material state (color, maps, sampled canvas pixels)."""
from __future__ import annotations

import json

from playwright.sync_api import sync_playwright


def main() -> int:
    script = """
    () => {
      const viewer = window.__SCULPT_VIEWER__;
      const meshes = viewer.root.userData.sculptRuntime?.meshes || {};
      const out = {};
      const targetKeys = ['central-block', 'west-hall', 'plaza-grounds', 'terrace-podium', 'tree-rows'];
      targetKeys.forEach((key) => {
        const mesh = meshes[key];
        if (!mesh) { out[key] = 'missing mesh'; return; }
        const m = mesh.material;
        const entry = {
          type: m.type,
          color: m.color ? m.color.getHexString() : null,
          roughness: m.roughness,
          metalness: m.metalness,
          hasMap: !!m.map,
          mapSource: m.map && m.map.image ? (m.map.image.tagName || typeof m.map.image) : null,
        };
        if (m.map && m.map.image && m.map.image.tagName === 'CANVAS') {
          const canvas = m.map.image;
          entry.mapSize = [canvas.width, canvas.height];
          try {
            const ctx = canvas.getContext('2d');
            const data = ctx.getImageData(Math.floor(canvas.width / 2), Math.floor(canvas.height / 2), 1, 1).data;
            entry.centerPixel = [data[0], data[1], data[2], data[3]];
          } catch (err) { entry.centerPixel = String(err); }
        }
        out[key] = entry;
      });
      const rt = viewer.root.userData.sculptRuntime;
      out.__runtimeKeys = Object.keys(rt || {});
      out.__meshCount = Object.keys(meshes).length;
      return out;
    }
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True, args=["--use-angle=swiftshader"])
        page = browser.new_page(viewport={"width": 1440, "height": 810})
        page.goto("http://127.0.0.1:5199/?view=front-elevation", wait_until="load", timeout=30000)
        page.wait_for_function("() => window.__SCULPT_READY__ === true", timeout=30000)
        print(json.dumps(page.evaluate(script), ensure_ascii=False, indent=1))
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
