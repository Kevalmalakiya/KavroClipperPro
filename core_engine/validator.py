import json
import os
import shutil
import subprocess
from typing import List, Sequence, Union

from .models import ClipErrorCode, ClipSegment, KavroClipError, VideoMetadata

SUPPORTED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".3gp"}
PRESET_DURATIONS_SEC = (15, 30, 60, 90)
MIN_CLIP_DURATION_SEC = 1.0
MAX_CLIP_DURATION_SEC = 3600.0
MAX_CLIPS_PER_BATCH = 100
SAFETY_FREE_RESERVE_BYTES = 200 * 1024 * 1024


def validate_video_file_extension(filepath: str) -> str:
    """Validate file existence, extension, and non-empty size."""
    if not filepath or not os.path.isfile(filepath):
        raise KavroClipError(
            ClipErrorCode.FILE_NOT_FOUND,
            f"Video file not found: {filepath}",
        )

    _, ext = os.path.splitext(filepath)
    ext_lower = ext.lower()

    if ext_lower not in SUPPORTED_EXTENSIONS:
        raise KavroClipError(
            ClipErrorCode.UNSUPPORTED_FORMAT,
            f"Unsupported video format: {ext_lower or 'unknown'}",
        )

    if os.path.getsize(filepath) <= 0:
        raise KavroClipError(
            ClipErrorCode.CORRUPTED_MEDIA,
            "Selected video file is empty.",
        )

    return ext_lower


def probe_video_metadata(
    filepath: str,
    ffprobe_bin: str = "ffprobe",
) -> VideoMetadata:
    """Read video metadata without loading the whole video into memory."""
    ext_lower = validate_video_file_extension(filepath)
    file_size = os.path.getsize(filepath)

    cmd = [
        ffprobe_bin,
        "-v", "error",
        "-show_entries",
        "format=duration:stream=codec_type,width,height,duration",
        "-of", "json",
        filepath,
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise KavroClipError(
            ClipErrorCode.FFMPEG_FAILURE,
            f"Failed to execute ffprobe: {exc}",
        ) from exc

    if proc.returncode != 0 or not proc.stdout.strip():
        raise KavroClipError(
            ClipErrorCode.CORRUPTED_MEDIA,
            "Unable to read video metadata. The file may be corrupted.",
        )

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise KavroClipError(
            ClipErrorCode.CORRUPTED_MEDIA,
            "Invalid metadata returned by ffprobe.",
        ) from exc

    streams = data.get("streams", [])
    video = next(
        (stream for stream in streams if stream.get("codec_type") == "video"),
        None,
    )

    if video is None:
        raise KavroClipError(
            ClipErrorCode.CORRUPTED_MEDIA,
            "File does not contain a valid video stream.",
        )

    has_audio = any(
        stream.get("codec_type") == "audio" for stream in streams
    )

    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)

    if width <= 0 or height <= 0:
        raise KavroClipError(
            ClipErrorCode.CORRUPTED_MEDIA,
            "Video resolution is invalid.",
        )

    raw_duration = (
        data.get("format", {}).get("duration")
        or video.get("duration")
        or 0
    )

    try:
        duration = float(raw_duration)
    except (TypeError, ValueError) as exc:
        raise KavroClipError(
            ClipErrorCode.CORRUPTED_MEDIA,
            "Video duration is unreadable.",
        ) from exc

    if not (0 < duration < float("inf")):
        raise KavroClipError(
            ClipErrorCode.CORRUPTED_MEDIA,
            "Video duration must be positive and finite.",
        )

    return VideoMetadata(
        filepath=os.path.abspath(filepath),
        filename=os.path.basename(filepath),
        format_ext=ext_lower,
        duration_sec=round(duration, 3),
        width=width,
        height=height,
        file_size_bytes=file_size,
        has_audio=has_audio,
    )


