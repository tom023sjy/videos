#!/usr/bin/env python3
"""
扫描目录下所有 .mp4 / .mkv 文件，为每个文件在同级创建同名子目录，
生成 HLS（.ts 切片 + .m3u8）。

策略：
  1. 用 ffprobe 探测视频/音频编码；
  2. 视频是 H.264 且像素格式兼容（yuv420p/yuvj420p） -> 视频流 copy，否则转码 H.264；
  3. 音频是 AAC/MP3 -> copy，否则（AC3/DTS/Opus/FLAC/TrueHD…）转 AAC；
  4. 字幕、附件、数据流一律丢弃；
  5. 多音轨时只取第一条音轨。

示例：
  A/A.mp4  -> A/A/A-1.ts, ..., A/A/A.m3u8
  B/B.mkv  -> B/B/B-1.ts, ..., B/B/B.m3u8
"""

import os
import sys
import json
import shutil
import subprocess

# ---------- 可调参数 ----------
HLS_TIME = 6
OVERWRITE = False
ROOT_DIR = "."
VIDEO_EXT = {".mp4", ".mkv", ".mov", ".m4v"}   # 想扩展格式就加进来
# 这些容器里的 H.264 是 AVCC，需要 bsf 转 Annex B；MKV 里本身就是 Annex B
AVCC_EXTS = {".mp4", ".mov", ".m4v", ".m4a"}
# -----------------------------

VIDEO_COPY_CODECS = {"h264"}
VIDEO_COPY_PIXFMTS = {"yuv420p", "yuvj420p"}
AUDIO_COPY_CODECS = {"aac", "mp3"}


def find_media_files(root):
    for dirpath, _, filenames in os.walk(root):
        for f in filenames:
            if os.path.splitext(f)[1].lower() in VIDEO_EXT:
                yield os.path.join(dirpath, f)


def probe(path):
    cmd = ["ffprobe", "-v", "error", "-show_streams", "-show_format",
           "-of", "json", path]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def pick_streams(info):
    """返回 (video_stream, audio_stream_or_None)。"""
    v = a = None
    for s in info.get("streams", []):
        t = s.get("codec_type")
        if t == "video" and v is None:
            # 跳过 mkv 里的封面缩略图（attached_pic）
            if s.get("disposition", {}).get("attached_pic"):
                continue
            v = s
        elif t == "audio" and a is None:
            a = s
    return v, a


def build_ffmpeg_cmd(src, out_dir, stem, video_stream, audio_stream):
    v_codec = (video_stream or {}).get("codec_name", "")
    v_pixfmt = (video_stream or {}).get("pix_fmt", "")
    a_codec = (audio_stream or {}).get("codec_name", "")

    copy_v = v_codec in VIDEO_COPY_CODECS and v_pixfmt in VIDEO_COPY_PIXFMTS
    copy_a = (audio_stream is None) or (a_codec in AUDIO_COPY_CODECS)

    ext = os.path.splitext(src)[1].lower()
    m3u8_path = os.path.join(out_dir, f"{stem}.m3u8")
    ts_pattern = os.path.join(out_dir, f"{stem}-%d.ts")

    cmd = ["ffmpeg", "-y" if OVERWRITE else "-n", "-i", src]

    # 显式选流：第一条视频 + 第一条音频（如果存在），丢弃字幕/附件/数据
    cmd += ["-map", "0:v:0"]
    if audio_stream is not None:
        cmd += ["-map", "0:a:0?"]
    cmd += ["-sn", "-dn"]

    # 视频
    if copy_v:
        cmd += ["-c:v", "copy"]
        if ext in AVCC_EXTS:
            cmd += ["-bsf:v", "h264_mp4toannexb"]
    else:
        cmd += [
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-profile:v", "high",
            "-level", "4.0",
        ]

    # 音频
    if audio_stream is None:
        cmd += ["-an"]
    elif copy_a:
        cmd += ["-c:a", "copy"]
        if a_codec == "mp3":
            cmd += ["-bsf:a", "aac_adtstoasc"] if False else []  # mp3 直接 copy 即可
    else:
        cmd += ["-c:a", "aac", "-b:a", "128k", "-ac", "2"]

    # HLS 输出
    cmd += [
        "-f", "hls",
        "-hls_time", str(HLS_TIME),
        "-hls_playlist_type", "vod",
        "-hls_segment_filename", ts_pattern,
        m3u8_path,
    ]

    strategy = f"v={'copy' if copy_v else 'transcode'}({v_codec}/{v_pixfmt}), " \
               f"a={'none' if audio_stream is None else ('copy' if copy_a else 'transcode')}({a_codec})"
    return cmd, strategy


def split_one(src):
    src_abs = os.path.abspath(src)
    base_dir = os.path.dirname(src_abs)
    stem = os.path.splitext(os.path.basename(src_abs))[0]
    out_dir = os.path.join(base_dir, stem)

    if not OVERWRITE and os.path.isdir(out_dir) and any(
        f.endswith(".m3u8") for f in os.listdir(out_dir)
    ):
        print(f"[skip] 已存在 HLS 输出: {out_dir}")
        return

    try:
        info = probe(src_abs)
    except subprocess.CalledProcessError as e:
        print(f"[error] ffprobe 失败: {src_abs}\n{e.stderr}")
        sys.exit(1)

    v, a = pick_streams(info)
    if v is None:
        print(f"[warn] 没有视频流，跳过: {src_abs}")
        return

    os.makedirs(out_dir, exist_ok=True)
    cmd, strategy = build_ffmpeg_cmd(src_abs, out_dir, stem, v, a)

    print(f"[run ] {src_abs}")
    print(f"[str ] {strategy}")
    print(f"[cmd ] {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[error] ffmpeg 失败: {src_abs}\nSTDERR:\n{result.stderr[-3000:]}")
        sys.exit(1)

    print(f"[done] -> {out_dir}")


def main():
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        print("需要先安装 ffmpeg / ffprobe")
        sys.exit(1)

    root = sys.argv[1] if len(sys.argv) > 1 else ROOT_DIR
    files = list(find_media_files(root))
    if not files:
        print("没有找到可处理的视频文件")
        return
    for f in files:
        split_one(f)


if __name__ == "__main__":
    main()
