import math
from typing import List, Sequence, Tuple, Union

from .models import ClipErrorCode, ClipSegment, KavroClipError

PRESET_DURATIONS_SEC = (15.0, 30.0, 60.0, 90.0)
MIN_CLIP_DURATION_SEC = 1.0
MAX_CLIP_DURATION_SEC = 3600.0
MAX_CLIPS_PER_BATCH = 100
FLOAT_EPSILON = 1e-6

TimestampInput = Union[str, int, float]


def _finite(value, name, code):
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        raise KavroClipError(code, f"{name} must be a finite number.")
    result = float(value)
    if not math.isfinite(result):
        raise KavroClipError(code, f"{name} must be finite.")
    return result


def validate_video_duration(value):
    duration = _finite(value, "video_duration_sec", ClipErrorCode.INVALID_DURATION)
    if duration < MIN_CLIP_DURATION_SEC:
        raise KavroClipError(ClipErrorCode.INVALID_DURATION,
                             "Video duration must be at least 1 second.")
    return round(duration, 3)


def validate_clip_duration(value, video_duration_sec=None):
    duration = _finite(value, "clip_duration_sec", ClipErrorCode.INVALID_DURATION)
    if not MIN_CLIP_DURATION_SEC <= duration <= MAX_CLIP_DURATION_SEC:
        raise KavroClipError(ClipErrorCode.INVALID_DURATION,
                             "Clip duration must be between 1 and 3600 seconds.")
    if video_duration_sec is not None:
        video_duration = validate_video_duration(video_duration_sec)
        if duration > video_duration + FLOAT_EPSILON:
            raise KavroClipError(ClipErrorCode.INVALID_DURATION,
                                 "Clip duration exceeds video duration.")
    return round(duration, 3)


