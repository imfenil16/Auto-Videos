"""
Soft Body Ring Drop Animation Generator
========================================
Recreates the @KAWAKEN_3DCG style soft body demo video.
A transparent glossy ring drops over a wooden cone sculpture
at varying softness percentages (0%, 10%, 25%, 50%, 80%, 100%).

Usage:
    blender --background --python generate_video.py

Output:
    - Individual clips in ./renders/soft_XX/
    - Final stitched video: ./renders/final_output.mp4 (requires FFmpeg)
"""

import bpy
import bmesh
import math
import os
import subprocess
import shutil

# ============================================================
# CONFIGURATION
# ============================================================
SOFTNESS_VALUES = [0, 10, 25, 50, 80, 100]
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "renders")
RESOLUTION_X = 1080
RESOLUTION_Y = 1920  # 9:16 vertical
FPS = 30
CLIP_DURATION_SEC = 5  # seconds per softness value
SAMPLES = 64  # render samples (increase for quality, decrease for speed)
USE_EEVEE = True  # True = fast, False = Cycles (slower but more realistic)


# ============================================================
# UTILITY FUNCTIONS
# ============================================================
def clean_scene():
    """Remove all objects, materials, etc."""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)

    for mat in bpy.data.materials:
        bpy.data.materials.remove(mat)
    for mesh in bpy.data.meshes:
        bpy.data.meshes.remove(mesh)
    for cam in bpy.data.cameras:
        bpy.data.cameras.remove(cam)
    for light in bpy.data.lights:
        bpy.data.lights.remove(light)
    for txt in bpy.data.fonts:
        if txt.name != "Bfont":
            bpy.data.fonts.remove(txt)


def set_render_settings(output_path):
    """Configure render settings."""
    scene = bpy.context.scene
    scene.render.resolution_x = RESOLUTION_X
    scene.render.resolution_y = RESOLUTION_Y
    scene.render.resolution_percentage = 100
    scene.render.fps = FPS
    scene.frame_start = 1
    scene.frame_end = CLIP_DURATION_SEC * FPS

    if USE_EEVEE:
        scene.render.engine = 'BLENDER_EEVEE_NEXT' if bpy.app.version >= (4, 0, 0) else 'BLENDER_EEVEE'
        if hasattr(scene.eevee, 'taa_render_samples'):
            scene.eevee.taa_render_samples = SAMPLES
    else:
        scene.render.engine = 'CYCLES'
        scene.cycles.samples = SAMPLES
        scene.cycles.device = 'GPU'

    scene.render.image_settings.file_format = 'PNG'
    scene.render.filepath = output_path + "/"

    # Transparent background off — we want dark gray bg
    scene.render.film_transparent = False


# ============================================================
# MATERIAL CREATION
# ============================================================
def create_wood_material():
    """Create a realistic wood material using procedural textures."""
    mat = bpy.data.materials.new(name="Wood")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # Nodes
    output = nodes.new('ShaderNodeOutputMaterial')
    output.location = (600, 0)

    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.location = (300, 0)
    bsdf.inputs['Roughness'].default_value = 0.4
    bsdf.inputs['Specular IOR Level'].default_value = 0.3 if bpy.app.version >= (4, 0, 0) else 0.3

    # Wood color via noise + color ramp
    noise = nodes.new('ShaderNodeTexNoise')
    noise.location = (-200, 0)
    noise.inputs['Scale'].default_value = 3.0
    noise.inputs['Detail'].default_value = 6.0
    noise.inputs['Distortion'].default_value = 2.0

    mapping = nodes.new('ShaderNodeMapping')
    mapping.location = (-400, 0)
    mapping.inputs['Scale'].default_value = (1.0, 1.0, 8.0)

    tex_coord = nodes.new('ShaderNodeTexCoord')
    tex_coord.location = (-600, 0)

    color_ramp = nodes.new('ShaderNodeValToRGB')
    color_ramp.location = (0, 0)
    # Light wood colors
    color_ramp.color_ramp.elements[0].position = 0.3
    color_ramp.color_ramp.elements[0].color = (0.65, 0.45, 0.25, 1.0)
    color_ramp.color_ramp.elements[1].position = 0.7
    color_ramp.color_ramp.elements[1].color = (0.85, 0.65, 0.40, 1.0)

    # Links
    links.new(tex_coord.outputs['Object'], mapping.inputs['Vector'])
    links.new(mapping.outputs['Vector'], noise.inputs['Vector'])
    links.new(noise.outputs['Fac'], color_ramp.inputs['Fac'])
    links.new(color_ramp.outputs['Color'], bsdf.inputs['Base Color'])
    links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])

    return mat


