"""Protect the real HTTP smoke tool's distinct batch/live sample-rate contracts."""
import array
import importlib.util
import io
import math
from pathlib import Path
import sys
import unittest
import wave
from assess import AssessmentError
from azure_feedback import validate_wav

spec = importlib.util.spec_from_file_location('remote_smoke', Path(__file__).resolve().parents[1] / 'remote-smoke.py')
remote_smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(remote_smoke)


def source_wav(rate=24000, channels=1, seconds=1):
    values = array.array('h', [int(math.sin(index * 2 * math.pi * 400 / rate) * 5000) for index in range(round(rate * seconds) * channels)])
    if sys.byteorder != 'little':
        values.byteswap()
    output = io.BytesIO()
    with wave.open(output, 'wb') as stream:
        stream.setnchannels(channels)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(values.tobytes())
    return output.getvalue()


class SmokeAudioTests(unittest.TestCase):
    def test_tts_copy_becomes_valid_16k_batch_without_changing_live_source(self):
        original = source_wav()
        unchanged = original[:]
        with self.assertRaises(AssessmentError):
            validate_wav(original)
        converted = remote_smoke.assessment_wav(original)
        info = validate_wav(converted)
        self.assertAlmostEqual(info['duration_seconds'], 1.0)
        self.assertFalse(info['no_speech'])
        self.assertEqual(original, unchanged)
        with wave.open(io.BytesIO(original), 'rb') as stream:
            self.assertEqual(stream.getframerate(), 24000)
        with wave.open(io.BytesIO(converted), 'rb') as stream:
            self.assertEqual((stream.getframerate(), stream.getnchannels(), stream.getsampwidth(), stream.getnframes()), (16000, 1, 2, 16000))

    def test_existing_16k_pcm_samples_are_preserved(self):
        original = source_wav(rate=16000)
        self.assertEqual(remote_smoke.assessment_wav(original), original)

    def test_bad_channels_rate_and_duration_fail_before_request(self):
        for audio in (source_wav(channels=2), source_wav(rate=8000), source_wav(seconds=16)):
            with self.assertRaises(RuntimeError):
                remote_smoke.assessment_wav(audio)
