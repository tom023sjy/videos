# generate_config.py
# 扫描 ts_files/ 目录，自动生成 config.json

import os
import json
import re
from collections import defaultdict

def scan_ts_files(directory="./ts_files"):
    """扫描目录，自动识别视频和版本"""
    videos = defaultdict(lambda: {"segments": [], "version": 0})
    
    # 支持多级目录，例如 ts_files/movie123/001.ts
    pattern = re.compile(r'^(.+?)-(\d+)-v(\d+)\.ts$')
    
    for root, dirs, files in os.walk(directory):
        for filename in files:
            if not filename.endswith('.ts'):
                continue
            
            match = pattern.match(filename)
            if not match:
                print(f"Skip file: {filename}")
                continue
            
            identifier = match.group(1)
            seq = int(match.group(2))
            version = int(match.group(3))
            
            if version > videos[identifier]["version"]:
                videos[identifier]["version"] = version
            
            videos[identifier]["segments"].append({
                "seq": seq,
                "version": version,
                "filename": filename
            })
    
    result = {}
    for identifier, data in videos.items():
        max_version = data["version"]
        segments = [s for s in data["segments"] if s["version"] == max_version]
        segments.sort(key=lambda x: x["seq"])
        
        result[identifier] = {
            "version": max_version,
            "total_segments": len(segments),
            "segments": [s["filename"] for s in segments]
        }
    
    return result

if __name__ == "__main__":
    print("Scanning ts_files ...")
    config = scan_ts_files("./ts_files")
    
    if not config:
        print("No ts file found.")
        print("File name: {%s}-{%lld}-v{%s}.ts")
        print("  Example: movie123-001-v2.ts")
        config = {}
    
    with open("config.json", "w") as f:
        json.dump(config, f, indent=2)
    
    print(f"Configured config.json，contains {len(config)} videos")
    for identifier, data in config.items():
        print(f"   - {identifier}: v{data['version']}, {data['total_segments']} Segmentions found.")