def validate_clip_count(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise KavroClipError(ClipErrorCode.INVALID_CLIP_COUNT,
                             "Clip count must be an integer.")
    if not 1 <= value <= MAX_CLIPS_PER_BATCH:
        raise KavroClipError(ClipErrorCode.INVALID_CLIP_COUNT,
                             "Clip count must be between 1 and 100.")
    return value


def parse_safe_timestamp(value):
    if value is None or isinstance(value, bool):
        raise KavroClipError(ClipErrorCode.TIMESTAMP_OUT_OF_RANGE,
                             "Invalid timestamp.")

    if isinstance(value, (int, float)):
        seconds = _finite(value, "timestamp",
                          ClipErrorCode.TIMESTAMP_OUT_OF_RANGE)
        if seconds < 0:
            raise KavroClipError(ClipErrorCode.TIMESTAMP_OUT_OF_RANGE,
                                 "Timestamp cannot be negative.")
        return round(seconds, 3)

    if not isinstance(value, str) or not value.strip():
        raise KavroClipError(ClipErrorCode.TIMESTAMP_OUT_OF_RANGE,
                             "Timestamp must not be empty.")

    cleaned = value.strip()

    # Reject negative timestamp strings, including "-00:10".
    if cleaned.startswith("-"):
        raise KavroClipError(
            ClipErrorCode.TIMESTAMP_OUT_OF_RANGE,
            "Timestamp cannot be negative.",
        )

    parts = cleaned.split(":")
    if len(parts) > 3:
        raise KavroClipError(ClipErrorCode.TIMESTAMP_OUT_OF_RANGE,
                             "Use SS, MM:SS, or HH:MM:SS.")

    try:
        nums = [float(part.strip()) for part in parts]
    except ValueError as exc:
        raise KavroClipError(ClipErrorCode.TIMESTAMP_OUT_OF_RANGE,
                             "Invalid timestamp format.") from exc

    if any(not math.isfinite(n) or n < 0 for n in nums):
        raise KavroClipError(ClipErrorCode.TIMESTAMP_OUT_OF_RANGE,
                             "Timestamp values must be finite and non-negative.")

    if len(nums) == 1:
        total = nums[0]
    elif len(nums) == 2:
        minutes, seconds = nums
        if not minutes.is_integer() or seconds >= 60:
            raise KavroClipError(ClipErrorCode.TIMESTAMP_OUT_OF_RANGE,
                                 "Invalid MM:SS timestamp.")
        total = minutes * 60 + seconds
    else:
        hours, minutes, seconds = nums
        if (not hours.is_integer() or not minutes.is_integer()
                or minutes >= 60 or seconds >= 60):
            raise KavroClipError(ClipErrorCode.TIMESTAMP_OUT_OF_RANGE,
                                 "Invalid HH:MM:SS timestamp.")
        total = hours * 3600 + minutes * 60 + seconds

    return round(total, 3)


def validate_segment_boundaries(segments, video_duration_sec,
                                allow_overlap=False):
    if not isinstance(allow_overlap, bool):
        raise KavroClipError(ClipErrorCode.INVALID_DURATION,
                             "allow_overlap must be boolean.")

    video_duration = validate_video_duration(video_duration_sec)

    if not isinstance(segments, (list, tuple)) or not segments:
        raise KavroClipError(ClipErrorCode.INVALID_CLIP_COUNT,
                             "Segments must be a non-empty list or tuple.")

    validate_clip_count(len(segments))
    result = []

    for index, segment in enumerate(segments, start=1):
        if not isinstance(segment, ClipSegment):
            raise KavroClipError(ClipErrorCode.TIMESTAMP_OUT_OF_RANGE,
                                 f"Invalid segment #{index}.")

        start = _finite(segment.start_sec, "start_sec",
                        ClipErrorCode.TIMESTAMP_OUT_OF_RANGE)
        end = _finite(segment.end_sec, "end_sec",
                      ClipErrorCode.TIMESTAMP_OUT_OF_RANGE)

        if start < 0 or start >= video_duration:
            raise KavroClipError(ClipErrorCode.TIMESTAMP_OUT_OF_RANGE,
                                 f"Invalid start time in segment #{index}.")

        if end <= start + FLOAT_EPSILON or end > video_duration + FLOAT_EPSILON:
            raise KavroClipError(ClipErrorCode.TIMESTAMP_OUT_OF_RANGE,
                                 f"Invalid end time in segment #{index}.")

        end = round(min(end, video_duration), 3)
        start = round(start, 3)
        duration = end - start

        if duration < MIN_CLIP_DURATION_SEC - FLOAT_EPSILON:
            raise KavroClipError(ClipErrorCode.INVALID_DURATION,
                                 f"Segment #{index} is shorter than 1 second.")

        if duration > MAX_CLIP_DURATION_SEC + FLOAT_EPSILON:
            raise KavroClipError(ClipErrorCode.INVALID_DURATION,
                                 f"Segment #{index} is too long.")

        result.append(ClipSegment(
            index=index,
            start_sec=start,
            end_sec=end,
            score=segment.score
        ))

    if not allow_overlap:
        ordered = sorted(result, key=lambda s: (s.start_sec, s.end_sec))
        for current, following in zip(ordered, ordered[1:]):
            if current.end_sec > following.start_sec + FLOAT_EPSILON:
                raise KavroClipError(
                    ClipErrorCode.TIMESTAMP_OUT_OF_RANGE,
                    "Overlapping clips are not allowed."
                )

    return result


def calculate_max_consecutive_clips(video_duration_sec, clip_duration_sec,
                                    start_offset=0.0, gap_sec=0.0):
    video = validate_video_duration(video_duration_sec)
    duration = validate_clip_duration(clip_duration_sec)
    offset = parse_safe_timestamp(start_offset)
    gap = _finite(gap_sec, "gap_sec", ClipErrorCode.INVALID_DURATION)

    if gap < 0:
        raise KavroClipError(ClipErrorCode.INVALID_DURATION,
                             "Gap cannot be negative.")
    if offset >= video or video - offset + FLOAT_EPSILON < duration:
        return 0

    step = duration + gap
    usable = video - offset
    count = 1 + int(((usable - duration) + FLOAT_EPSILON) // step)
    return min(count, MAX_CLIPS_PER_BATCH)


def plan_consecutive_clips(video_duration_sec, clip_duration_sec, clip_count,
                           start_offset=0.0, gap_sec=0.0):
    video = validate_video_duration(video_duration_sec)
    duration = validate_clip_duration(clip_duration_sec, video)
    count = validate_clip_count(clip_count)
    offset = parse_safe_timestamp(start_offset)
    gap = _finite(gap_sec, "gap_sec", ClipErrorCode.INVALID_DURATION)

    if gap < 0:
        raise KavroClipError(ClipErrorCode.INVALID_DURATION,
                             "Gap cannot be negative.")
    if offset >= video:
        raise KavroClipError(ClipErrorCode.TIMESTAMP_OUT_OF_RANGE,
                             "Start offset must be inside the video.")

    final_end = offset + count * duration + (count - 1) * gap
    if final_end > video + FLOAT_EPSILON:
        maximum = calculate_max_consecutive_clips(video, duration, offset, gap)
        raise KavroClipError(
            ClipErrorCode.TIMESTAMP_OUT_OF_RANGE,
            f"Cannot fit {count} clips; maximum possible is {maximum}."
        )

    segments = []
    for i in range(count):
        start = round(offset + i * (duration + gap), 3)
        end = round(start + duration, 3)
        segments.append(ClipSegment(index=i + 1,
                                    start_sec=start,
                                    end_sec=end))

    return validate_segment_boundaries(segments, video, allow_overlap=False)


def plan_manual_timestamp_clips(video_duration_sec, clip_duration_sec,
                                start_timestamps, allow_overlap=False):
    video = validate_video_duration(video_duration_sec)
    duration = validate_clip_duration(clip_duration_sec, video)

    if (not isinstance(start_timestamps, (list, tuple))
            or not start_timestamps):
        raise KavroClipError(ClipErrorCode.INVALID_CLIP_COUNT,
                             "Provide a non-empty timestamp list.")

    validate_clip_count(len(start_timestamps))
    segments = []

    for index, timestamp in enumerate(start_timestamps, start=1):
        start = parse_safe_timestamp(timestamp)
        end = round(start + duration, 3)
        if end > video + FLOAT_EPSILON:
            raise KavroClipError(ClipErrorCode.TIMESTAMP_OUT_OF_RANGE,
                                 f"Clip #{index} exceeds video duration.")
        segments.append(ClipSegment(index=index,
                                    start_sec=start,
                                    end_sec=end))

    return validate_segment_boundaries(segments, video, allow_overlap)


def plan_custom_range_clips(video_duration_sec, time_ranges,
                            allow_overlap=False):
    video = validate_video_duration(video_duration_sec)

    if not isinstance(time_ranges, (list, tuple)) or not time_ranges:
        raise KavroClipError(ClipErrorCode.INVALID_CLIP_COUNT,
                             "Provide a non-empty list of time ranges.")

    validate_clip_count(len(time_ranges))
    segments = []

    for index, pair in enumerate(time_ranges, start=1):
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise KavroClipError(ClipErrorCode.TIMESTAMP_OUT_OF_RANGE,
                                 f"Range #{index} must contain start and end.")

        start = parse_safe_timestamp(pair[0])
        end = parse_safe_timestamp(pair[1])
        if end <= start:
            raise KavroClipError(ClipErrorCode.TIMESTAMP_OUT_OF_RANGE,
                                 f"Range #{index} has invalid boundaries.")

        segments.append(ClipSegment(index=index,
                                    start_sec=start,
                                    end_sec=end))

    return validate_segment_boundaries(segments, video, allow_overlap)