def create_dark_wood_material():
    """Darker wood for the base inset."""
    mat = bpy.data.materials.new(name="DarkWood")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    output = nodes.new('ShaderNodeOutputMaterial')
    output.location = (400, 0)

    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.location = (200, 0)
    bsdf.inputs['Base Color'].default_value = (0.35, 0.22, 0.12, 1.0)
    bsdf.inputs['Roughness'].default_value = 0.5

    links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
    return mat


def create_glass_material():
    """Create a glossy transparent glass material for the ring."""
    mat = bpy.data.materials.new(name="Glass")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    output = nodes.new('ShaderNodeOutputMaterial')
    output.location = (400, 0)

    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.location = (200, 0)
    bsdf.inputs['Base Color'].default_value = (0.95, 0.95, 0.98, 1.0)
    bsdf.inputs['Roughness'].default_value = 0.05
    bsdf.inputs['IOR'].default_value = 1.45

    # Transmission for glass look
    if bpy.app.version >= (4, 0, 0):
        bsdf.inputs['Transmission Weight'].default_value = 0.9
    else:
        bsdf.inputs['Transmission'].default_value = 0.9

    bsdf.inputs['Alpha'].default_value = 0.85

    links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])

    mat.blend_method = 'BLEND' if hasattr(mat, 'blend_method') else 'OPAQUE'
    return mat


# ============================================================
# OBJECT CREATION
# ============================================================
def create_cone(name, radius_bottom, radius_top, height, location, material):
    """Create a cone/truncated cone."""
    bpy.ops.mesh.primitive_cone_add(
        vertices=64,
        radius1=radius_bottom,
        radius2=radius_top,
        depth=height,
        location=location
    )
    obj = bpy.context.active_object
    obj.name = name
    bpy.ops.object.shade_smooth()
    obj.data.materials.append(material)
    return obj


def create_sculpture(wood_mat, dark_wood_mat):
    """Create the 3-tier wooden cone sculpture on a base."""
    objects = []

    # Base block (cube)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0.15))
    base = bpy.context.active_object
    base.name = "Base"
    base.scale = (1.2, 1.2, 0.3)
    bpy.ops.object.shade_smooth()
    base.data.materials.append(wood_mat)
    objects.append(base)

    # Circular dark inset on top of base
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=64, radius=0.85, depth=0.05,
        location=(0, 0, 0.32)
    )
    inset = bpy.context.active_object
    inset.name = "BaseInset"
    bpy.ops.object.shade_smooth()
    inset.data.materials.append(dark_wood_mat)
    objects.append(inset)

    # Bottom cone (largest)
    bottom_cone = create_cone(
        "BottomCone", 0.75, 0.50, 0.9,
        (0, 0, 0.80), wood_mat
    )
    objects.append(bottom_cone)

    # Middle cone
    mid_cone = create_cone(
        "MiddleCone", 0.50, 0.30, 0.7,
        (0, 0, 1.60), wood_mat
    )
    objects.append(mid_cone)

    # Top cone (smallest)
    top_cone = create_cone(
        "TopCone", 0.30, 0.05, 0.55,
        (0, 0, 2.25), wood_mat
    )
    objects.append(top_cone)

    return objects


def create_ring(glass_mat, start_height=3.5):
    """Create the torus ring."""
    bpy.ops.mesh.primitive_torus_add(
        major_radius=0.65,
        minor_radius=0.08,
        major_segments=64,
        minor_segments=24,
        location=(0, 0, start_height)
    )
    ring = bpy.context.active_object
    ring.name = "Ring"
    bpy.ops.object.shade_smooth()
    ring.data.materials.append(glass_mat)
    return ring


# ============================================================
# PHYSICS SETUP
# ============================================================
def setup_collision(obj):
    """Add collision physics to an object."""
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_add(type='COLLISION')


