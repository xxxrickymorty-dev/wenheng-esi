# export_meshes.py
#
# Blender 无头导出：把道具的几何（顶点 / 法线 / UV / 索引）打成 base64，
# 写成 meshes.js，供网页里的三维场景直接读。
#
# 怎么跑（务必用 blender.exe，不是 blender-launcher.exe）：
#     F:\blender\blender.exe --background --python F:\blender\wenheng\export_meshes.py
#
# 几条约定（改之前先看 PLAN-Blender道具.md 第 2.3 节）：
#   · 1 个 Blender 单位 = 1 米
#   · 每件道具的原点放在「底面中心」——摆位置时一句话搞定
#   · 送出去之前把位移 / 旋转 / 缩放全部归零，再切成三角面
#   · Blender 是 Z 轴朝上、网页里是 Y 轴朝上，导出时转一下：
#     (x, y, z) → (x, z, -y)
#   · 部件名字用英文（top / leg-1 这种），中文名在导出和排查里都麻烦
#   · 几何的来源是 wh_models.py——交互式建模与这里共用，两边不会各长各的

import base64
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wh_models  # noqa: E402

# 输出目录走纯英文路径——Blender 在 Windows 下对中文路径不稳
OUT_DIR = r"F:\blender\wenheng"
OUT_JS = os.path.join(OUT_DIR, "meshes.js")
OUT_REPORT = os.path.join(OUT_DIR, "meshes_report.json")


# ---------- 小工具 ----------
def b64_f32(values):
    """把一串浮点数压成 base64，体积只有文本数组的四分之一左右。"""
    data = struct.pack("<%df" % len(values), *values)
    return base64.b64encode(data).decode("ascii")


def b64_u16(values):
    data = struct.pack("<%dH" % len(values), *values)
    return base64.b64encode(data).decode("ascii")


def round_key(x, digits):
    return round(x, digits)


# ---------- 从网格取数据 ----------
def bmesh_to_part(part_name, mat_name, bm, to_y_up=True):
    """把一个网格拆成网页能直接用的四段数据。

    同一个位置、同一个朝向、同一个贴图坐标的点只留一份，
    其余共用——方块这样有硬边的东西会变成 24 个点（而不是 8 个），
    棱角才不会糊。
    """
    bm.normal_update()

    uv_layer = bm.loops.layers.uv.active

    pos = []
    nrm = []
    uv = []
    idx = []
    seen = {}

    for face in bm.faces:
        # 用面法线（硬边）：木桌的棱要见棱见角
        fn = face.normal
        for loop in face.loops:
            co = loop.vert.co
            if uv_layer is not None:
                u, v = loop[uv_layer].uv
            else:
                u, v = 0.0, 0.0

            key = (
                round_key(co.x, 6), round_key(co.y, 6), round_key(co.z, 6),
                round_key(fn.x, 5), round_key(fn.y, 5), round_key(fn.z, 5),
                round_key(u, 5), round_key(v, 5),
            )
            if key in seen:
                idx.append(seen[key])
                continue

            i = len(pos) // 3
            seen[key] = i
            idx.append(i)

            if to_y_up:
                # Z 朝上 → Y 朝上
                pos.extend([co.x, co.z, -co.y])
                nrm.extend([fn.x, fn.z, -fn.y])
            else:
                pos.extend([co.x, co.y, co.z])
                nrm.extend([fn.x, fn.y, fn.z])
            uv.extend([u, v])

    return {
        "name": part_name,
        "mat": mat_name,
        "pos": b64_f32(pos),
        "nrm": b64_f32(nrm),
        "uv": b64_f32(uv),
        "idx": b64_u16(idx),
        "_count": {"verts": len(pos) // 3, "tris": len(idx) // 3},
        "_pos": pos,  # 留着算尺寸，不写进 js
    }


def bbox_of_pos(chunks):
    """把几段顶点并起来算一圈包围盒，返回 [宽, 高, 深] 与最小 / 最大点。"""
    xs, ys, zs = [], [], []
    for pos in chunks:
        xs.extend(pos[0::3])
        ys.extend(pos[1::3])
        zs.extend(pos[2::3])
    mn = [min(xs), min(ys), min(zs)]
    mx = [max(xs), max(ys), max(zs)]
    size = [mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2]]
    return size, mn, mx


def part_bbox(pos):
    xs = pos[0::3]
    ys = pos[1::3]
    zs = pos[2::3]
    mn = [min(xs), min(ys), min(zs)]
    mx = [max(xs), max(ys), max(zs)]
    return [mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2]], mn, mx


def pack_props(named_bms):
    """{部件名: (材质名, 网格)} → 网页读的那份 + 一份给人看的报表。"""
    parts_out = []
    parts_report = []
    chunks = []
    for name in named_bms:
        mat_name, bm = named_bms[name]
        part = bmesh_to_part(name, mat_name, bm)
        bm.free()
        parts_out.append({k: part[k] for k in ("name", "mat", "pos", "nrm", "uv", "idx")})
        size, mn, mx = part_bbox(part["_pos"])
        parts_report.append({
            "name": name,
            "mat": mat_name,
            "bbox_m": [round(size[0], 6), round(size[1], 6), round(size[2], 6)],
            "min": [round(x, 6) for x in mn],
            "max": [round(x, 6) for x in mx],
            "verts": part["_count"]["verts"],
            "tris": part["_count"]["tris"],
        })
        chunks.append(part["_pos"])
    size, mn, mx = bbox_of_pos(chunks)
    entry = {
        "bbox": [round(size[0], 6), round(size[1], 6), round(size[2], 6)],
        "parts": parts_out,
    }
    report = {
        "bbox_m": [round(size[0], 6), round(size[1], 6), round(size[2], 6)],
        "min": [round(x, 6) for x in mn],
        "max": [round(x, 6) for x in mx],
        "part_count": len(parts_out),
        "tris": sum(p["tris"] for p in parts_report),
        "parts": parts_report,
    }
    return entry, report


# ---------- 主流程 ----------
def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    meshes = {}
    report = {}

    entry, rep = pack_props(wh_models.build_test_cube())
    meshes["test-cube"] = entry
    report["test-cube"] = rep

    entry, rep = pack_props(wh_models.build_test_desk())
    meshes["test-desk"] = entry
    report["test-desk"] = rep

    entry, rep = pack_props(wh_models.build_reading_desk())
    meshes["reading-desk"] = entry
    report["reading-desk"] = rep

    lines = [
        "/* Generated by export_meshes.py. Do not edit by hand. */",
        "window.WH_MESHES = " + json.dumps(meshes, ensure_ascii=True) + ";",
    ]
    with open(OUT_JS, "w", encoding="ascii", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    with open(OUT_REPORT, "w", encoding="ascii", newline="\n") as f:
        json.dump(report, f, indent=2, ensure_ascii=True)

    # 打到控制台，方便跟网页那边对
    print("MESH_REPORT=" + json.dumps(report, ensure_ascii=True))
    print("WROTE=" + OUT_JS)


if __name__ == "__main__":
    main()
