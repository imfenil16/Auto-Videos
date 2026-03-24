"""
Viral Edit Generator — Web UI
Run: python app.py
Then open http://localhost:5000
"""

import os
import uuid
import shutil
from flask import Flask, render_template, request, send_file, redirect, url_for, flash

from generate_video import generate, IMAGE_EXTS

app = Flask(__name__)
app.secret_key = os.urandom(24)

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "outputs")

ALLOWED_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


def _allowed_video(filename):
    return os.path.splitext(filename)[1].lower() in ALLOWED_VIDEO_EXTS


def _allowed_image(filename):
    return os.path.splitext(filename)[1].lower() in IMAGE_EXTS


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate_video():
    # Validate video
    video = request.files.get("video")
    if not video or video.filename == "":
        flash("Please upload a video clip.", "error")
        return redirect(url_for("index"))
    if not _allowed_video(video.filename):
        flash("Invalid video format. Use MP4, MOV, AVI, MKV, or WEBM.", "error")
        return redirect(url_for("index"))

    # Validate images
    images = request.files.getlist("images")
    images = [f for f in images if f.filename != ""]
    if len(images) < 2:
        flash("Please upload at least 2 background images.", "error")
        return redirect(url_for("index"))
    for img in images:
        if not _allowed_image(img.filename):
            flash(f"Invalid image: {img.filename}", "error")
            return redirect(url_for("index"))

    # Freeze time
    freeze_str = request.form.get("freeze", "1.5")
    try:
        freeze_time = float(freeze_str)
        if freeze_time <= 0:
            raise ValueError
    except ValueError:
        freeze_time = 1.5

    # Create job directory
    job_id = uuid.uuid4().hex[:10]
    job_dir = os.path.join(UPLOAD_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    try:
        # Save video
        video_ext = os.path.splitext(video.filename)[1]
        video_path = os.path.join(job_dir, f"clip{video_ext}")
        video.save(video_path)

        # Save images
        image_paths = []
        for i, img in enumerate(images):
            ext = os.path.splitext(img.filename)[1]
            img_path = os.path.join(job_dir, f"bg{i:03d}{ext}")
            img.save(img_path)
            image_paths.append(img_path)

        # Output
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        output_path = os.path.join(OUTPUT_DIR, f"{job_id}.mp4")

        # Generate
        generate(video_path, image_paths, output_path, freeze_time=freeze_time)

        return send_file(output_path, as_attachment=True, download_name="viral_edit.mp4")

    finally:
        # Clean up uploads
        shutil.rmtree(job_dir, ignore_errors=True)


if __name__ == "__main__":
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    port = int(os.environ.get("PORT", 8000))
    print(f"\n  Viral Edit Generator")
    print(f"  http://localhost:{port}\n")
    app.run(host="0.0.0.0", debug=False, port=port)
