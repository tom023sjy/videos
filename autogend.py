#!/usr/bin/env python3
"""
扫描当前目录（或指定根目录）下所有 .mp4 文件，
为每个 mp4 在同级创建同名子目录，
并在子目录内生成 HLS（.ts 切片 + .m3u8 索引）。

示例：
  A/A.mp4  -> A/A/A-1.ts, A/A/A-2.ts, ..., A/A/A.m3u8
  B.mp4    -> B/B-1.ts, ..., B/B.m3u8
"""

import os
import subprocess
import sys

# ---------- 可调参数 ----------
HLS_TIME = 6          # 每片秒数
OVERWRITE = False      # 是否覆盖已有输出
ROOT_DIR = "."         # 扫描根目录
# -----------------------------


def find_mp4_files(root: str):
    for dirpath, _, filenames in os.walk(root):
        for f in filenames:
            if f.lower().endswith(".mp4"):
                yield os.path.join(dirpath, f)


def split_one(mp4_path: str):
    mp4_path = os.path.abspath(mp4_path)
    base_dir = os.path.dirname(mp4_path)
    stem = os.path.splitext(os.path.basename(mp4_path))[0]
    out_dir = os.path.join(base_dir, stem)

    if not OVERWRITE and os.path.isdir(out_dir) and any(
        f.endswith(".m3u8") for f in os.listdir(out_dir)
    ):
        print(f"[skip] 已存在 HLS 输出: {out_dir}")
        return

    os.makedirs(out_dir, exist_ok=True)
    m3u8_path = os.path.join(out_dir, f"{stem}.m3u8")
    ts_pattern = os.path.join(out_dir, f"{stem}-%d.ts")

    cmd = [
        "ffmpeg",
        "-y" if OVERWRITE else "-n",
        "-i", mp4_path,
        "-c:v", "copy",
        "-c:a", "copy",
        "-bsf:v", "h264_mp4toannexb",
        "-f", "hls",
        "-hls_time", str(HLS_TIME),
        "-hls_playlist_type", "vod",
        "-hls_segment_filename", ts_pattern,
        m3u8_path,
    ]

    print(f"[run] {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"[error] {mp4_path}\nSTDERR:\n{result.stderr[-2000:]}")
        sys.exit(1)

    print(f"[done] {mp4_path} -> {out_dir}")


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else ROOT_DIR
    files = list(find_mp4_files(root))
    if not files:
        print("没有找到 .mp4 文件")
        return
    for f in files:
        split_one(f)


if __name__ == "__main__":
    main()
