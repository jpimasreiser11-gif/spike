"""SPIKE's part of a Blender run (`blender --background --factory-startup --python render_driver.py -- ...`): run the
model's script, make sure the scene has a camera and a light, and render a small preview to the path SPIKE chose.

After the `--` that ends Blender's own options come five arguments: the script, the preview path, width, height and
samples. SPIKE copies this file next to the script and builds that command line, so nothing the script says can
change where the preview goes: the render settings and the path are set here, after the script has run. Only
Blender's own `bpy` and the standard library are used. Written for Blender 3.x and 4.x; a script that fails stops
Blender with a non-zero exit code (`--python-exit-code 1`), so no preview is written for it."""

import math
import runpy
import sys

import bpy

script, preview, width, height, samples = sys.argv[sys.argv.index("--") + 1:][:5]
runpy.run_path(script, run_name="__main__")

SHAPES = {"MESH", "CURVE", "SURFACE", "FONT", "META"}
scene = bpy.context.scene
shapes = [o for o in scene.objects if o.type in SHAPES and not o.hide_render]
if shapes:  # a sphere around everything the script made
    center = [sum(o.location[i] for o in shapes) / len(shapes) for i in range(3)]
    radius = max(math.dist(center, o.location) + math.sqrt(sum(d * d for d in o.dimensions)) / 2 for o in shapes)
else:
    center, radius = [0.0, 0.0, 0.0], 1.0
radius = max(radius, 0.1)


def look_at(position, target):
    """Euler angles (x, y, z) that point a camera at `target` with the world's Z axis up: a Blender camera looks along
    its own -Z axis, and rotation_euler is applied in X, Y, Z order."""
    dx, dy, dz = (target[i] - position[i] for i in range(3))
    return math.atan2(math.hypot(dx, dy), -dz), 0.0, math.atan2(-dx, dy)


if scene.camera is None:  # the script made none: frame what it made, a little from the side and above
    distance = radius * 3.4 + 0.5
    aim = (0.8, -1.0, 0.6)
    scale = distance / math.sqrt(sum(a * a for a in aim))
    position = [center[i] + aim[i] * scale for i in range(3)]
    data = bpy.data.cameras.new("SpikeCamera")
    data.clip_end = max(100.0, distance * 10)
    camera = bpy.data.objects.new("SpikeCamera", data)
    scene.collection.objects.link(camera)
    camera.location = position
    camera.rotation_euler = look_at(position, center)
    scene.camera = camera
if not any(o.type == "LIGHT" for o in scene.objects):  # and a sun, so the preview is not black
    data = bpy.data.lights.new("SpikeLight", "SUN")
    data.energy = 3.0
    light = bpy.data.objects.new("SpikeLight", data)
    scene.collection.objects.link(light)
    light.rotation_euler = (math.radians(50), 0.0, math.radians(35))

render = scene.render
render.engine = "CYCLES"  # the path tracer that needs neither a GPU nor a window
scene.cycles.device = "CPU"
scene.cycles.samples = int(samples)
render.resolution_x, render.resolution_y, render.resolution_percentage = int(width), int(height), 100
render.image_settings.file_format = "PNG"
render.use_file_extension = False  # the file is exactly the path SPIKE chose
render.filepath = preview
bpy.ops.render.render(write_still=True)