def setup_soft_body(ring, softness_pct):
    """Add soft body physics to the ring with given softness."""
    bpy.context.view_layer.objects.active = ring

    # Remove existing soft body if any
    for mod in ring.modifiers:
        if mod.type == 'SOFT_BODY':
            ring.modifiers.remove(mod)

    bpy.ops.object.modifier_add(type='SOFT_BODY')
    sb = ring.modifiers['Softbody'].settings

    # Goal strength: higher = more rigid. Invert softness.
    # Soft 0% = rigid (goal=1.0), Soft 100% = very soft (goal=0.0)
    goal_strength = 1.0 - (softness_pct / 100.0)

    sb.use_goal = True
    sb.goal_spring = goal_strength
    sb.goal_friction = 0.5

    # Physics settings
    sb.mass = 1.0
    sb.friction = 0.5

    # Spring settings for softness
    sb.use_edges = True
    sb.pull = 0.5 + (0.4 * (1.0 - softness_pct / 100.0))
    sb.push = 0.5 + (0.4 * (1.0 - softness_pct / 100.0))

    # Gravity
    bpy.context.scene.gravity = (0, 0, -9.81)
    bpy.context.scene.use_gravity = True


def animate_ring_drop(ring, start_frame, end_frame, start_z=3.5, end_z=0.35):
    """Animate the ring dropping from start_z to end_z."""
    ring.location.z = start_z
    ring.keyframe_insert(data_path="location", index=2, frame=start_frame)

    ring.location.z = end_z
    ring.keyframe_insert(data_path="location", index=2, frame=end_frame)

    # Set easing
    if ring.animation_data and ring.animation_data.action:
        for fcurve in ring.animation_data.action.fcurves:
            for kfp in fcurve.keyframe_points:
                kfp.interpolation = 'BEZIER'
                kfp.easing = 'EASE_IN'


# ============================================================
# SCENE SETUP
# ============================================================
def setup_camera():
    """Set up the camera for vertical 9:16 view."""
    bpy.ops.object.camera_add(
        location=(4.5, -4.5, 2.2),
        rotation=(math.radians(72), 0, math.radians(45))
    )
    cam = bpy.context.active_object
    cam.name = "Camera"
    cam.data.lens = 50
    bpy.context.scene.camera = cam

    # Track to center of sculpture
    bpy.ops.object.constraint_add(type='TRACK_TO')
    track = cam.constraints['Track To']
    # Create an empty at the sculpture center for tracking
    bpy.ops.object.empty_add(location=(0, 0, 1.3))
    target = bpy.context.active_object
    target.name = "CameraTarget"
    track.target = target
    track.track_axis = 'TRACK_NEGATIVE_Z'
    track.up_axis = 'UP_Y'

    # Re-select camera
    bpy.context.view_layer.objects.active = cam
    return cam


def setup_lighting():
    """Set up studio lighting."""
    # Key light
    bpy.ops.object.light_add(
        type='AREA', location=(3, -2, 5),
        rotation=(math.radians(45), 0, math.radians(20))
    )
    key = bpy.context.active_object
    key.name = "KeyLight"
    key.data.energy = 300
    key.data.size = 3

    # Fill light
    bpy.ops.object.light_add(
        type='AREA', location=(-3, -3, 3),
        rotation=(math.radians(60), 0, math.radians(-30))
    )
    fill = bpy.context.active_object
    fill.name = "FillLight"
    fill.data.energy = 150
    fill.data.size = 4

    # Rim light
    bpy.ops.object.light_add(
        type='AREA', location=(-1, 4, 4),
        rotation=(math.radians(40), 0, math.radians(180))
    )
    rim = bpy.context.active_object
    rim.name = "RimLight"
    rim.data.energy = 200
    rim.data.size = 2


def setup_background():
    """Set world background to dark gray."""
    world = bpy.data.worlds.get("World")
    if not world:
        world = bpy.data.worlds.new("World")
    bpy.context.scene.world = world

    world.use_nodes = True
    nodes = world.node_tree.nodes
    bg = nodes.get("Background")
    if bg:
        bg.inputs['Color'].default_value = (0.08, 0.08, 0.08, 1.0)
        bg.inputs['Strength'].default_value = 1.0


def create_title_text(text_content, location=(0, 0, 4.2)):
    """Create 3D text for title overlay."""
    bpy.ops.object.text_add(location=location)
    txt = bpy.context.active_object
    txt.name = "TitleText"
    txt.data.body = text_content
    txt.data.align_x = 'CENTER'
    txt.data.align_y = 'CENTER'
    txt.data.size = 0.35
    txt.data.extrude = 0.02

    # White emissive material so text is always visible
    mat = bpy.data.materials.new(name="TextMaterial")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    output = nodes.new('ShaderNodeOutputMaterial')
    output.location = (300, 0)

    emission = nodes.new('ShaderNodeEmission')
    emission.location = (100, 0)
    emission.inputs['Color'].default_value = (1.0, 1.0, 1.0, 1.0)
    emission.inputs['Strength'].default_value = 5.0

    links.new(emission.outputs['Emission'], output.inputs['Surface'])

    txt.data.materials.append(mat)

    # Make text face camera
    bpy.ops.object.constraint_add(type='TRACK_TO')
    track = txt.constraints['Track To']
    cam = bpy.data.objects.get("Camera")
    if cam:
        track.target = cam
        track.track_axis = 'TRACK_Z'
        track.up_axis = 'UP_Y'

    return txt


