import unittest

from core_engine.models import ClipErrorCode, ClipSegment, KavroClipError
from core_engine.planner import (
    PRESET_DURATIONS_SEC,
    calculate_max_consecutive_clips,
    parse_safe_timestamp,
    plan_consecutive_clips,
    plan_custom_range_clips,
    plan_manual_timestamp_clips,
    validate_clip_count,
    validate_clip_duration,
    validate_segment_boundaries,
    validate_video_duration,
)


class TestStage2Planner(unittest.TestCase):

    def test_presets_and_exact_boundaries(self):
        for preset in PRESET_DURATIONS_SEC:
            clips = plan_consecutive_clips(300, preset, 2)
            self.assertEqual(len(clips), 2)
            self.assertEqual(clips[0].duration_sec, preset)

        clips = plan_consecutive_clips(90, 30, 3)
        self.assertEqual(clips[-1].end_sec, 90)

    def test_consecutive_clips_with_gap(self):
        clips = plan_consecutive_clips(100, 20, 3, "00:10", 5)
        self.assertEqual(
            [(c.start_sec, c.end_sec) for c in clips],
            [(10, 30), (35, 55), (60, 80)],
        )
        self.assertEqual(
            calculate_max_consecutive_clips(100, 20, 10, 5), 3
        )

    def test_overflow_and_negative_gap(self):
        with self.assertRaises(KavroClipError):
            plan_consecutive_clips(90, 30, 3, 0.5)

        with self.assertRaises(KavroClipError):
            plan_consecutive_clips(120, 15, 2, gap_sec=-1)

    def test_manual_timestamps(self):
        clips = plan_manual_timestamp_clips(
            200, 15, ["00:05", "00:30.500", "00:02:10"]
        )
        self.assertEqual(len(clips), 3)
        self.assertEqual(clips[1].start_sec, 30.5)
        self.assertEqual(clips[2].start_sec, 130)

    def test_overlap_protection(self):
        with self.assertRaises(KavroClipError):
            plan_manual_timestamp_clips(
                120, 20, ["00:10", "00:25"]
            )

        clips = plan_manual_timestamp_clips(
            120, 20, ["00:10", "00:25"], allow_overlap=True
        )
        self.assertEqual(len(clips), 2)

    def test_custom_ranges(self):
        clips = plan_custom_range_clips(
            120, [("00:05", "00:20"), ("00:30", "01:00")]
        )
        self.assertEqual([c.duration_sec for c in clips], [15, 30])

        with self.assertRaises(KavroClipError):
            plan_custom_range_clips(120, [("00:40", "00:20")])

        with self.assertRaises(KavroClipError):
            plan_custom_range_clips(120, [("00:10", "00:10.400")])

    def test_invalid_durations_and_counts(self):
        for value in (None, True, 0, -1, 0.5, float("nan"), float("inf"), "30"):
            with self.assertRaises(KavroClipError):
                validate_video_duration(value)
            with self.assertRaises(KavroClipError):
                validate_clip_duration(value)

        for count in (None, True, 0, -3, 101, 2.5, "3"):
            with self.assertRaises(KavroClipError):
                validate_clip_count(count)

    def test_invalid_timestamps(self):
        for value in (
            None, True, -1, float("nan"), float("inf"), "", "nan",
            "01:75", "bad:ts", "-00:10", "00:-10",
            "01:60", "01:02:60", "1.5:10", "01:02:03:04",
        ):
            with self.subTest(value=value):
                with self.assertRaises(KavroClipError):
                    parse_safe_timestamp(value)

    def test_segment_validation(self):
        valid = ClipSegment(index=1, start_sec=5, end_sec=20)
        result = validate_segment_boundaries([valid], 60)
        self.assertEqual(len(result), 1)

        invalid = ClipSegment(index=1, start_sec=5, end_sec=float("nan"))
        with self.assertRaises(KavroClipError):
            validate_segment_boundaries([invalid], 60)


if __name__ == "__main__":
    unittest.main(verbosity=2)
