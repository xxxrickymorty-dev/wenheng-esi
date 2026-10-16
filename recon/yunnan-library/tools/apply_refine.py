# -*- coding: utf-8 -*-
"""Inject the hand-authored refine layer into a freshly generated factory (idempotent).

Usage: python tools/apply_refine.py [path-to-createYNULibraryModel.ts]
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
TARGET = HERE / "src" / "createYNULibraryModel.ts"
IMPORT_LINE = "import { refineYNULibraryModel } from './refineYNULibrary';"
CALL_LINE = "  refineYNULibraryModel(root, root.userData.sculptRuntime as ProceduralModelRuntime);"
MARKER = "// [apply_refine] refinement layer applied"


def main(argv: list[str]) -> int:
    target = Path(argv[0]) if argv else TARGET
    text = target.read_text(encoding="utf-8")
    if MARKER in text:
        print("already applied:", target)
        return 0

    # import after the three import block
    lines = text.splitlines()
    last_import = max(i for i, line in enumerate(lines) if line.startswith("import "))
    lines.insert(last_import + 1, IMPORT_LINE)

    # call before the final `return root;` of the model factory
    call_index = None
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() == "return root;":
            call_index = i
            break
    if call_index is None:
        raise SystemExit("could not find 'return root;' in the generated factory")
    lines.insert(call_index, "")
    lines.insert(call_index, MARKER)
    lines.insert(call_index + 1, CALL_LINE)

    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("refine layer injected:", target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
