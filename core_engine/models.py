from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ClipErrorCode(str, Enum):
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    CORRUPTED_MEDIA = "CORRUPTED_MEDIA"
    INVALID_DURATION = "INVALID_DURATION"
    INVALID_CLIP_COUNT = "INVALID_CLIP_COUNT"
    TIMESTAMP_OUT_OF_RANGE = "TIMESTAMP_OUT_OF_RANGE"
    INSUFFICIENT_STORAGE = "INSUFFICIENT_STORAGE"
    FFMPEG_FAILURE = "FFMPEG_FAILURE"
    USER_CANCELLED = "USER_CANCELLED"


class KavroClipError(Exception):
    def __init__(self, code: ClipErrorCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class VideoMetadata:
    filepath: str
    filename: str
    format_ext: str
    duration_sec: float
    width: int
    height: int
    file_size_bytes: int
    has_audio: bool = True

    @property
    def resolution_label(self) -> str:
        return f"{self.width}x{self.height}"

    @property
    def estimated_bitrate_bps(self) -> float:
        if self.duration_sec <= 0:
            return 0.0
        return (self.file_size_bytes * 8.0) / self.duration_sec


@dataclass(frozen=True)
class ClipSegment:
    index: int
    start_sec: float
    end_sec: float
    score: Optional[float] = None

    @property
    def duration_sec(self) -> float:
        return round(self.end_sec - self.start_sec, 3)
