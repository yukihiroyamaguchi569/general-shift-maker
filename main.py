"""
当直表 一括作成システム - FastAPI サーバー（統合版）
"""

import io
import os
import time
import zipfile
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import jpholiday
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from configs import SHIFT_CONFIGS
from excel_handler import read_excel, write_excel
from solver import generate_shift

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PASSWORD = os.environ.get("APP_PASSWORD", "")
SECRET_KEY = os.environ.get("SECRET_KEY", "")

if not PASSWORD:
    raise RuntimeError("環境変数 APP_PASSWORD が設定されていません。起動を中止します。")
if not SECRET_KEY:
    raise RuntimeError("環境変数 SECRET_KEY が設定されていません。起動を中止します。")

app = FastAPI(title="当直表 一括作成システム")
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    https_only=os.environ.get("HTTPS_ONLY", "true").lower() != "false",
    max_age=3600,
)


# =========================================================
# セキュリティヘッダーミドルウェア
# =========================================================

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


app.add_middleware(SecurityHeadersMiddleware)


# =========================================================
# ブルートフォース対策
# =========================================================

_login_attempts: dict = defaultdict(list)
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW_SECONDS = 300


def _check_login_rate_limit(ip: str) -> bool:
    """True を返す場合はブロック"""
    now = time.time()
    attempts = _login_attempts[ip]
    _login_attempts[ip] = [t for t in attempts if now - t < _LOGIN_WINDOW_SECONDS]
    if len(_login_attempts[ip]) >= _LOGIN_MAX_ATTEMPTS:
        return True
    _login_attempts[ip].append(now)
    return False


# 静的ファイルの配信
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


def require_auth(request: Request):
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=401, detail="Unauthorized")


def get_config(shift_type: str):
    config = SHIFT_CONFIGS.get(shift_type)
    if not config:
        raise HTTPException(
            status_code=404,
            detail=f"不明なシフトタイプです: {shift_type}。icu / junya / resident のいずれかを指定してください。",
        )
    return config


# =========================================================
# リクエストモデル
# =========================================================

class GenerateRequest(BaseModel):
    staff_ids: List[str]
    day_limits: List[int]
    night_limits: List[int]
    dates: List[Any]
    schedule: List[List[str]]
    holiday_flags: List[bool]
    closed_flags: List[bool]
    max_total_duties: int = 6
    min_gap: int = 2


class DownloadRequest(BaseModel):
    staff_ids: List[str]
    day_limits: List[int]
    night_limits: List[int]
    dates: List[Any]
    schedule: List[List[str]]
    closed_days: List[int]


class DownloadAllRequest(BaseModel):
    types: Dict[str, DownloadRequest]


# =========================================================
# 認証ルート
# =========================================================

@app.get("/")
async def root(request: Request):
    if not request.session.get("authenticated"):
        return RedirectResponse(url="/login")
    return FileResponse(os.path.join(BASE_DIR, "static", "index.html"))


@app.get("/login")
async def login_page(request: Request):
    if request.session.get("authenticated"):
        return RedirectResponse(url="/")
    return FileResponse(os.path.join(BASE_DIR, "static", "login.html"))


@app.post("/api/login")
async def login(request: Request):
    ip = request.client.host if request.client else "unknown"
    if _check_login_rate_limit(ip):
        return JSONResponse(
            {"ok": False, "detail": "試行回数が多すぎます。しばらくしてから再試行してください。"},
            status_code=429,
        )
    body = await request.json()
    if body.get("password") == PASSWORD:
        request.session["authenticated"] = True
        _login_attempts[ip] = []
        return JSONResponse({"ok": True})
    return JSONResponse({"ok": False, "detail": "パスワードが違います"}, status_code=401)


@app.post("/api/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)


# =========================================================
# 共通API
# =========================================================

@app.get("/api/holidays")
async def get_holidays(request: Request, year: int, month: int):
    require_auth(request)
    if month == 12:
        next_month_date = date(year + 1, 1, 1)
    else:
        next_month_date = date(year, month + 1, 1)

    first_day = date(year, month, 1)
    num_days = (next_month_date - first_day).days

    holiday_indices = []
    for d in range(num_days):
        current = first_day + timedelta(days=d)
        if current.weekday() == 6 or jpholiday.is_holiday(current):
            holiday_indices.append(d)

    return {"holiday_indices": holiday_indices}


# =========================================================
# タイプ別API
# =========================================================

@app.post("/api/{shift_type}/upload")
async def upload_excel(request: Request, shift_type: str, file: UploadFile = File(...)):
    require_auth(request)
    get_config(shift_type)  # タイプ検証

    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="xlsx形式のファイルをアップロードしてください")

    try:
        contents = await file.read()
        data = read_excel(contents)
    except Exception:
        raise HTTPException(status_code=400, detail="ファイルの読み込みに失敗しました。フォーマットを確認してください。")

    if not data["staff_ids"]:
        raise HTTPException(status_code=400, detail="職員データが見つかりません。フォーマットを確認してください。")

    return data


@app.post("/api/{shift_type}/generate")
async def generate(http_request: Request, shift_type: str, request: GenerateRequest):
    require_auth(http_request)
    config = get_config(shift_type)

    try:
        num_days = len(request.dates)
        schedule, warnings, emergency_used = generate_shift(
            staff_ids=request.staff_ids,
            day_limits=request.day_limits,
            night_limits=request.night_limits,
            schedule=request.schedule,
            num_days=num_days,
            holiday_flags=request.holiday_flags,
            closed_flags=request.closed_flags,
            total_limit=request.max_total_duties,
            min_gap=request.min_gap,
            config=config,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"シフト生成中にエラーが発生しました: {str(e)}")

    result: Dict[str, Any] = {"schedule": schedule, "warnings": warnings}
    if config.track_emergency:
        result["emergency_used"] = emergency_used
    return result


@app.post("/api/{shift_type}/download")
async def download_excel(http_request: Request, shift_type: str, request: DownloadRequest):
    require_auth(http_request)
    config = get_config(shift_type)

    try:
        excel_bytes = write_excel(
            staff_ids=request.staff_ids,
            day_limits=request.day_limits,
            night_limits=request.night_limits,
            dates=request.dates,
            schedule=request.schedule,
            closed_days=request.closed_days,
            sheet_title=config.sheet_title,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"エクセル生成中にエラーが発生しました: {str(e)}")

    # ファイル名をURLエンコード（RFC 5987）
    import urllib.parse
    encoded_filename = urllib.parse.quote(config.download_filename)

    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
        },
    )


# =========================================================
# 一括ダウンロード
# =========================================================

@app.post("/api/download-all")
async def download_all(http_request: Request, request: DownloadAllRequest):
    """アップロード済みの全タイプのExcelをZIPにまとめてダウンロード"""
    require_auth(http_request)

    if not request.types:
        raise HTTPException(status_code=400, detail="ダウンロードするデータがありません")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for shift_type, dl_req in request.types.items():
            config = SHIFT_CONFIGS.get(shift_type)
            if not config:
                continue
            try:
                excel_bytes = write_excel(
                    staff_ids=dl_req.staff_ids,
                    day_limits=dl_req.day_limits,
                    night_limits=dl_req.night_limits,
                    dates=dl_req.dates,
                    schedule=dl_req.schedule,
                    closed_days=dl_req.closed_days,
                    sheet_title=config.sheet_title,
                )
                zf.writestr(config.download_filename, excel_bytes)
            except Exception:
                continue  # 1ファイル失敗しても他を続行

    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="当直表一括.zip"'},
    )


# =========================================================
# 起動
# =========================================================

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
