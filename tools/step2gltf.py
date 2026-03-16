"""
将 STEP 文件转换为 GLTF/GLB 格式，保留材质颜色数据。
使用 FreeCAD Import 模块读取 STEP 文件中的颜色信息（XDE/XCAF）。

用法: FreeCADCmd.exe step2gltf.py <input.step> <output.gltf|.glb>
"""
import sys
import os
import struct
import json
import base64
import math


# ---------------------------------------------------------------------------
# STEP 读取：带颜色信息
# ---------------------------------------------------------------------------

def load_step_with_colors(input_path):
    """
    用 FreeCAD Import 模块加载 STEP 文件，提取每个面的颜色。
    返回: list of (shape_faces, face_colors, label)
        shape_faces : list[Part.Face]
        face_colors : list[(r,g,b,a)]  与 shape_faces 等长
        label       : str
    """
    import FreeCAD
    import Part
    import MeshPart

    doc = FreeCAD.newDocument("step2gltf")

    color_data_available = False
    try:
        import Import
        Import.insert(input_path, doc.Name)
        color_data_available = True
        print("Loaded STEP with color information via Import module")
    except Exception as e:
        print(f"Import module unavailable ({e}), falling back to Part.read()")
        shape = Part.read(input_path)
        if shape.isNull():
            raise RuntimeError("Part.read() returned a null shape")
        obj = doc.addObject("Part::Feature", "Shape")
        obj.Shape = shape
        doc.recompute()

    results = []
    for obj in doc.Objects:
        if not (hasattr(obj, 'Shape') and not obj.Shape.isNull()):
            continue
        shape = obj.Shape
        faces = shape.Faces
        n = len(faces)
        if n == 0:
            continue

        # 尝试获取逐面颜色 (DiffuseColor 是 App 层属性，非 GUI 层)
        if color_data_available and hasattr(obj, 'DiffuseColor') and len(obj.DiffuseColor) == n:
            raw = obj.DiffuseColor
            face_colors = [_normalize_color(c) for c in raw]
        elif hasattr(obj, 'ShapeColor'):
            c = _normalize_color(obj.ShapeColor)
            face_colors = [c] * n
        else:
            face_colors = [(0.8, 0.8, 0.8, 1.0)] * n

        results.append((faces, face_colors, obj.Label))

    FreeCAD.closeDocument(doc.Name)
    return results


def _normalize_color(c):
    """将 FreeCAD 颜色元组统一为 (r, g, b, a) float[0,1]。"""
    if len(c) == 3:
        return (float(c[0]), float(c[1]), float(c[2]), 1.0)
    return (float(c[0]), float(c[1]), float(c[2]), float(c[3]))


# ---------------------------------------------------------------------------
# 三角化：按颜色分组，提升性能
# ---------------------------------------------------------------------------

def tessellate_by_color(object_list, linear_deflection=0.5, angular_deflection=0.523599):
    """
    将同一颜色的面合并后三角化，返回各颜色对应的顶点/法线/索引列表。
    返回: list of (vertices, normals, indices, color)
        vertices : list[(x,y,z)]
        normals  : list[(nx,ny,nz)]  顶点平均法线（平滑着色）
        indices  : list[(i0,i1,i2)]
        color    : (r,g,b,a)
    """
    import Part
    import MeshPart

    # color_key -> list[Part.Face]
    color_groups = {}
    for (faces, face_colors, label) in object_list:
        for face, color in zip(faces, face_colors):
            key = (round(color[0], 4), round(color[1], 4),
                   round(color[2], 4), round(color[3], 4))
            color_groups.setdefault(key, []).append(face)

    print(f"Found {len(color_groups)} unique color(s)")

    primitives = []
    for color_key, faces in color_groups.items():
        compound = Part.makeCompound(faces)
        mesh = MeshPart.meshFromShape(
            Shape=compound,
            LinearDeflection=linear_deflection,
            AngularDeflection=angular_deflection,
            Relative=False,
        )
        if mesh.CountPoints == 0:
            continue

        verts = [(p.x, p.y, p.z) for p in mesh.Points]
        tris  = [(f.PointIndices[0], f.PointIndices[1], f.PointIndices[2])
                 for f in mesh.Facets]

        normals = _compute_smooth_normals(verts, tris)

        print(f"  Color {color_key}: {len(faces)} faces → "
              f"{len(verts)} verts, {len(tris)} tris")
        primitives.append((verts, normals, tris, color_key))

    return primitives


