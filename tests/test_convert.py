"""End-to-end acceptance tests. All media is generated, not downloaded."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / "convert_videos.py"
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE", "ffprobe")


class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="winffmpeg 中文 ' ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "video"
        self.root.mkdir()

    def media(self, path, color="red", rate=25, size="96x64", audio=False):
        path.parent.mkdir(parents=True, exist_ok=True)
        command = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                   "-f", "lavfi", "-i", f"color=c={color}:s={size}:r={rate}:d=0.8"]
        if audio:
            command += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=0.8"]
        command += ["-c:v", "mpeg4", "-pix_fmt", "yuv420p"]
        if audio:
            command += ["-c:a", "pcm_s16le"]
        subprocess.run(command + [str(path)], check=True, capture_output=True)
        return path

    def cli(self, *arguments, expected=0):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--input", str(self.root),
             "--ffmpeg", FFMPEG, "--ffprobe", FFPROBE, *arguments],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def probe(self, path):
        result = subprocess.run(
            [FFPROBE, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            check=True, capture_output=True, text=True, encoding="utf-8",
        )
        return json.loads(result.stdout)

    def test_single_clip_becomes_playable_25p_mp4_with_silent_audio(self):
        source = self.media(self.root / "分组 one" / "clip.avi")
        original = source.read_bytes()
        self.cli()
        output = self.root / "output" / "分组 one.mp4"
        info = self.probe(output)
        video = next(s for s in info["streams"] if s["codec_type"] == "video")
        audio = next(s for s in info["streams"] if s["codec_type"] == "audio")
        self.assertEqual(video["codec_name"], "h264")
        self.assertEqual(video["pix_fmt"], "yuv420p")
        self.assertEqual(video["r_frame_rate"], "25/1")
        self.assertEqual(video["field_order"], "progressive")
        self.assertEqual(audio["codec_name"], "aac")
        self.assertEqual(audio["sample_rate"], "48000")
        self.assertEqual(audio["channels"], 2)
        self.assertAlmostEqual(float(video["duration"]), 0.8, delta=0.08)
        self.assertEqual(source.read_bytes(), original)
        subprocess.run([FFMPEG, "-v", "error", "-xerror", "-i", str(output),
                        "-f", "null", "-"], check=True, capture_output=True)

    def pixel(self, path, at):
        result = subprocess.run(
            [FFMPEG, "-v", "error", "-ss", str(at), "-i", str(path), "-frames:v", "1",
             "-vf", "scale=1:1", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"],
            check=True, capture_output=True,
        )
        return tuple(result.stdout)

    def test_recursive_groups_merge_in_natural_order_and_normalize_mixed_media(self):
        group = self.root / "旅行 ' & one"
        self.media(group / "clip10.mkv", color="blue", size="128x72", rate=30, audio=True)
        self.media(group / "clip2.AVI", color="lime")
        self.media(group / "sub" / "clip1.avi", color="red", size="64x96", rate=24)
        (group / "notes.txt").write_text("not video", encoding="utf-8")
        self.media(self.root / "another" / "only.avi", color="yellow")
        self.media(self.root / "root-level-ignored.avi")
        (self.root / "empty").mkdir()
        (self.root / "output" / "nested").mkdir(parents=True)
        (self.root / "output" / "nested" / "broken.mp4").write_bytes(b"ignore output")
        self.cli()
        output = self.root / "output" / "旅行 ' & one.mp4"
        info = self.probe(output)
        video = next(s for s in info["streams"] if s["codec_type"] == "video")
        self.assertEqual((video["width"], video["height"]), (96, 64))
        self.assertAlmostEqual(float(video["duration"]), 2.4, delta=0.12)
        for at, channel in [(0.3, 1), (1.1, 2), (1.9, 0)]:
            pixel = self.pixel(output, at)
            self.assertGreater(pixel[channel], 100, (at, pixel))
            self.assertEqual(pixel.index(max(pixel)), channel, (at, pixel))
        self.assertEqual({p.name for p in (self.root / "output").glob("*.mp4")},
                         {"旅行 ' & one.mp4", "another.mp4"})


if __name__ == "__main__":
    unittest.main()
