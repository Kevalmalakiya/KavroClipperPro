"""Render a video segment using the installed FFmpeg executable."""
import shutil
import subprocess
from pathlib import Path

from core_engine.planner import validate_clip_duration, parse_safe_timestamp


def render_clip(input_path, output_path, start_sec, end_sec):
    source = Path(input_path).expanduser()
    destination = Path(output_path).expanduser()

    if not source.is_file():
        raise FileNotFoundError(f"Input video not found: {source}")

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is not installed.")

    start = parse_safe_timestamp(start_sec)
    end = parse_safe_timestamp(end_sec)

    if end <= start:
        raise ValueError("Clip end must be greater than clip start.")

    duration = round(end - start, 3)
    validate_clip_duration(duration)

    destination.parent.mkdir(parents=True, exist_ok=True)

    command = [
        ffmpeg, "-hide_banner", "-y",
        "-ss", str(start),
        "-i", str(source),
        "-t", str(duration),
        "-map", "0:v:0",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-c:a", "aac",
        "-movflags", "+faststart",
        str(destination),
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
    )

    if result.returncode != 0 or not destination.is_file():
        raise RuntimeError(
            "FFmpeg could not render the clip:\n"
            + (result.stderr[-2500:] if result.stderr else "Unknown error")
        )

    if destination.stat().st_size == 0:
        destination.unlink(missing_ok=True)
        raise RuntimeError("Rendered clip is empty.")

    return destination
