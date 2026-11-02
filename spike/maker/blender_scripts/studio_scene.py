"""A small studio: a floor, a sphere and a box, one sun and one camera looking at them. Change the numbers and render
it again."""

import colorsys
import math

import bpy

SPHERE_RADIUS = 1.0  # 0.2..3 radius of the sphere
BOX_SIZE = 1.6  # 0.2..4 side of the box
HUE = 0.08  # 0..1 colour of the sphere, around the colour wheel (0 red, 0.33 green, 0.66 blue)
SUN_STRENGTH = 4.0  # 0.5..15 brightness of the sun
CAMERA_DISTANCE = 9.0  # 3..40 how far the camera stands from the middle of the scene


def look_at(position, target):
    """Euler angles (x, y, z) that point a camera at `target` with the world's Z axis up: a Blender camera looks along
    its own -Z axis, and rotation_euler is applied in X, Y, Z order."""
    dx, dy, dz = (target[i] - position[i] for i in range(3))
    return math.atan2(math.hypot(dx, dy), -dz), 0.0, math.atan2(-dx, dy)


def paint(obj, name, hue, saturation=0.6, value=0.8):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    red, green, blue = colorsys.hsv_to_rgb(hue, saturation, value)
    material.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (red, green, blue, 1.0)
    obj.data.materials.append(material)


for old in list(bpy.data.objects):  # start from an empty scene
    bpy.data.objects.remove(old, do_unlink=True)

bpy.ops.mesh.primitive_plane_add(size=24)
floor = bpy.context.active_object
floor.name = "Floor"
paint(floor, "FloorMaterial", 0.6, 0.1, 0.6)

bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=SPHERE_RADIUS,
                                     location=(-1.5, 0.0, SPHERE_RADIUS))
sphere = bpy.context.active_object
sphere.name = "Sphere"
bpy.ops.object.shade_smooth()
paint(sphere, "SphereMaterial", HUE)

bpy.ops.mesh.primitive_cube_add(size=BOX_SIZE, location=(1.5, 0.5, BOX_SIZE / 2),
                                rotation=(0.0, 0.0, math.radians(25)))
box = bpy.context.active_object
box.name = "Box"
paint(box, "BoxMaterial", (HUE + 0.5) % 1.0)

sun_data = bpy.data.lights.new("Sun", "SUN")
sun_data.energy = SUN_STRENGTH
sun = bpy.data.objects.new("Sun", sun_data)
bpy.context.scene.collection.objects.link(sun)
sun.rotation_euler = (math.radians(50), 0.0, math.radians(35))

camera_data = bpy.data.cameras.new("Camera")
camera = bpy.data.objects.new("Camera", camera_data)
bpy.context.scene.collection.objects.link(camera)
target = (0.0, 0.0, 0.8)
camera.location = (CAMERA_DISTANCE * 0.6, -CAMERA_DISTANCE * 0.75, CAMERA_DISTANCE * 0.4)
camera.rotation_euler = look_at(camera.location, target)
bpy.context.scene.camera = camera
