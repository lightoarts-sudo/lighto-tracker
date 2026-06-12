import asyncio
import json
import os
import re
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.background import BackgroundTask


ASSET_DIR = Path(__file__).resolve().parent / "static"
MAX_CLIP_SECONDS = 60 * 60
_download_lock = asyncio.Lock()


def _is_youtube_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower().removeprefix("www.")
    return parsed.scheme in {"http", "https"} and host in {
        "youtube.com",
        "m.youtube.com",
        "youtu.be",
    }


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", value or "youtube-clip")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()[:90]
    return cleaned or "youtube-clip"


def _asset(name: str, media_type: str) -> Response:
    path = ASSET_DIR / name
    if not path.is_file():
        return JSONResponse({"error": "Not found"}, status_code=404)
    return Response(path.read_bytes(), media_type=media_type)


def _cleanup(path: str) -> None:
    shutil.rmtree(path, ignore_errors=True)


def install_youtube_clipper(app: FastAPI) -> None:
    @app.get("/youtube", response_class=HTMLResponse)
    @app.get("/youtube/", response_class=HTMLResponse)
    async def youtube_clipper_page():
        return _asset("index.html", "text/html; charset=utf-8")

    @app.get("/youtube/styles.css")
    async def youtube_clipper_styles():
        return _asset("styles.css", "text/css; charset=utf-8")

    @app.get("/youtube/app.js")
    async def youtube_clipper_script():
        return _asset("app.js", "text/javascript; charset=utf-8")

    @app.post("/youtube/api/download")
    async def youtube_clipper_download(request: Request):
        if _download_lock.locked():
            return JSONResponse(
                {"error": "目前有另一個片段正在處理，請稍後再試。"},
                status_code=429,
            )

        try:
            payload = await request.json()
            url = str(payload.get("url", ""))
            start = float(payload.get("start"))
            end = float(payload.get("end"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return JSONResponse({"error": "無法讀取下載設定。"}, status_code=400)

        if not _is_youtube_url(url):
            return JSONResponse({"error": "請輸入有效的 YouTube 連結。"}, status_code=400)
        if start < 0 or end <= start:
            return JSONResponse({"error": "結束時間必須晚於開始時間。"}, status_code=400)
        if end - start > MAX_CLIP_SECONDS:
            return JSONResponse({"error": "單次下載片段最多 60 分鐘。"}, status_code=400)

        job_dir = tempfile.mkdtemp(prefix=f"yt-clip-{uuid.uuid4().hex[:8]}-")
        output_template = os.path.join(job_dir, "clip.%(ext)s")

        try:
            import imageio_ffmpeg

            ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
            async with _download_lock:
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "yt_dlp",
                    "--no-playlist",
                    "--no-warnings",
                    "--download-sections",
                    f"*{start:.3f}-{end:.3f}",
                    "--force-keyframes-at-cuts",
                    "--ffmpeg-location",
                    ffmpeg_path,
                    "--merge-output-format",
                    "mp4",
                    "--format",
                    "bv*+ba/b",
                    "--max-filesize",
                    "500M",
                    "--output",
                    output_template,
                    "--print",
                    "after_move:filepath",
                    url,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await process.communicate()
        except Exception:
            _cleanup(job_dir)
            return JSONResponse({"error": "伺服器無法啟動影片處理工具。"}, status_code=500)

        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace")
            _cleanup(job_dir)
            message = (
                "影片超過伺服器允許的檔案大小。"
                if "max-filesize" in detail.lower()
                else "YouTube 無法提供此影片，可能是私人、受限或連結已失效。"
            )
            return JSONResponse({"error": message}, status_code=422)

        reported = stdout.decode("utf-8", errors="replace").strip().splitlines()
        candidate = Path(reported[-1]) if reported else None
        if not candidate or not candidate.is_file() or job_dir not in str(candidate.resolve()):
            files = [path for path in Path(job_dir).iterdir() if path.is_file()]
            candidate = files[0] if files else None
        if not candidate or not candidate.is_file():
            _cleanup(job_dir)
            return JSONResponse({"error": "影片處理完成，但找不到輸出檔案。"}, status_code=500)

        title = _safe_filename(str(payload.get("title", "youtube-clip")))
        filename = f"{title}_{int(start)}-{int(end)}.mp4"
        return FileResponse(
            candidate,
            media_type="video/mp4",
            filename=filename,
            background=BackgroundTask(_cleanup, job_dir),
        )