def parse_timestamp_to_seconds(value: Union[str, int, float]) -> float:
    """Convert SS, MM:SS, or HH:MM:SS.ms into seconds."""
    if isinstance(value, bool):
        raise KavroClipError(
            ClipErrorCode.TIMESTAMP_OUT_OF_RANGE,
            "Boolean values are not valid timestamps.",
        )

    if isinstance(value, (int, float)):
        sec = float(value)
        if not (0 <= sec < float("inf")):
            raise KavroClipError(
                ClipErrorCode.TIMESTAMP_OUT_OF_RANGE,
                "Timestamp must be finite and non-negative.",
            )
        return round(sec, 3)

    if not isinstance(value, str) or not value.strip():
        raise KavroClipError(
            ClipErrorCode.TIMESTAMP_OUT_OF_RANGE,
            "Timestamp cannot be empty.",
        )

    cleaned = value.strip()
    if cleaned.startswith("-"):
        raise KavroClipError(
            ClipErrorCode.TIMESTAMP_OUT_OF_RANGE,
            "Timestamp cannot be negative.",
        )

    parts = cleaned.split(":")
    if len(parts) > 3:
        raise KavroClipError(
            ClipErrorCode.TIMESTAMP_OUT_OF_RANGE,
            "Use SS, MM:SS, or HH:MM:SS.ms.",
        )

    try:
        nums = [float(part) for part in parts]
    except ValueError as exc:
        raise KavroClipError(
            ClipErrorCode.TIMESTAMP_OUT_OF_RANGE,
            "Timestamp contains an invalid number.",
        ) from exc

    if any(not (0 <= n < float("inf")) for n in nums):
        raise KavroClipError(
            ClipErrorCode.TIMESTAMP_OUT_OF_RANGE,
            "Timestamp values must be finite and non-negative.",
        )

    if len(nums) == 1:
        total = nums[0]
    elif len(nums) == 2:
        minutes, seconds = nums
        if seconds >= 60:
            raise KavroClipError(
                ClipErrorCode.TIMESTAMP_OUT_OF_RANGE,
                "Seconds must be less than 60 in MM:SS.",
            )
        total = minutes * 60 + seconds
    else:
        hours, minutes, seconds = nums
        if minutes >= 60 or seconds >= 60:
            raise KavroClipError(
                ClipErrorCode.TIMESTAMP_OUT_OF_RANGE,
                "Minutes and seconds must be less than 60.",
            )
        total = hours * 3600 + minutes * 60 + seconds

    return round(total, 3)


