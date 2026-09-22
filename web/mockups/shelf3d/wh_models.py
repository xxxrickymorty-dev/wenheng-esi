# wh_models.py
#
# 道具的几何都从这里出。两头共用一套，免得「Blender 里看的」和「网页里跑的」不是同一个东西：
#   · 交互式建模：Blender 里的 Python 把它建成看得见的物体
#   · 生产导出：  无头脚本把它压成网页读的顶点数据
#
# 约定见 PLAN-Blender道具.md 第 2.3 节：1 单位 = 1 米、原点在底面中心、
# 切成三角面、导出时 Z 朝上转 Y 朝上。
#
# 材质槽（写进导出数据，网页那边按名字配质感）：
#   wood 木 / metal 金属 / glass 玻璃（灯罩）/ fabric 布（软包）/ carpet 地毯

import math

import bmesh
from mathutils import Vector


# ---------- 基础形 ----------
def assign_box_uvs(bm):
    """给每个面摊一块贴图坐标：朝哪条轴就往那两条轴上投影。

    方块类的东西这么摊不会拉变形；曲面（灯罩）上的坐标只是「有就行」，
    真要贴花纹再重做展开。
    """
    uv_layer = bm.loops.layers.uv.new("UVMap")
    for face in bm.faces:
        n = face.normal
        ax, ay, az = abs(n.x), abs(n.y), abs(n.z)
        for loop in face.loops:
            co = loop.vert.co
            if ax >= ay and ax >= az:
                u, v = co.y, co.z
            elif ay >= ax and ay >= az:
                u, v = co.x, co.z
            else:
                u, v = co.x, co.y
            loop[uv_layer].uv = (u, v)
    return uv_layer


def _finish(bm):
    bmesh.ops.triangulate(bm, faces=list(bm.faces))
    assign_box_uvs(bm)
    bm.normal_update()
    return bm


def box_bm(size, center, bevel=0.0):
    """一个方块的网格。size = (宽, 深, 高)；center = 中心点坐标。

    bevel > 0 时倒一圈小圆角——软包（椅面、靠背）用，免得像砖头。
    返回的网格用完要记得 .free()。
    """
    w, d, h = size
    cx, cy, cz = center
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * w + cx, v.co.y * d + cy, v.co.z * h + cz))
    if bevel > 0:
        try:
            bmesh.ops.bevel(
                bm,
                geom=list(bm.verts[:]) + list(bm.edges[:]),
                offset=bevel, segments=2, profile=0.7, affect="EDGES",
            )
        except Exception:
            pass  # 倒角失败就退化成直角，不影响链路
    return _finish(bm)


def cyl_bm(radius, height, center, segs=12):
    """圆柱：台灯的座、杆、顶珠用。轴沿 Z（朝上）。"""
    cx, cy, cz = center
    bm = bmesh.new()
    try:
        bmesh.ops.create_cone(
            bm, cap_ends=True, segments=segs,
            radius1=radius, radius2=radius, depth=height,
        )
    except Exception:
        bmesh.ops.create_cube(bm, size=1.0)
        for v in bm.verts:
            v.co = Vector((v.co.x * radius * 2, v.co.y * radius * 2, v.co.z * height))
    for v in bm.verts:
        v.co = Vector((v.co.x + cx, v.co.y + cy, v.co.z + cz))
    return _finish(bm)


def half_tube_bm(radius, half_len, center, segs=16):
    """对半劈开的管子——绿罩台灯的灯罩就是这个形状。

    弧拱过头顶（X-Z 平面），管长沿 Y，**开口朝下**；两端各封一个半圆面。
    """
    cx, cy, cz = center
    bm = bmesh.new()
    rings = []
    for i in range(segs + 1):
        a = math.pi * i / segs
        x = math.cos(a) * radius + cx
        z = math.sin(a) * radius + cz
        v0 = bm.verts.new((x, cy - half_len, z))
        v1 = bm.verts.new((x, cy + half_len, z))
        rings.append((v0, v1))
    for i in range(segs):
        p, q = rings[i], rings[i + 1]
        bm.faces.new((p[0], p[1], q[1], q[0]))
    for y, idx in ((cy - half_len, 0), (cy + half_len, 1)):
        c = bm.verts.new((cx, y, cz))
        for i in range(segs):
            bm.faces.new((c, rings[i][idx], rings[i + 1][idx]))
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces[:]))
    return _finish(bm)


# ---------- 试件（增量①② 的回归） ----------
def build_test_cube():
    """0.30 宽 × 0.20 深 × 0.15 高，底面贴地。三个数故意不一样，转错轴当场看得出。"""
    return {"cube": ("wood", box_bm((0.30, 0.20, 0.15), (0, 0, 0.075)))}


def build_test_desk():
    """桌面 + 4 条腿，验「多部件 + 材质槽」那条链路（增量②）。"""
    parts = {}
    parts["top"] = ("wood", box_bm((1.20, 0.70, 0.04), (0, 0, 0.73)))
    i = 0
    for sx in (-1, 1):
        for sy in (-1, 1):
            i += 1
            parts["leg-%d" % i] = (
                "metal",
                box_bm((0.07, 0.07, 0.71), (sx * 0.50, sy * 0.25, 0.355)),
            )
    return parts


