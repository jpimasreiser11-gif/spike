"""A straight staircase made of boxes. Change the numbers and render it again."""

import colorsys

import bpy

STEPS = 10  # 2..60 number of steps
RISE = 0.18  # 0.05..0.5 height of each step
RUN = 0.28  # 0.1..1 depth of each step
WIDTH = 1.2  # 0.3..5 width of the staircase
HUE = 0.08  # 0..1 colour, around the colour wheel (0 red, 0.33 green, 0.66 blue)


def staircase_mesh():
    """Each step is a box from the floor up to its top, so the staircase has no gaps underneath."""
    verts, faces = [], []
    for i in range(STEPS):
        x0, x1, z1 = i * RUN, (i + 1) * RUN, (i + 1) * RISE
        base = len(verts)
        for z in (0.0, z1):
            verts += [(x0, -WIDTH / 2, z), (x1, -WIDTH / 2, z), (x1, WIDTH / 2, z), (x0, WIDTH / 2, z)]
        faces += [(base, base + 3, base + 2, base + 1), (base + 4, base + 5, base + 6, base + 7),
                  (base, base + 1, base + 5, base + 4), (base + 1, base + 2, base + 6, base + 5),
                  (base + 2, base + 3, base + 7, base + 6), (base + 3, base, base + 4, base + 7)]
    return verts, faces


for old in list(bpy.data.objects):  # start from an empty scene
    bpy.data.objects.remove(old, do_unlink=True)

verts, faces = staircase_mesh()
mesh = bpy.data.meshes.new("Staircase")
mesh.from_pydata(verts, [], faces)
mesh.update()
stairs = bpy.data.objects.new("Staircase", mesh)
bpy.context.scene.collection.objects.link(stairs)

material = bpy.data.materials.new("StairMaterial")
material.use_nodes = True
red, green, blue = colorsys.hsv_to_rgb(HUE, 0.5, 0.8)
material.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (red, green, blue, 1.0)
mesh.materials.append(material)
