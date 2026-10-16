# -*- coding: utf-8 -*-
"""Capture review screenshots of the YNU Library preview (playwright + system Chrome).

System Python (playwright lives there), channel="chrome" per the project's three.js recipe.

Usage:
  python tools/shoot.py <out_subdir> [view1 view2 ...] [--az ALL] [--light MODE]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:5199/"
DEFAULT_VIEWS = ["front-elevation", "front-aerial-3q", "close-aerial", "rear-quarter", "west-profile", "east-profile"]


def main(argv: list[str]) -> int:
    out_sub = argv[0] if argv else "blockout"
    views = [a for a in argv[1:] if not a.startswith("--")]
    light = "reference"
    stripped = "--stripped" in argv
    for a in argv:
        if a.startswith("--light="):
            light = a.split("=", 1)[1]
    if not views:
        views = DEFAULT_VIEWS
    out_dir = HERE / "render" / out_sub
    out_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True, args=["--use-angle=swiftshader"])
        page = browser.new_page(viewport={"width": 1440, "height": 810}, device_scale_factor=1)
        page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
        page.on(
            "console",
            lambda msg: errors.append(f"console.{msg.type}: {msg.text}")
            if msg.type == "error" and "favicon" not in msg.text and "404" not in msg.text
            else None,
        )
        for view in views:
            if view.startswith("az:"):
                url = f"{BASE}?az={view.split(':', 1)[1]}&light={light}" + ("&stripped=1" if stripped else "")
                suffix = (f"-az{view.split(':', 1)[1]}") + ("-stripped" if stripped else "")
                shot_name = f"orbit{suffix}.png"
            else:
                url = f"{BASE}?view={view}&light={light}" + ("&stripped=1" if stripped else "")
                suffix = "-stripped" if stripped else ""
                shot_name = f"{view}{suffix}.png"
            page.goto(url, wait_until="load", timeout=30000)
            try:
                page.wait_for_function("() => window.__SCULPT_READY__ === true", timeout=30000)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{view}: ready wait failed: {exc}")
            # wait for async reference-map textures; tolerate the no-loads case
            try:
                page.wait_for_function("() => window.__SCULPT_LOADED__ === true", timeout=8000)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(600)
            shot = out_dir / shot_name
            page.screenshot(path=str(shot))
            stats = page.evaluate("() => window.__SCULPT_STATS__ ? window.__SCULPT_STATS__() : null")
            results[view] = stats
            print(f"{view}: {stats} -> {shot.name}")
        browser.close()
    print("STATS", json.dumps(results, ensure_ascii=False))
    if errors:
        print("ERRORS")
        for e in errors:
            print(" ", e)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
