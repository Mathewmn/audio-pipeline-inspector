import contextlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
import wave

from audio_inspector import decode_pcm, main, render_html, scan


def write_wav(path, samples, channels=1, width=2, rate=48000):
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(width)
        output.setframerate(rate)
        output.writeframes(b"".join(v.to_bytes(width, "little", signed=True) for v in samples))


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_clean_stereo_metrics_and_source_unchanged(self):
        path = self.root / "violin_take.wav"
        write_wav(path, [16384, -16384, -16384, 16384] * 240, channels=2)
        original = path.read_bytes()
        asset = scan(self.root)["assets"][0]
        self.assertEqual(asset["status"], "ok")
        self.assertEqual(asset["duration_seconds"], 0.01)
        self.assertAlmostEqual(asset["peak_dbfs"], -6.02, places=2)
        self.assertEqual(path.read_bytes(), original)

    def test_silence_and_empty_are_review_flags(self):
        write_wav(self.root / "silence.wav", [0] * 8)
        write_wav(self.root / "empty.wav", [])
        assets = {a["path"]: a for a in scan(self.root)["assets"]}
        self.assertIn("Digital silence", assets["silence.wav"]["issues"])
        self.assertIn("Empty audio asset", assets["empty.wav"]["issues"])
        self.assertIsNone(assets["silence.wav"]["peak_dbfs"])

    def test_rail_hits_and_dc_offset(self):
        write_wav(self.root / "clipped.wav", [32767, -32768, 32767, -32768])
        write_wav(self.root / "offset.wav", [8192] * 20)
        assets = {a["path"]: a for a in scan(self.root)["assets"]}
        self.assertEqual(assets["clipped.wav"]["rail_hit_samples"], 4)
        self.assertEqual(assets["offset.wav"]["dc_offset_by_channel"], [0.25])

    def test_24_bit_sign_extension(self):
        values = [-8388608, -1, 0, 8388607]
        data = b"".join(v.to_bytes(3, "little", signed=True) for v in values)
        self.assertEqual(decode_pcm(data, 3), values)
        write_wav(self.root / "sound.wav", [2000000, -2000000], width=3)
        self.assertEqual(scan(self.root)["assets"][0]["status"], "ok")

    def test_8_bit_unsigned_center(self):
        self.assertEqual(decode_pcm(bytes([0, 128, 255]), 1), [-128, 0, 127])

    def test_truncated_pcm_is_error(self):
        path = self.root / "truncated.wav"
        write_wav(path, [10, -10] * 10)
        path.write_bytes(path.read_bytes()[:-4])
        asset = scan(self.root)["assets"][0]
        self.assertEqual(asset["status"], "error")
        self.assertIn("Truncated PCM", asset["issues"][0])

    def test_bad_file_does_not_abort_scan(self):
        (self.root / "bad.wav").write_bytes(b"not audio")
        write_wav(self.root / "good.wav", [1000, -1000])
        report = scan(self.root)
        self.assertEqual(report["summary"]["error"], 1)
        self.assertEqual(report["summary"]["ok"], 1)

    def test_duplicates_sorted_and_uppercase_extension(self):
        write_wav(self.root / "a.wav", [1000, -1000])
        (self.root / "B.WAV").write_bytes((self.root / "a.wav").read_bytes())
        report = scan(self.root)
        self.assertEqual(report["duplicate_groups"], [["B.WAV", "a.wav"]])
        self.assertEqual(report["summary"]["warning"], 1)

    def test_symlink_outside_root_rejected(self):
        with tempfile.TemporaryDirectory() as other:
            source = Path(other) / "outside.wav"
            write_wav(source, [1000, -1000])
            (self.root / "escape.wav").symlink_to(source)
            asset = scan(self.root)["assets"][0]
            self.assertEqual(asset["status"], "error")
            self.assertNotIn("sha256", asset)

    def test_cli_reports_strict_exit_and_html_escaping(self):
        write_wav(self.root / "bad<script>.wav", [0] * 8)
        json_path = self.root / "reports" / "report.json"
        html_path = self.root / "reports" / "report.html"
        self.assertEqual(main([str(self.root), "--strict", "--json-report", str(json_path),
                               "--html-report", str(html_path)]), 1)
        self.assertEqual(json.loads(json_path.read_text())["summary"]["total"], 1)
        output = html_path.read_text()
        self.assertIn("bad&lt;script&gt;.wav", output)
        self.assertNotIn("bad<script>.wav", output)
        self.assertFalse(list(json_path.parent.glob(".audio-report-*")))

    def test_invalid_root_and_unsupported_sample_width(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main([str(self.root / "missing")]), 2)
        with self.assertRaises(ValueError):
            decode_pcm(b"12345", 5)


if __name__ == "__main__":
    unittest.main()
