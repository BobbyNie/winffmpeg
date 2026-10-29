#!/usr/bin/env python3
"""Convert each first-level video folder to one progressive H.264 MP4."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile


EXTENSIONS = {".mp4", ".m4v", ".mov", ".mkv", ".avi", ".mts", ".m2ts", ".ts",
              ".mpeg", ".mpg", ".wmv", ".webm", ".flv", ".vob", ".mxf", ".3gp"}


def run(command):
    """Use argument lists, never a shell, for untrusted file names."""
    result = subprocess.run(command, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return result.stdout


def probe(path, executable):
    return json.loads(run([executable, "-v", "error", "-show_streams", "-of", "json", str(path)]))


def normalize(source, target, args):
    info = probe(source, args.ffprobe)
    audio = any(stream["codec_type"] == "audio" for stream in info["streams"])
    command = [args.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(source)]
    if not audio:
        command += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    command += ["-map", "0:v:0", "-map", "0:a:0" if audio else "1:a:0",
                "-vf", "bwdif=mode=send_field:parity=auto:deint=all,fps=25,setpts=PTS-STARTPTS,setsar=1",
                "-af", "asetpts=PTS-STARTPTS,aresample=48000,apad",
                "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
                "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", "-shortest", str(target)]
    run(command)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("video"))
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    args = parser.parse_args()
    root = args.input.resolve()
    output = root / "output"
    output.mkdir(exist_ok=True)
    for group in sorted(root.iterdir()):
        if not group.is_dir() or group == output:
            continue
        clips = sorted(p for p in group.rglob("*") if p.is_file() and p.suffix.lower() in EXTENSIONS)
        if not clips:
            continue
        with tempfile.TemporaryDirectory(prefix="winffmpeg-") as directory:
            segment = Path(directory) / "segment.mkv"
            normalize(clips[0], segment, args)
            run([args.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                 "-i", str(segment), "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                 "-movflags", "+faststart", str(output / (group.name + ".mp4"))])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