def _compute_smooth_normals(verts, tris):
    """对每个顶点求其相邻三角形法线的平均值（平滑法线）。"""
    n = len(verts)
    acc = [[0.0, 0.0, 0.0] for _ in range(n)]

    for i0, i1, i2 in tris:
        v0, v1, v2 = verts[i0], verts[i1], verts[i2]
        # 叉积求面法线
        ax, ay, az = v1[0]-v0[0], v1[1]-v0[1], v1[2]-v0[2]
        bx, by, bz = v2[0]-v0[0], v2[1]-v0[1], v2[2]-v0[2]
        nx = ay*bz - az*by
        ny = az*bx - ax*bz
        nz = ax*by - ay*bx
        for idx in (i0, i1, i2):
            acc[idx][0] += nx
            acc[idx][1] += ny
            acc[idx][2] += nz

    normals = []
    for nx, ny, nz in acc:
        length = math.sqrt(nx*nx + ny*ny + nz*nz)
        if length > 1e-10:
            normals.append((nx/length, ny/length, nz/length))
        else:
            normals.append((0.0, 0.0, 1.0))
    return normals


# ---------------------------------------------------------------------------
# GLTF 输出
# ---------------------------------------------------------------------------

def write_gltf(primitives, output_path):
    """
    将三角化后的多色图元写入 .gltf（内嵌 base64 二进制）或 .glb。
    每种颜色对应一个 GLTF 图元和一个 PBR 材质。
    """
    is_glb = output_path.lower().endswith('.glb')

    bin_buf   = bytearray()
    bv_list   = []
    acc_list  = []
    mat_list  = []
    prim_list = []

    def _pad4(buf):
        while len(buf) % 4:
            buf.append(0)

    def _add_bv(data_bytes, target):
        offset = len(bin_buf)
        bin_buf.extend(data_bytes)
        _pad4(bin_buf)
        idx = len(bv_list)
        bv_list.append({
            "buffer": 0,
            "byteOffset": offset,
            "byteLength": len(data_bytes),
            "target": target,
        })
        return idx

    def _add_acc(bv_idx, comp_type, count, acc_type, mn=None, mx=None):
        acc = {"bufferView": bv_idx, "componentType": comp_type,
               "count": count, "type": acc_type}
        if mn is not None:
            acc["min"] = mn
        if mx is not None:
            acc["max"] = mx
        idx = len(acc_list)
        acc_list.append(acc)
        return idx

    for verts, normals, tris, color in primitives:
        n_v = len(verts)
        n_t = len(tris)

        # --- positions ---
        pos_bytes = struct.pack(f'{n_v*3}f',
                                *[c for v in verts for c in v])
        xs = [v[0] for v in verts]
        ys = [v[1] for v in verts]
        zs = [v[2] for v in verts]
        bv_pos = _add_bv(pos_bytes, 34962)  # ARRAY_BUFFER
        acc_pos = _add_acc(bv_pos, 5126, n_v, "VEC3",
                           [min(xs), min(ys), min(zs)],
                           [max(xs), max(ys), max(zs)])

        # --- normals ---
        nrm_bytes = struct.pack(f'{n_v*3}f',
                                *[c for n in normals for c in n])
        bv_nrm = _add_bv(nrm_bytes, 34962)
        acc_nrm = _add_acc(bv_nrm, 5126, n_v, "VEC3")

        # --- indices ---
        if n_v > 65535:
            idx_bytes = struct.pack(f'{n_t*3}I',
                                    *[i for t in tris for i in t])
            comp_idx = 5125  # UNSIGNED_INT
        else:
            idx_bytes = struct.pack(f'{n_t*3}H',
                                    *[i for t in tris for i in t])
            comp_idx = 5123  # UNSIGNED_SHORT
        bv_idx = _add_bv(idx_bytes, 34963)  # ELEMENT_ARRAY_BUFFER
        acc_idx = _add_acc(bv_idx, comp_idx, n_t * 3, "SCALAR",
                           [0], [n_v - 1])

        # --- material ---
        r, g, b, a = color
        mat_idx = len(mat_list)
        mat_list.append({
            "name": f"mat_{mat_idx}",
            "pbrMetallicRoughness": {
                "baseColorFactor": [r, g, b, a],
                "metallicFactor": 0.1,
                "roughnessFactor": 0.7,
            },
            "doubleSided": True,
        })

        prim_list.append({
            "attributes": {"POSITION": acc_pos, "NORMAL": acc_nrm},
            "indices": acc_idx,
            "material": mat_idx,
        })

    gltf = {
        "asset": {"version": "2.0", "generator": "step2gltf (FreeCAD)"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes":  [{"mesh": 0, "name": "step_root"}],
        "meshes": [{"name": "step_mesh", "primitives": prim_list}],
        "materials":   mat_list,
        "accessors":   acc_list,
        "bufferViews": bv_list,
        "buffers": [{"byteLength": len(bin_buf)}],
    }

    if is_glb:
        _write_glb(gltf, bin_buf, output_path)
    else:
        uri = "data:application/octet-stream;base64," + \
              base64.b64encode(bytes(bin_buf)).decode('ascii')
        gltf["buffers"][0]["uri"] = uri
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(gltf, f, indent=2)

    print(f"Exported {'GLB' if is_glb else 'GLTF'}: {output_path}")
    print(f"  {len(prim_list)} primitives, {len(mat_list)} materials")


def _write_glb(gltf_dict, bin_buf, output_path):
    json_bytes = json.dumps(gltf_dict, separators=(',', ':')).encode('utf-8')
    while len(json_bytes) % 4:
        json_bytes += b' '

    bin_bytes = bytes(bin_buf)  # already padded to 4

    total = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)

    with open(output_path, 'wb') as f:
        f.write(struct.pack('<III', 0x46546C67, 2, total))          # header
        f.write(struct.pack('<II', len(json_bytes), 0x4E4F534A))    # JSON chunk
        f.write(json_bytes)
        f.write(struct.pack('<II', len(bin_bytes), 0x004E4942))     # BIN chunk
        f.write(bin_bytes)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def convert(input_path, output_path, linear_deflection=0.5, angular_deflection=0.523599):
    print(f"Input : {input_path}")
    print(f"Output: {output_path}")

    object_list = load_step_with_colors(input_path)
    if not object_list:
        print("ERROR: no shapes found in STEP file")
        sys.exit(1)

    primitives = tessellate_by_color(object_list, linear_deflection, angular_deflection)
    if not primitives:
        print("ERROR: tessellation produced no geometry")
        sys.exit(1)

    write_gltf(primitives, output_path)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: FreeCADCmd.exe step2gltf.py <input.step> <output.gltf|.glb>")
        print("  Optional env vars:")
        print("    STEP2GLTF_LINEAR_DEFL    float  (default 0.5)")
        print("    STEP2GLTF_ANGULAR_DEFL   float  radians (default 0.5236 = 30°)")
        sys.exit(1)

    lin  = float(os.environ.get("STEP2GLTF_LINEAR_DEFL",  "0.5"))
    ang  = float(os.environ.get("STEP2GLTF_ANGULAR_DEFL", "0.523599"))
    convert(sys.argv[1], sys.argv[2], lin, ang)
