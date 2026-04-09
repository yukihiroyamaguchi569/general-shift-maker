"""
エクセルファイルの読み込み・書き出し（当直表フォーマット）

フォーマット:
  行1: ヘッダー（A1: 日直回数上限, B1: 当直回数上限, C1: 職員番号, D1以降: 日付）
  行2以降: 職員データ（A列: 日直上限, B列: 当直上限, C列: 職員番号, D列以降: シフト）

※ 休診日はUIのプルダウンで設定（Excel内に休診日行なし）
"""

from io import BytesIO
from typing import Any, Dict, List

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


# =========================================================
# シフト種別ごとの色設定
# =========================================================

SHIFT_COLORS = {
    "当直": {"bg": "1e3a5f", "fg": "FFFFFF"},  # 濃紺背景・白文字
    "日直": {"bg": "ffcdd2", "fg": "333333"},  # 薄赤背景・黒文字
}

# 固定値（☓, 出, 休 など）はグレー
FIXED_COLOR = {"bg": "e0e0e0", "fg": "666666"}


def read_excel(file_bytes: bytes) -> Dict[str, Any]:
    """
    エクセルファイルを読み込んでJSON用の辞書を返す

    Returns:
        {
            "staff_ids": ["01", "02", ...],
            "day_limits": [2, 0, ...],     # 日直回数上限
            "night_limits": [4, 6, ...],   # 当直回数上限
            "dates": [1, 2, ..., 31],
            "schedule": [["", "☓", ...], ...],
            "closed_days": [],
        }
    """
    wb = load_workbook(BytesIO(file_bytes), data_only=True)
    ws = wb.active

    # 行1のD列（col=4）以降から日付を読む
    date_col_start = 4
    dates: List[Any] = []

    for col in range(date_col_start, ws.max_column + 1):
        val = ws.cell(1, col).value
        if val is None:
            break
        try:
            day_num = int(val)
            if 1 <= day_num <= 31:
                dates.append(day_num)
            else:
                break
        except (ValueError, TypeError):
            break

    num_date_cols = len(dates)

    # 行2以降: 職員データ
    staff_ids: List[str] = []
    day_limits: List[int] = []
    night_limits: List[int] = []
    schedule: List[List[str]] = []

    for row_idx in range(2, ws.max_row + 1):
        staff_id = ws.cell(row_idx, 3).value
        if staff_id is None or str(staff_id).strip() == "":
            continue

        day_lim_val = ws.cell(row_idx, 1).value
        try:
            day_lim = int(day_lim_val) if day_lim_val is not None else 0
        except (ValueError, TypeError):
            day_lim = 0

        night_lim_val = ws.cell(row_idx, 2).value
        try:
            night_lim = int(night_lim_val) if night_lim_val is not None else 0
        except (ValueError, TypeError):
            night_lim = 0

        staff_ids.append(str(staff_id).strip())
        day_limits.append(day_lim)
        night_limits.append(night_lim)

        row_data: List[str] = []
        for col in range(date_col_start, date_col_start + num_date_cols):
            val = ws.cell(row_idx, col).value
            if val is None:
                row_data.append("")
            else:
                row_data.append(str(val).strip())
        schedule.append(row_data)

    return {
        "staff_ids": staff_ids,
        "day_limits": day_limits,
        "night_limits": night_limits,
        "dates": dates,
        "schedule": schedule,
        "closed_days": [],  # 休診日はUIで管理
    }


def write_excel(
    staff_ids: List[str],
    day_limits: List[int],
    night_limits: List[int],
    dates: List[Any],
    schedule: List[List[str]],
    closed_days: List[int],
    sheet_title: str = "当直表",
) -> bytes:
    """
    当直表データからエクセルファイルを生成してバイト列で返す
    """
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title

    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )
    header_fill = PatternFill(start_color="f5f5f5", end_color="f5f5f5", fill_type="solid")
    header_font = Font(bold=True, size=10)
    cell_font = Font(size=10)
    center_align = Alignment(horizontal="center", vertical="center")

    # 行1: ヘッダー
    headers = ["日直回数上限", "当直回数上限", "職員番号"]
    for i, h in enumerate(headers):
        cell = ws.cell(1, i + 1, h)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = thin_border
        cell.alignment = center_align

    ws.column_dimensions["A"].width = 12
    ws.column_dimensions["B"].width = 12
    ws.column_dimensions["C"].width = 10

    for i, date_val in enumerate(dates):
        col = i + 4
        cell = ws.cell(1, col, date_val)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = thin_border
        cell.alignment = center_align
        ws.column_dimensions[get_column_letter(col)].width = 4.5

    # 行2以降: 職員データ
    for row_idx, staff_id in enumerate(staff_ids):
        excel_row = row_idx + 2

        cell = ws.cell(excel_row, 1, day_limits[row_idx] if row_idx < len(day_limits) else 0)
        cell.font = cell_font
        cell.border = thin_border
        cell.alignment = center_align

        cell = ws.cell(excel_row, 2, night_limits[row_idx] if row_idx < len(night_limits) else 0)
        cell.font = cell_font
        cell.border = thin_border
        cell.alignment = center_align

        cell = ws.cell(excel_row, 3, staff_id)
        cell.font = cell_font
        cell.border = thin_border
        cell.alignment = center_align

        for col_idx, shift in enumerate(schedule[row_idx]):
            col = col_idx + 4
            cell = ws.cell(excel_row, col, shift)
            cell.border = thin_border
            cell.alignment = center_align

            if shift in SHIFT_COLORS:
                colors = SHIFT_COLORS[shift]
                cell.fill = PatternFill(
                    start_color=colors["bg"],
                    end_color=colors["bg"],
                    fill_type="solid",
                )
                cell.font = Font(size=10, color=colors["fg"], bold=(shift == "当直"))
            elif shift.strip() != "":
                cell.fill = PatternFill(
                    start_color=FIXED_COLOR["bg"],
                    end_color=FIXED_COLOR["bg"],
                    fill_type="solid",
                )
                cell.font = Font(size=10, color=FIXED_COLOR["fg"])
            else:
                cell.font = cell_font

    # フリーズペイン（1行目とC列を固定）
    ws.freeze_panes = "D2"

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()