def format_seconds_to_timestamp(seconds: float) -> str:
    """Format seconds as HH:MM:SS.mmm."""
    if not isinstance(seconds, (int, float)) or not (0 <= seconds < float("inf")):
        raise ValueError("Seconds must be finite and non-negative.")

    total_ms = int(round(seconds * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    whole_seconds, milliseconds = divmod(rem, 1000)

    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{milliseconds:03d}"


def validate_clip_duration_and_count(
    clip_duration_sec: float,
    clip_count: int,
    video_duration_sec: float,
) -> None:
    """Validate clip duration, count, and source video duration."""
    if isinstance(clip_duration_sec, bool) or not isinstance(
        clip_duration_sec, (int, float)
    ):
        raise KavroClipError(
            ClipErrorCode.INVALID_DURATION,
            "Clip duration must be a number.",
        )

    if not (MIN_CLIP_DURATION_SEC <= clip_duration_sec <= MAX_CLIP_DURATION_SEC):
        raise KavroClipError(
            ClipErrorCode.INVALID_DURATION,
            f"Clip duration must be between {MIN_CLIP_DURATION_SEC:.0f} and "
            f"{MAX_CLIP_DURATION_SEC:.0f} seconds.",
        )

    if isinstance(video_duration_sec, bool) or not isinstance(
        video_duration_sec, (int, float)
    ) or not (0 < video_duration_sec < float("inf")):
        raise KavroClipError(
            ClipErrorCode.INVALID_DURATION,
            "Video duration must be positive and finite.",
        )

    if clip_duration_sec > video_duration_sec:
        raise KavroClipError(
            ClipErrorCode.INVALID_DURATION,
            "Clip duration exceeds the source video duration.",
        )

    if isinstance(clip_count, bool) or not isinstance(clip_count, int):
        raise KavroClipError(
            ClipErrorCode.INVALID_CLIP_COUNT,
            "Clip count must be a whole number.",
        )

    if not 1 <= clip_count <= MAX_CLIPS_PER_BATCH:
        raise KavroClipError(
            ClipErrorCode.INVALID_CLIP_COUNT,
            f"Clip count must be between 1 and {MAX_CLIPS_PER_BATCH}.",
        )


def generate_consecutive_clips(
    video_duration_sec: float,
    clip_duration_sec: float,
    clip_count: int,
    start_offset_sec: Union[str, int, float] = 0.0,
) -> List[ClipSegment]:
    """Generate consecutive, non-overlapping clip segments."""
    validate_clip_duration_and_count(
        clip_duration_sec, clip_count, video_duration_sec
    )
    offset = parse_timestamp_to_seconds(start_offset_sec)

    if offset >= video_duration_sec:
        raise KavroClipError(
            ClipErrorCode.TIMESTAMP_OUT_OF_RANGE,
            "Start timestamp must be inside the source video.",
        )

    total_needed = offset + clip_duration_sec * clip_count
    if total_needed > video_duration_sec + 0.001:
        max_possible = max(
            0, int((video_duration_sec - offset) // clip_duration_sec)
        )
        raise KavroClipError(
            ClipErrorCode.TIMESTAMP_OUT_OF_RANGE,
            f"Requested clips exceed video duration. Maximum possible: {max_possible}.",
        )

    segments = []
    for idx in range(clip_count):
        start = round(offset + idx * clip_duration_sec, 3)
        end = round(start + clip_duration_sec, 3)
        segments.append(
            ClipSegment(index=idx + 1, start_sec=start, end_sec=end)
        )

    return segments


def generate_manual_timestamp_clips(
    video_duration_sec: float,
    clip_duration_sec: float,
    start_timestamps: Sequence[Union[str, int, float]],
) -> List[ClipSegment]:
    """Generate clips from user-supplied start timestamps."""
    if not start_timestamps:
        raise KavroClipError(
            ClipErrorCode.INVALID_CLIP_COUNT,
            "Provide at least one clip timestamp.",
        )

    validate_clip_duration_and_count(
        clip_duration_sec, len(start_timestamps), video_duration_sec
    )

    segments = []
    for idx, raw_timestamp in enumerate(start_timestamps, start=1):
        start = parse_timestamp_to_seconds(raw_timestamp)
        end = round(start + clip_duration_sec, 3)

        if start >= video_duration_sec or end > video_duration_sec + 0.001:
            raise KavroClipError(
                ClipErrorCode.TIMESTAMP_OUT_OF_RANGE,
                f"Clip #{idx} exceeds the source video duration.",
            )

        segments.append(
            ClipSegment(
                index=idx,
                start_sec=start,
                end_sec=min(end, round(video_duration_sec, 3)),
            )
        )

    return segments


def verify_sufficient_storage(
    output_dir: str,
    metadata: VideoMetadata,
    segments: Sequence[ClipSegment],
    free_bytes_override: int = None,
) -> int:
    """
    Estimate output storage requirements.
    Includes a 1.5x size multiplier and a 200 MiB safety reserve.
    Returns required bytes or raises INSUFFICIENT_STORAGE.
    """
    if not segments:
        raise KavroClipError(
            ClipErrorCode.INVALID_CLIP_COUNT,
            "No clips were requested.",
        )

    total_clip_duration = sum(segment.duration_sec for segment in segments)

    if metadata.duration_sec <= 0 or metadata.file_size_bytes < 0:
        raise KavroClipError(
            ClipErrorCode.CORRUPTED_MEDIA,
            "Video metadata is invalid.",
        )

    bytes_per_second = metadata.file_size_bytes / metadata.duration_sec
    estimated_output_bytes = int(
        total_clip_duration * bytes_per_second * 1.5
    )
    required_bytes = estimated_output_bytes + SAFETY_FREE_RESERVE_BYTES

    if free_bytes_override is not None:
        if not isinstance(free_bytes_override, int) or free_bytes_override < 0:
            raise ValueError("free_bytes_override must be a non-negative integer.")
        available_bytes = free_bytes_override
    else:
        check_path = (
            output_dir
            if os.path.isdir(output_dir)
            else os.path.expanduser("~")
        )
        available_bytes = shutil.disk_usage(check_path).free

    if available_bytes < required_bytes:
        required_mb = required_bytes / (1024 * 1024)
        available_mb = available_bytes / (1024 * 1024)

        raise KavroClipError(
            ClipErrorCode.INSUFFICIENT_STORAGE,
            f"Not enough free space: {available_mb:.1f} MiB available; "
            f"approximately {required_mb:.1f} MiB required.",
        )

    return required_bytes
