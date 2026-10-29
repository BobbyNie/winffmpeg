"""End-to-end acceptance tests. All media is generated, not downloaded."""
import json
import os
from pathlib import Path
import shutil
import math
import struct
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

    def test_recursive_groups_merge_in_filename_lexical_order_and_normalize_mixed_media(self):
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
        self.assertEqual((video["width"], video["height"]), (64, 96))
        self.assertAlmostEqual(float(video["duration"]), 2.4, delta=0.12)
        for at, channel in [(0.3, 0), (1.1, 2), (1.9, 1)]:
            pixel = self.pixel(output, at)
            self.assertGreater(pixel[channel], 100, (at, pixel))
            self.assertEqual(pixel.index(max(pixel)), channel, (at, pixel))
        self.assertEqual({p.name for p in (self.root / "output").glob("*.mp4")},
                         {"旅行 ' & one.mp4", "another.mp4"})

    def test_custom_integer_and_fractional_frame_rates(self):
        self.media(self.root / "fps" / "clip.avi")
        for rate, expected in [("50", "50/1"), ("30000/1001", "30000/1001")]:
            with self.subTest(rate=rate):
                output = self.root / "output" / "fps.mp4"
                if output.exists():
                    output.unlink()
                self.cli("--fps", rate)
                video = self.probe(output)["streams"][0]
                self.assertEqual(video["r_frame_rate"], expected)
                self.assertAlmostEqual(float(video["duration"]), 0.8, delta=0.05)

    def comb_score(self, path):
        result = subprocess.run(
            [FFMPEG, "-v", "error", "-i", str(path), "-an", "-pix_fmt", "gray",
             "-f", "rawvideo", "pipe:1"], check=True, capture_output=True,
        )
        data = result.stdout
        frame_size = 96 * 64
        self.assertEqual(len(data) % frame_size, 0)
        differences = []
        for start in range(0, len(data), frame_size):
            frame = data[start:start + frame_size]
            differences.extend(abs(frame[y * 96 + x] - frame[(y + 1) * 96 + x])
                               for y in range(2, 61) for x in range(96))
        return sum(differences) / len(differences)

    def test_deinterlacing_removes_motion_combing_even_with_wrong_progressive_flags(self):
        source = self.root / "motion" / "interlaced.mkv"
        source.parent.mkdir()
        pattern = ("nullsrc=s=96x64:r=50:d=1.2,"
                   "geq=lum='if(between(X,mod(N*4,80),mod(N*4,80)+15),235,16)':cb=128:cr=128,"
                   "tinterlace=mode=interleave_top,setfield=prog")
        subprocess.run([FFMPEG, "-v", "error", "-f", "lavfi", "-i", pattern,
                        "-c:v", "ffv1", str(source)], check=True, capture_output=True)
        baseline = self.comb_score(source)
        self.assertGreater(baseline, 10)
        scores = {}
        for mode in ["off", "auto", "force"]:
            with self.subTest(mode=mode):
                self.cli("--deinterlace", mode, "--parity", "tff")
                output = self.root / "output" / "motion.mp4"
                scores[mode] = self.comb_score(output)
                output.unlink()
        self.assertGreater(scores["off"], baseline * 0.8)
        self.assertGreater(scores["auto"], baseline * 0.8)
        self.assertLess(scores["force"], baseline * 0.25, scores)

    def test_overwrite_is_explicit_and_failed_group_preserves_previous_output(self):
        source = self.media(self.root / "a-broken" / "clip.avi")
        self.cli()
        output = self.root / "output" / "a-broken.mp4"
        original = output.read_bytes()
        self.cli(expected=1)
        self.assertEqual(output.read_bytes(), original)
        self.cli("--overwrite")
        source.write_bytes(b"corrupted video")
        self.media(self.root / "b-healthy" / "clip.avi")
        self.cli("--overwrite", expected=1)
        self.assertEqual(output.read_bytes(), original)
        self.assertTrue((self.root / "output" / "b-healthy.mp4").is_file())
        self.assertFalse(any(p.is_dir() for p in (self.root / "output").iterdir()))

    def test_invalid_arguments_and_missing_dependencies_have_clear_exit_codes(self):
        for rate in ["0", "-25", "1/0", "nan", "abc", "25,fps=1"]:
            with self.subTest(rate=rate):
                result = self.cli(f"--fps={rate}", expected=2)
                self.assertNotIn("Traceback", result.stderr)
        for arguments in [("--input", str(self.root / "missing")),
                          ("--ffmpeg", "missing-ffmpeg-executable"),
                          ("--ffprobe", "missing-ffprobe-executable")]:
            with self.subTest(arguments=arguments):
                result = self.cli(*arguments, expected=2)
                self.assertNotIn("Traceback", result.stderr)
        result = self.cli(expected=1)
        self.assertIn("No video", result.stdout + result.stderr)

    def test_directory_links_cannot_import_external_clips_or_redirect_outputs(self):
        external = Path(self.temp.name) / "external"
        external.mkdir()
        (external / "broken.mp4").write_bytes(b"must not read external media")
        group = self.root / "safe"
        self.media(group / "clip.avi")

        def link_directory(link, target):
            if os.name == "nt":
                command = f'mklink /J "{link}" "{target}"'
                subprocess.run([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", command],
                               check=True, capture_output=True)
            else:
                link.symlink_to(target, target_is_directory=True)

        link_directory(group / "linked", external)
        link_directory(self.root / "linked-group", external)
        self.cli()
        self.assertTrue((self.root / "output" / "safe.mp4").is_file())
        shutil.rmtree(self.root / "output")
        link_directory(self.root / "output", external)
        result = self.cli("--overwrite", expected=2)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual({p.name for p in external.iterdir()}, {"broken.mp4"})

    def test_audio_track_selection_uses_requested_track_and_rejects_missing_track(self):
        source = self.root / "sound" / "tracks.mkv"
        source.parent.mkdir()
        subprocess.run(
            [FFMPEG, "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=96x64:r=25:d=0.8",
             "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
             "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=44100",
             "-map", "0:v:0", "-map", "1:a:0", "-map", "2:a:0", "-t", "0.8",
             "-c:v", "mpeg4", "-c:a", "pcm_s16le", str(source)],
            check=True, capture_output=True,
        )
        levels = []
        for arguments in [(), ("--audio-track", "1")]:
            self.cli(*arguments)
            output = self.root / "output" / "sound.mp4"
            result = subprocess.run(
                [FFMPEG, "-v", "error", "-i", str(output), "-map", "0:a:0",
                 "-f", "s16le", "pipe:1"], check=True, capture_output=True,
            )
            samples = [item[0] for item in struct.iter_unpack("<h", result.stdout)]
            self.assertTrue(samples)
            levels.append(math.sqrt(sum(s * s for s in samples) / len(samples)))
            output.unlink()
        self.assertLess(levels[0], 1)
        self.assertGreater(levels[1], 100)
        self.cli("--audio-track", "5", expected=1)
        self.cli("--audio-track=-1", expected=2)

    def test_windows_launcher_uses_its_own_video_directory_and_preserves_exit_code(self):
        launcher = PROJECT / "convert_videos.cmd"
        self.assertTrue(launcher.is_file(), "Windows launcher must be included")
        if os.name != "nt":
            return  # The command interpreter is exercised by the Windows CI job.
        local_launcher = Path(self.temp.name) / launcher.name
        shutil.copy2(launcher, local_launcher)
        shutil.copy2(SCRIPT, Path(self.temp.name) / SCRIPT.name)
        self.media(self.root / "launcher" / "clip.avi")
        for arguments, expected in [("--fps 50", 0), ("--fps 0", 2)]:
            command = (f'call "{local_launcher}" --ffmpeg "{FFMPEG}" '
                       f'--ffprobe "{FFPROBE}" {arguments}')
            result = subprocess.run(
                [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", command],
                cwd=PROJECT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
            )
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        info = self.probe(self.root / "output" / "launcher.mp4")
        self.assertEqual(info["streams"][0]["r_frame_rate"], "50/1")


if __name__ == "__main__":
    unittest.main()
