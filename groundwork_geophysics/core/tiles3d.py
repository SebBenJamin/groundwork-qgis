"""3D Tiles for the 3D view's section pictures (pure NumPy): a binary glTF of textured strips,
a local east/north/up frame on the earth (EPSG:4978) and the tileset placing the glTF there.
QGIS shows a tileset as a tiled scene layer; Cesium and other 3D Tiles viewers read the same
files."""
from __future__ import annotations

import json
import struct

import numpy as np

_ARRAY_BUFFER, _ELEMENT_ARRAY_BUFFER = 34962, 34963
_FLOAT, _UINT = 5126, 5125
_LINEAR, _LINEAR_MIPMAP_LINEAR, _CLAMP = 9729, 9987, 33071


def glb(pieces) -> bytes:
    """A binary glTF 2.0: one mesh with a textured, unlit, alpha-blended primitive per piece
    ``(positions (n, 3), uvs (n, 2), triangles (m, 3), png bytes)`` (positions in glTF's
    y-up axes). Every triangle is also written reversed, so the strip shows from both sides
    in a viewer that ignores ``doubleSided``."""
    parts, views, accessors, prims, materials, textures, images = [], [], [], [], [], [], []
    offset = 0

    def add(data: bytes, target=None) -> int:
        nonlocal offset
        view = {"buffer": 0, "byteOffset": offset, "byteLength": len(data)}
        if target:
            view["target"] = target
        views.append(view)
        pad = (-len(data)) % 4
        parts.append(data + b"\0" * pad)
        offset += len(data) + pad
        return len(views) - 1

    for k, (positions, uvs, triangles, png) in enumerate(pieces):
        pos = np.asarray(positions, np.float32).reshape(-1, 3)
        uv = np.asarray(uvs, np.float32).reshape(-1, 2)
        tri = np.asarray(triangles, np.uint32).reshape(-1, 3)
        idx = np.vstack([tri, tri[:, ::-1]]).ravel()
        a = len(accessors)
        accessors += [
            {"bufferView": add(pos.tobytes(), _ARRAY_BUFFER), "componentType": _FLOAT,
             "count": len(pos), "type": "VEC3",
             "min": pos.min(axis=0).astype(float).tolist(),
             "max": pos.max(axis=0).astype(float).tolist()},
            {"bufferView": add(uv.tobytes(), _ARRAY_BUFFER), "componentType": _FLOAT,
             "count": len(uv), "type": "VEC2"},
            {"bufferView": add(idx.tobytes(), _ELEMENT_ARRAY_BUFFER), "componentType": _UINT,
             "count": len(idx), "type": "SCALAR"}]
        images.append({"bufferView": add(bytes(png)), "mimeType": "image/png"})
        textures.append({"source": k, "sampler": 0})
        materials.append({"pbrMetallicRoughness": {"baseColorTexture": {"index": k},
                                                   "metallicFactor": 0.0,
                                                   "roughnessFactor": 1.0},
                          "doubleSided": True, "alphaMode": "BLEND",
                          "extensions": {"KHR_materials_unlit": {}}})
        prims.append({"attributes": {"POSITION": a, "TEXCOORD_0": a + 1}, "indices": a + 2,
                      "material": k, "mode": 4})
    binary = b"".join(parts)
    doc = {"asset": {"version": "2.0", "generator": "Groundwork QGIS plugin"},
           "extensionsUsed": ["KHR_materials_unlit"],
           "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
           "meshes": [{"primitives": prims}], "materials": materials, "textures": textures,
           "samplers": [{"magFilter": _LINEAR, "minFilter": _LINEAR_MIPMAP_LINEAR,
                         "wrapS": _CLAMP, "wrapT": _CLAMP}],
           "images": images, "accessors": accessors, "bufferViews": views,
           "buffers": [{"byteLength": len(binary)}]}
    text = json.dumps(doc, separators=(",", ":")).encode()
    text += b" " * ((-len(text)) % 4)
    total = 12 + 8 + len(text) + 8 + len(binary)
    return (struct.pack("<III", 0x46546C67, 2, total)
            + struct.pack("<II", len(text), 0x4E4F534A) + text
            + struct.pack("<II", len(binary), 0x004E4942) + binary)


def enu_axes(origin) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """East, north and up unit vectors at the earth-centred point ``origin`` (an orthonormal
    frame; "up" points away from the earth's centre)."""
    x, y, z = (float(v) for v in origin)
    lon = np.arctan2(y, x)
    lat = np.arctan2(z, np.hypot(x, y))
    east = np.array([-np.sin(lon), np.cos(lon), 0.0])
    north = np.array([-np.sin(lat) * np.cos(lon), -np.sin(lat) * np.sin(lon), np.cos(lat)])
    up = np.array([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)])
    return east, north, up


def tileset(content_uri: str, east, north, up, origin, centre, half) -> dict:
    """A 3D Tiles 1.1 tileset of one glTF placed in the frame (east, north, up) at ``origin``
    (earth-centred metres); ``centre`` and ``half`` (east, north, up) bound it in that frame."""
    transform = [*map(float, east), 0.0, *map(float, north), 0.0, *map(float, up), 0.0,
                 *map(float, origin), 1.0]                       # column-major
    c, h = (np.asarray(v, float) for v in (centre, half))
    box = [c[0], c[1], c[2], h[0], 0, 0, 0, h[1], 0, 0, 0, h[2]]
    return {"asset": {"version": "1.1", "generator": "Groundwork QGIS plugin"},
            "geometricError": 100.0,
            "root": {"transform": transform,
                     "boundingVolume": {"box": [float(v) for v in box]},
                     "geometricError": 0.0, "refine": "ADD",
                     "content": {"uri": content_uri}}}
