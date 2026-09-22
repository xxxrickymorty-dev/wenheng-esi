# wh_models.py
#
# 道具的几何都从这里出。两头共用一套，免得「Blender 里看的」和「网页里跑的」不是同一个东西：
#   · 交互式建模：Blender 里的 Python 把它建成看得见的物体
#   · 生产导出：  无头脚本把它压成网页读的顶点数据
#
# 约定见 PLAN-Blender道具.md 第 2.3 节：1 单位 = 1 米、原点在底面中心、
# 切成三角面、导出时 Z 朝上转 Y 朝上。

import bmesh
from mathutils import Vector


# ---------- 贴图坐标（按面的朝向摊平，俗称「盒子展开」） ----------
def assign_box_uvs(bm):
    """给每个面摊一块贴图坐标：朝哪条轴就往那两条轴上投影。

    方块类的东西这么摊不会拉变形；曲面要另说（增量 ④⑤ 再处理）。
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


def box_bm(size, center):
    """一个方块的网格。size = (宽, 深, 高)；center = 中心点坐标。

    返回的网格用完要记得 .free()。
    """
    w, d, h = size
    cx, cy, cz = center
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * w + cx, v.co.y * d + cy, v.co.z * h + cz))
    bmesh.ops.triangulate(bm, faces=list(bm.faces))
    assign_box_uvs(bm)
    bm.normal_update()
    return bm


# ---------- 试件 ----------
def build_test_cube():
    """0.30 宽 × 0.20 深 × 0.15 高，底面贴地。三个数故意不一样，转错轴当场看得出。"""
    return {"cube": ("wood", box_bm((0.30, 0.20, 0.15), (0, 0, 0.075)))}


def build_test_desk():
    """桌面 + 4 条腿，用来验「多部件 + 材质槽」那条链路。

    桌面高 0.75 米（真实书桌高度）；桌面走木头、腿走金属——两种材质在网页里
    必须一眼分得开，分不开就说明材质槽丢了。
    """
    parts = {}
    # 桌面：1.20 宽 × 0.70 深 × 0.04 厚，上表面正好 0.75
    parts["top"] = ("wood", box_bm((1.20, 0.70, 0.04), (0, 0, 0.73)))
    # 4 条腿：0.07 见方、0.71 高（地面顶到桌面下沿），四角内收
    i = 0
    for sx in (-1, 1):
        for sy in (-1, 1):
            i += 1
            parts["leg-%d" % i] = (
                "metal",
                box_bm((0.07, 0.07, 0.71), (sx * 0.50, sy * 0.25, 0.355)),
            )
    return parts
