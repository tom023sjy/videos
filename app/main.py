import os
import time
import threading
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Railway HLS OSS")

# ---------- 配置 ----------
# 仓库根目录（Railway 部署时就是 /app）
ROOT = Path(os.getenv("HLS_ROOT", Path(__file__).parent))
# 扫描间隔（秒），配合 Railway Cron 时设为 0 关闭内部线程
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "300"))  # 5 分钟

# 内部缓存：key = 相对路径，value = 绝对路径
_index = {}
_index_lock = threading.Lock()


def scan_hls_files():
    """扫描所有 .m3u8 和 .ts 文件，更新索引。"""
    new_index = {}
    for p in ROOT.rglob("*"):
        if p.suffix.lower() in (".m3u8", ".ts"):
            rel = p.relative_to(ROOT).as_posix()
            new_index[rel] = p
    with _index_lock:
        _index.clear()
        _index.update(new_index)
    print(f"[scan] indexed {len(new_index)} hls files under {ROOT}")


def scan_loop():
    while True:
        try:
            scan_hls_files()
        except Exception as e:
            print(f"[scan error] {e}")
        time.sleep(SCAN_INTERVAL)


@app.on_event("startup")
def startup():
    scan_hls_files()
    if SCAN_INTERVAL > 0:
        t = threading.Thread(target=scan_loop, daemon=True)
        t.start()


# ---------- 静态文件路由 ----------
@app.get("/files")
def list_files():
    """列出所有已索引的 HLS 文件（类 OSS ListObjects）。"""
    with _index_lock:
        items = sorted(_index.keys())
    return JSONResponse({"count": len(items), "files": items})


@app.get("/hls/{file_path:path}")
def serve_hls(file_path: str):
    """按相对路径返回 m3u8 或 ts。"""
    with _index_lock:
        abs_path = _index.get(file_path)
    if not abs_path or not abs_path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    media_type = (
        "application/vnd.apple.mpegurl"
        if abs_path.suffix.lower() == ".m3u8"
        else "video/mp2t"
    )
    return FileResponse(abs_path, media_type=media_type)


# 可选：把 ROOT 下所有静态文件也直接挂出来
# app.mount("/raw", StaticFiles(directory=ROOT), name="raw")
