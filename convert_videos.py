#!/usr/bin/env python3
"""Convert each first-level video folder to one progressive H.264 MP4."""
import argparse
import json
import os
import sys
from fractions import Fraction
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


def filename_key(path):
    """Sort by file name first, then relative path, without numeric collation."""
    return path.name.casefold(), path.as_posix().casefold(), path.as_posix()


def display_size(stream):
    sar = Fraction(stream.get("sample_aspect_ratio", "1:1").replace(":", "/"))
    if sar <= 0:
        sar = Fraction(1)
    width = max(2, round(int(stream["width"]) * sar / 2) * 2)
    height = max(2, int(stream["height"]) // 2 * 2)
    rotation = next((s.get("rotation", 0) for s in stream.get("side_data_list", [])
                     if "rotation" in s), 0)
    return (height, width) if abs(rotation) % 180 == 90 else (width, height)


def normalize(source, target, args, size):
    info = probe(source, args.ffprobe)
    audio = any(stream["codec_type"] == "audio" for stream in info["streams"])
    width, height = size
    deinterlace = ""
    if args.deinterlace != "off":
        mode = "all" if args.deinterlace == "force" else "interlaced"
        deinterlace = f"bwdif=mode=send_field:parity={args.parity}:deint={mode},"
    filters = (deinterlace + f"fps={args.fps},setpts=PTS-STARTPTS,"
               "scale=w='max(2,trunc(iw*sar/2)*2)':h='max(2,trunc(ih/2)*2)',setsar=1,"
               f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
               f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1")
    video_only = target.with_suffix(".video.mkv")
    run([args.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
         "-i", str(source), "-map", "0:v:0", "-an", "-sn", "-dn",
         "-map_metadata", "-1", "-map_chapters", "-1", "-vf", filters,
         "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
         "-fps_mode", "cfr", str(video_only)])
    packets = json.loads(run([args.ffprobe, "-v", "error", "-select_streams", "v:0",
                              "-count_packets", "-show_entries", "stream=nb_read_packets",
                              "-of", "json", str(video_only)]))
    duration = int(packets["streams"][0]["nb_read_packets"]) / float(args.fps)
    command = [args.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
               "-i", str(video_only)]
    if audio:
        command += ["-i", str(source)]
    else:
        command += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    command += ["-map", "0:v:0", "-map", "1:a:0", "-map_metadata", "-1", "-map_chapters", "-1",
                "-c:v", "copy", "-af", "asetpts=PTS-STARTPTS,aresample=48000,apad",
                "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", "-t", f"{duration:.9f}", str(target)]
    run(command)
    video_only.unlink()
    return duration


def convert_group(clips, destination, args):
    if destination.exists() and not args.overwrite:
        raise RuntimeError(f"Output exists: {destination}. Use --overwrite to replace it.")
    info = probe(clips[0], args.ffprobe)
    size = display_size(next(s for s in info["streams"] if s["codec_type"] == "video"))
    with tempfile.TemporaryDirectory(prefix=".winffmpeg-", dir=destination.parent) as directory:
        work = Path(directory)
        entries = []
        for index, clip in enumerate(clips):
            segment = work / f"segment{index}.mkv"
            duration = normalize(clip, segment, args, size)
            entries.append(f"file '{segment.name}'\nduration {duration:.9f}\n")
        manifest = work / "segments.ffconcat"
        manifest.write_text("ffconcat version 1.0\n" + "".join(entries), encoding="utf-8")
        run([args.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
             "-f", "concat", "-safe", "1", "-i", str(manifest),
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-movflags", "+faststart", str(work / "result.mp4")])
        staged = work / "result.mp4"
        if args.overwrite:
            os.replace(staged, destination)
        elif os.name == "nt":
            # Windows rename fails if another process has created the destination.
            os.rename(staged, destination)
        else:
            # POSIX rename would overwrite; an exclusive hard link will not.
            os.link(staged, destination)
            staged.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("video"))
    parser.add_argument("--fps", type=Fraction, default=Fraction(25), help="Output frames per second (default: 25)")
    parser.add_argument("--deinterlace", choices=("force", "auto", "off"), default="force",
                        help="force removes combing even with missing interlace flags (default)")
    parser.add_argument("--parity", choices=("auto", "tff", "bff"), default="auto",
                        help="Input field order: auto, top field first, or bottom field first")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing outputs only after success")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    args = parser.parse_args()
    root = args.input.resolve()
    output = root / "output"
    output.mkdir(exist_ok=True)
    failures = 0
    for group in sorted(root.iterdir(), key=filename_key):
        if not group.is_dir() or group == output:
            continue
        clips = sorted((p for p in group.rglob("*") if p.is_file() and p.suffix.lower() in EXTENSIONS),
                       key=lambda p: filename_key(p.relative_to(group)))
        if not clips:
            continue
        try:
            print(f"[START] {group.name}: {len(clips)} clip(s)", flush=True)
            convert_group(clips, output / (group.name + ".mp4"), args)
            print(f"[OK] {output / (group.name + chr(46) + 'mp4')}", flush=True)
        except (OSError, RuntimeError, ValueError, StopIteration) as error:
            failures += 1
            print(f"[ERROR] {group.name}: {error}", file=sys.stderr, flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
