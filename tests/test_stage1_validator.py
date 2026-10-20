import unittest

from core_engine.models import ClipErrorCode, KavroClipError
from core_engine.validator import (
    parse_timestamp_to_seconds,
    format_seconds_to_timestamp,
    generate_consecutive_clips,
    generate_manual_timestamp_clips,
)


class TestStage1Validator(unittest.TestCase):

    def test_timestamp_parsing(self):
        self.assertEqual(parse_timestamp_to_seconds(15), 15.0)
        self.assertEqual(parse_timestamp_to_seconds("01:30"), 90.0)
        self.assertEqual(parse_timestamp_to_seconds("00:02:05.500"), 125.5)

    def test_timestamp_formatting(self):
        self.assertEqual(
            format_seconds_to_timestamp(90.25),
            "00:01:30.250",
        )

    def test_consecutive_clips(self):
        clips = generate_consecutive_clips(180, 30, 4, 10)
        self.assertEqual(len(clips), 4)
        self.assertEqual(clips[0].start_sec, 10.0)
        self.assertEqual(clips[-1].end_sec, 130.0)

    def test_consecutive_clips_out_of_range(self):
        with self.assertRaises(KavroClipError) as ctx:
            generate_consecutive_clips(180, 60, 4)
        self.assertEqual(
            ctx.exception.code,
            ClipErrorCode.TIMESTAMP_OUT_OF_RANGE,
        )

    def test_manual_timestamps(self):
        clips = generate_manual_timestamp_clips(
            120, 15, ["00:05", "00:45", "01:40"]
        )
        self.assertEqual(len(clips), 3)
        self.assertEqual(clips[-1].end_sec, 115.0)

    def test_manual_timestamp_out_of_range(self):
        with self.assertRaises(KavroClipError):
            generate_manual_timestamp_clips(
                120, 15, ["00:10", "01:50"]
            )

    def test_invalid_timestamp(self):
        for value in ("01:75", "bad:ts", "-00:10", ""):
            with self.subTest(value=value):
                with self.assertRaises(KavroClipError):
                    parse_timestamp_to_seconds(value)


if __name__ == "__main__":
    unittest.main(verbosity=2)
