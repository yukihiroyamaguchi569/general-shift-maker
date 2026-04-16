"""
当直表タイプごとの設定定義
"""

from dataclasses import dataclass
from typing import Dict


@dataclass
class ShiftConfig:
    name: str                               # "icu", "junya", "resident"
    display_name: str                       # UI表示名
    sheet_title: str                        # Excelシート名
    download_filename: str                  # ダウンロードファイル名
    default_min_gap: int                    # フロントエンド Phase1 の min_gap
    fallback_min_gap: int                   # フロントエンド Phase2 の min_gap
    min_gap_floor: int                      # ソルバー再帰フォールバックの下限
    require_all_nichoku: bool               # True=日直未充足を警告する（ICU）
    nichoku_requires_tochoku_capacity: bool # True=制約5を適用（junya/resident）
    track_emergency: bool                   # True=emergency_usedをAPIレスポンスに含める
    nichoku_objective_weight: int           # 目的関数での日直割当重み


SHIFT_CONFIGS: Dict[str, ShiftConfig] = {
    "icu": ShiftConfig(
        name="icu",
        display_name="ICU当直",
        sheet_title="当直表",
        download_filename="ICU当直表.xlsx",
        default_min_gap=2,
        fallback_min_gap=2,
        min_gap_floor=2,
        require_all_nichoku=True,
        nichoku_requires_tochoku_capacity=False,
        track_emergency=False,
        nichoku_objective_weight=1,
    ),
    "junya": ShiftConfig(
        name="junya",
        display_name="準夜当直",
        sheet_title="準夜当直表",
        download_filename="準夜当直表.xlsx",
        default_min_gap=3,
        fallback_min_gap=2,
        min_gap_floor=2,
        require_all_nichoku=False,
        nichoku_requires_tochoku_capacity=True,
        track_emergency=True,
        nichoku_objective_weight=10,
    ),
    "resident": ShiftConfig(
        name="resident",
        display_name="レジデント当直",
        sheet_title="当直表",
        download_filename="当直表.xlsx",
        default_min_gap=3,
        fallback_min_gap=2,
        min_gap_floor=2,
        require_all_nichoku=False,
        nichoku_requires_tochoku_capacity=True,
        track_emergency=True,
        nichoku_objective_weight=10,
    ),
}