# ---------- 阅览室道具 ----------
def build_reading_desk():
    """阅览桌：桌面 + 一圈横撑 + 4 条腿。

    横撑就是桌面下沿那圈木框。没有它，桌子看着像幼儿园的拼装桌。
    """
    parts = build_test_desk()
    z_apron = 0.665
    parts["apron-f"] = ("wood", box_bm((1.00, 0.028, 0.09), (0, 0.25, z_apron)))
    parts["apron-b"] = ("wood", box_bm((1.00, 0.028, 0.09), (0, -0.25, z_apron)))
    parts["apron-l"] = ("wood", box_bm((0.028, 0.44, 0.09), (-0.50, 0, z_apron)))
    parts["apron-r"] = ("wood", box_bm((0.028, 0.44, 0.09), (0.50, 0, z_apron)))
    return parts


def build_bankers_lamp():
    """绿罩台灯：铜座 + 铜杆 + 绿玻璃罩 + 顶珠。

    罩是「对半劈开的管子」，弧拱过头顶、开口朝下——这是它跟普通台灯
    最大的区别。罩子要自发光（网页那边给 emissive），桌面才会亮起一片光池。
    """
    parts = {}
    parts["lamp-base"] = ("metal", cyl_bm(0.085, 0.025, (0, 0, 0.0125), segs=14))
    parts["lamp-stem"] = ("metal", cyl_bm(0.013, 0.33, (0, 0, 0.19), segs=10))
    # 罩：半圆柱，平面朝下（z=0.355），拱顶到 z=0.485
    parts["lamp-shade"] = ("glass", half_tube_bm(0.13, 0.11, (0, 0, 0.355), segs=16))
    parts["lamp-finial"] = ("metal", cyl_bm(0.011, 0.028, (0, 0, 0.50), segs=8))
    return parts


def build_armchair():
    """扶手椅：软包座 / 靠 / 扶手 + 木腿。软包倒了小圆角。

    椅背在 -Y（Blender 的「后」）——摆进场景时背对或侧对镜头，
    正对镜头的椅子会跟书抢戏。
    """
    parts = {}
    parts["chair-seat"] = ("fabric", box_bm((0.55, 0.50, 0.12), (0, 0, 0.36), bevel=0.035))
    parts["chair-back"] = ("fabric", box_bm((0.55, 0.09, 0.55), (0, -0.205, 0.695), bevel=0.03))
    parts["chair-arm-l"] = ("fabric", box_bm((0.08, 0.48, 0.16), (-0.255, 0, 0.50), bevel=0.025))
    parts["chair-arm-r"] = ("fabric", box_bm((0.08, 0.48, 0.16), (0.255, 0, 0.50), bevel=0.025))
    i = 0
    for sx in (-1, 1):
        for sy in (-1, 1):
            i += 1
            parts["chair-leg-%d" % i] = (
                "wood",
                box_bm((0.05, 0.05, 0.30), (sx * 0.22, sy * 0.20, 0.15)),
            )
    return parts


def build_window_trim():
    """窗套线脚 + 窗台——「阅览室」的标志。

    原点在窗台下沿中点。窗洞 1.05 宽 × 2.50 高（跟背景那块亮玻璃对齐）。
    窗台往 **-Y** 探出（Blender 的 -Y 就是「伸进房间」那侧）。
    """
    parts = {}
    parts["sill"] = ("wood", box_bm((1.40, 0.22, 0.08), (0, -0.10, 0.04)))
    parts["trim-bot"] = ("wood", box_bm((1.25, 0.05, 0.10), (0, 0, 0.11)))
    parts["trim-top"] = ("wood", box_bm((1.25, 0.05, 0.10), (0, 0, 2.71)))
    parts["trim-l"] = ("wood", box_bm((0.10, 0.05, 2.70), (-0.575, 0, 1.41)))
    parts["trim-r"] = ("wood", box_bm((0.10, 0.05, 2.70), (0.575, 0, 1.41)))
    return parts


def build_carpet():
    """地毯：近平面，只给 2 厘米厚度。压暗、低对比——不跟书抢戏。"""
    return {"carpet": ("carpet", box_bm((1.9, 1.3, 0.02), (0, 0, 0.01)))}


def build_baseboard():
    """踢脚线：墙脚那一圈木条，说「这是房间」。

    只做后墙 + 两侧各回一段（镜头外的部分不做，省面数）。
    后墙在 Blender 的 **+Y**（转到网页就是 -Z，离镜头最远）。
    """
    parts = {}
    parts["skirt-back"] = ("wood", box_bm((5.0, 0.035, 0.12), (0, 1.6, 0.06)))
    parts["skirt-left"] = ("wood", box_bm((0.035, 1.4, 0.12), (-2.5, 0.9, 0.06)))
    parts["skirt-right"] = ("wood", box_bm((0.035, 1.4, 0.12), (2.5, 0.9, 0.06)))
    return parts


def build_all_props():
    """整间阅览室的道具（不含试件）。"""
    out = {}
    out.update(build_reading_desk())
    out.update(build_bankers_lamp())
    out.update(build_armchair())
    out.update(build_window_trim())
    out.update(build_carpet())
    out.update(build_baseboard())
    return out