# ============================================================
# BAKE & RENDER
# ============================================================
def bake_physics():
    """Bake all physics simulations."""
    bpy.ops.ptcache.bake_all(bake=True)


def free_physics():
    """Free all baked physics."""
    bpy.ops.ptcache.free_bake_all()


def render_clip(output_path):
    """Render the current scene animation."""
    os.makedirs(output_path, exist_ok=True)
    bpy.context.scene.render.filepath = output_path + "/frame_"
    bpy.ops.render.render(animation=True)


# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 60)
    print("  Soft Body Ring Drop Video Generator")
    print("=" * 60)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for softness in SOFTNESS_VALUES:
        print(f"\n--- Generating Soft {softness}% ---")

        # Clean everything
        clean_scene()

        # Materials
        wood_mat = create_wood_material()
        dark_wood_mat = create_dark_wood_material()
        glass_mat = create_glass_material()

        # Background
        setup_background()

        # Sculpture
        sculpture_parts = create_sculpture(wood_mat, dark_wood_mat)

        # Add collision to sculpture parts
        for part in sculpture_parts:
            setup_collision(part)

        # Ring
        ring = create_ring(glass_mat, start_height=3.5)

        # Soft body physics
        setup_soft_body(ring, softness)

        # Animate ring drop
        total_frames = CLIP_DURATION_SEC * FPS
        animate_ring_drop(ring, start_frame=1, end_frame=total_frames,
                          start_z=3.5, end_z=0.35)

        # Title text
        title = create_title_text(f"Soft {softness}%")

        # Camera & lights
        setup_camera()
        setup_lighting()

        # Render settings
        clip_dir = os.path.join(OUTPUT_DIR, f"soft_{softness:03d}")
        set_render_settings(clip_dir)

        # Bake physics
        try:
            bake_physics()
        except Exception as e:
            print(f"  Physics bake note: {e}")

        # Render
        print(f"  Rendering to {clip_dir}")
        render_clip(clip_dir)

        # Free physics cache
        try:
            free_physics()
        except Exception:
            pass

        print(f"  Done: Soft {softness}%")

    # Stitch clips together using FFmpeg
    stitch_videos()

    print("\n" + "=" * 60)
    print("  ALL DONE!")
    print(f"  Output: {os.path.join(OUTPUT_DIR, 'final_output.mp4')}")
    print("=" * 60)


def stitch_videos():
    """Use FFmpeg to combine all rendered clips into one video."""
    print("\n--- Stitching clips with FFmpeg ---")

    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        print("  FFmpeg not found! Skipping stitch.")
        print("  Run stitch_videos.ps1 manually after installing FFmpeg.")
        return

    concat_file = os.path.join(OUTPUT_DIR, "concat_list.txt")

    # First, convert each frame sequence to a video clip
    clip_paths = []
    for softness in SOFTNESS_VALUES:
        clip_dir = os.path.join(OUTPUT_DIR, f"soft_{softness:03d}")
        clip_video = os.path.join(OUTPUT_DIR, f"clip_{softness:03d}.mp4")
        clip_paths.append(clip_video)

        cmd = [
            ffmpeg_path, "-y",
            "-framerate", str(FPS),
            "-i", os.path.join(clip_dir, "frame_%04d.png"),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-crf", "18",
            clip_video
        ]
        print(f"  Encoding clip: Soft {softness}%")
        subprocess.run(cmd, capture_output=True)

    # Create concat list
    with open(concat_file, 'w') as f:
        for path in clip_paths:
            f.write(f"file '{path}'\n")

    # Concatenate
    final_output = os.path.join(OUTPUT_DIR, "final_output.mp4")
    cmd = [
        ffmpeg_path, "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_file,
        "-c", "copy",
        final_output
    ]
    print("  Concatenating all clips...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"  Final video: {final_output}")
    else:
        print(f"  FFmpeg concat error: {result.stderr}")


if __name__ == "__main__":
    main()
