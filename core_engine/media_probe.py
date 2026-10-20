"""Read video metadata using ffprobe."""
import json
import shutil
import subprocess
from pathlib import Path

from core_engine.models import VideoMetadata


def probe_video(filepath: str) -> VideoMetadata:
    path = Path(filepath).expanduser()

    if not path.is_file():
        raise FileNotFoundError(f"Video file not found: {path}")

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe is not installed. Install FFmpeg first.")

    result = subprocess.run(
        [
            ffprobe, "-v", "error",
            "-show_entries",
            "format=duration,size:format_tags=title:"
            "stream=codec_type,width,height",
            "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    if result.returncode != 0:
        raise ValueError(
            "Unable to read video metadata: "
            + (result.stderr.strip() or "Unknown ffprobe error")
        )

    try:
        data = json.loads(result.stdout)
        fmt = data.get("format", {})
        streams = data.get("streams", [])

        video_stream = next(
            (s for s in streams if s.get("codec_type") == "video"),
            None,
        )
        if video_stream is None:
            raise ValueError("No video stream found in this file.")

        duration = float(fmt.get("duration", 0))
        if duration <= 0:
            raise ValueError("Video duration is missing or invalid.")

        return VideoMetadata(
            filepath=str(path.resolve()),
            filename=path.name,
            format_ext=path.suffix.lower().lstrip("."),
            duration_sec=duration,
            width=int(video_stream.get("width", 0)),
            height=int(video_stream.get("height", 0)),
            file_size_bytes=path.stat().st_size,
            has_audio=any(
                s.get("codec_type") == "audio" for s in streams
            ),
        )
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid media metadata: {exc}") from exc
