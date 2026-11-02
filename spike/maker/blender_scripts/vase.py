"""A vase: a surface of revolution. Change the numbers and render it again."""

import colorsys
import math

import bpy

HEIGHT = 2.0  # 0.2..10 total height
RADIUS = 0.7  # 0.1..5 widest radius of the body
NECK = 0.35  # 0.05..5 radius at the base and at the mouth
SEGMENTS = 48  # 8..128 sides around the vase
RINGS = 24  # 4..96 slices from the base to the mouth
HUE = 0.58  # 0..1 colour, around the colour wheel (0 red, 0.33 green, 0.66 blue)


def profile(t):
    """Radius at height t (0 is the base, 1 the mouth): narrow at both ends, round in between."""
    return NECK + (RADIUS - NECK) * math.sin(math.pi * t) ** 0.8


def vase_mesh():
    verts = [(0.0, 0.0, 0.0)]  # the middle of the base
    for i in range(RINGS + 1):
        z, r = HEIGHT * i / RINGS, profile(i / RINGS)
        for j in range(SEGMENTS):
            angle = 2 * math.pi * j / SEGMENTS
            verts.append((r * math.cos(angle), r * math.sin(angle), z))
    faces = [(0, 1 + (j + 1) % SEGMENTS, 1 + j) for j in range(SEGMENTS)]  # the base, facing down
    for i in range(RINGS):
        for j in range(SEGMENTS):
            a = 1 + i * SEGMENTS + j
            b = 1 + i * SEGMENTS + (j + 1) % SEGMENTS
            faces.append((a, b, b + SEGMENTS, a + SEGMENTS))  # the wall, facing out
    return verts, faces


for old in list(bpy.data.objects):  # start from an empty scene
    bpy.data.objects.remove(old, do_unlink=True)

verts, faces = vase_mesh()
mesh = bpy.data.meshes.new("Vase")
mesh.from_pydata(verts, [], faces)
mesh.update()
mesh.polygons.foreach_set("use_smooth", [True] * len(mesh.polygons))
vase = bpy.data.objects.new("Vase", mesh)
bpy.context.scene.collection.objects.link(vase)
vase.modifiers.new("Wall", "SOLIDIFY").thickness = 0.04  # the vase is open at the top: give its wall a thickness

material = bpy.data.materials.new("VaseMaterial")
material.use_nodes = True
red, green, blue = colorsys.hsv_to_rgb(HUE, 0.55, 0.85)
material.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (red, green, blue, 1.0)
mesh.materials.append(material)
