"""
当直表 シフト自動生成エンジン（OR-Tools CP-SAT版）

シフト種別:
  当直 = 当直（毎日1人、すべての日に配置）
  日直 = 日直（日祝・休診日のみ、最大1人、未充足でも警告なし or あり（configによる））
  その他（☓、出など） = 固定値（生成対象外）

生成ルール:
  1. 毎日1人の当直を割り当て（全日必須）
  2. 日祝日・休診日に日直を割り当て（当直と別人）
  3. 中min_gap日空ける: 直前・直後min_gap日は別の当直/日直不可
  4. 個人の日直回数上限・当直回数上限を超えない
  5. 固定値（☓、出等）がある日は割り当て不可
"""

from typing import TYPE_CHECKING, List, Optional, Tuple

from ortools.sat.python import cp_model

if TYPE_CHECKING:
    from configs import ShiftConfig

DUTY_TYPES = {"当直", "日直"}
COVERAGE_MARKER = "割り当てられていません"


def generate_shift(
    staff_ids: List[str],
    day_limits: List[int],
    night_limits: List[int],
    schedule: List[List[str]],
    num_days: int,
    holiday_flags: List[bool],
    closed_flags: List[bool],
    total_limit: int = 6,
    min_gap: int = 2,
    config: Optional["ShiftConfig"] = None,
) -> Tuple[List[List[str]], List[str], bool]:
    """シフト生成のエントリーポイント。(schedule, warnings, emergency_used) を返す"""

    # configのデフォルト値（後方互換）
    min_gap_floor = config.min_gap_floor if config else 1
    require_all_nichoku = config.require_all_nichoku if config else True
    nichoku_requires_capacity = config.nichoku_requires_tochoku_capacity if config else False
    nichoku_weight = config.nichoku_objective_weight if config else 10

    num_staff = len(staff_ids)

    # ディープコピー
    sched = [row[:] for row in schedule]

    # 固定セルの判定
    fixed = [[cell.strip() != "" for cell in row] for row in schedule]

    # 固定値から当直/日直カウントを先に集計（変数定義に使用）
    fixed_tochoku = [0] * num_staff
    fixed_nichoku = [0] * num_staff
    for s in range(num_staff):
        for d in range(num_days):
            if sched[s][d] == "当直":
                fixed_tochoku[s] += 1
            elif sched[s][d] == "日直":
                fixed_nichoku[s] += 1

    # 日直が割り当て可能な日（日祝日・休診日）
    nichoku_days = [d for d in range(num_days) if holiday_flags[d] or closed_flags[d]]

    # --- CP-SAT モデル構築 ---
    model = cp_model.CpModel()

    # 変数: tochoku[s][d] = 1 ならスタッフ s が d 日に当直
    tochoku = {}
    for s in range(num_staff):
        for d in range(num_days):
            if fixed[s][d]:
                tochoku[s, d] = model.new_constant(1 if sched[s][d] == "当直" else 0)
            else:
                tochoku[s, d] = model.new_bool_var(f"tochoku_{s}_{d}")

    # 変数: nichoku[s][d] = 1 ならスタッフ s が d 日に日直
    nichoku = {}
    for s in range(num_staff):
        for d in nichoku_days:
            if fixed[s][d]:
                nichoku[s, d] = model.new_constant(1 if sched[s][d] == "日直" else 0)
            else:
                nichoku[s, d] = model.new_bool_var(f"nichoku_{s}_{d}")

    # 固定セルで当直/日直以外の値が入っている場合は割り当て不可
    for s in range(num_staff):
        for d in range(num_days):
            if fixed[s][d] and sched[s][d] != "当直":
                model.add(tochoku[s, d] == 0)
            if d in nichoku_days and fixed[s][d] and sched[s][d] != "日直":
                model.add(nichoku[s, d] == 0)

    # 制約1: 毎日ちょうど1人の当直
    for d in range(num_days):
        model.add(sum(tochoku[s, d] for s in range(num_staff)) == 1)

    # 制約2: 日直は各日最大1人
    for d in nichoku_days:
        model.add(sum(nichoku[s, d] for s in range(num_staff)) <= 1)

    # 制約2b: 同じ日に同じ人が当直と日直を兼務しない
    for s in range(num_staff):
        for d in nichoku_days:
            model.add(tochoku[s, d] + nichoku[s, d] <= 1)

    # 制約3: ギャップ制約（中min_gap日）
    for s in range(num_staff):
        for d in range(num_days):
            for d2 in range(d + 1, min(d + min_gap + 1, num_days)):
                terms_d = [tochoku[s, d]]
                if d in nichoku_days and (s, d) in nichoku:
                    terms_d.append(nichoku[s, d])
                terms_d2 = [tochoku[s, d2]]
                if d2 in nichoku_days and (s, d2) in nichoku:
                    terms_d2.append(nichoku[s, d2])
                model.add(sum(terms_d) + sum(terms_d2) <= 1)

    # 制約4a: 当直回数上限
    for s in range(num_staff):
        model.add(sum(tochoku[s, d] for d in range(num_days)) <= night_limits[s])

    # 制約4b: 日直回数上限
    for s in range(num_staff):
        if nichoku_days:
            model.add(sum(nichoku[s, d] for d in nichoku_days) <= day_limits[s])

    # 制約4c: 日当直合計上限
    for s in range(num_staff):
        all_duties = [tochoku[s, d] for d in range(num_days)]
        all_duties += [nichoku[s, d] for d in nichoku_days]
        model.add(sum(all_duties) <= total_limit)

    # 制約5: 日直は当直上限に達していないスタッフのみ（junya/resident）
    if nichoku_requires_capacity:
        for s in range(num_staff):
            if night_limits[s] > 0 and nichoku_days:
                tochoku_sum = sum(tochoku[s, d2] for d2 in range(num_days))
                for d in nichoku_days:
                    if (s, d) in nichoku:
                        model.add(nichoku[s, d] <= night_limits[s] - tochoku_sum)

    # 目的関数: 日直をできるだけ多く割り当てる + 当直・日直回数の均等化
    objective_terms = []
    for d in nichoku_days:
        for s in range(num_staff):
            if (s, d) in nichoku:
                objective_terms.append(nichoku[s, d])

    if num_staff > 1:
        max_tochoku = model.new_int_var(0, max(night_limits), "max_tochoku")
        min_tochoku = model.new_int_var(0, max(night_limits), "min_tochoku")
        for s in range(num_staff):
            s_total = sum(tochoku[s, d] for d in range(num_days))
            model.add(max_tochoku >= s_total)
            model.add(min_tochoku <= s_total)
        tochoku_spread = model.new_int_var(0, max(night_limits), "tochoku_spread")
        model.add(tochoku_spread == max_tochoku - min_tochoku)

        max_nichoku_var = model.new_int_var(0, max(day_limits) if day_limits else 0, "max_nichoku")
        min_nichoku_var = model.new_int_var(0, max(day_limits) if day_limits else 0, "min_nichoku")
        for s in range(num_staff):
            s_nichoku_total = sum(nichoku[s, d] for d in nichoku_days if (s, d) in nichoku)
            model.add(max_nichoku_var >= s_nichoku_total)
            model.add(min_nichoku_var <= s_nichoku_total)
        nichoku_spread = model.new_int_var(0, max(day_limits) if day_limits else 0, "nichoku_spread")
        model.add(nichoku_spread == max_nichoku_var - min_nichoku_var)

        model.maximize(
            nichoku_weight * sum(objective_terms) - tochoku_spread - nichoku_spread
        )
    elif objective_terms:
        model.maximize(sum(objective_terms))

    # --- ソルバー実行 ---
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30.0
    solver.parameters.num_workers = 4

    status = solver.solve(model)

    emergency_used = False
    warnings: List[str] = []

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # 解をスケジュールに反映
        for s in range(num_staff):
            for d in range(num_days):
                if not fixed[s][d]:
                    if solver.value(tochoku[s, d]) == 1:
                        sched[s][d] = "当直"
                    elif d in nichoku_days and (s, d) in nichoku and solver.value(nichoku[s, d]) == 1:
                        sched[s][d] = "日直"
    else:
        # 実行不能: ギャップを緩和して再試行
        if min_gap > min_gap_floor:
            sched_relaxed, warnings_relaxed, _ = generate_shift(
                staff_ids=staff_ids,
                day_limits=day_limits,
                night_limits=night_limits,
                schedule=schedule,
                num_days=num_days,
                holiday_flags=holiday_flags,
                closed_flags=closed_flags,
                total_limit=total_limit,
                min_gap=min_gap - 1,
                config=config,
            )
            return sched_relaxed, warnings_relaxed, True

        # フォールバック下限でも不可能な場合
        warnings.append("制約を満たすシフトが見つかりませんでした。制約を見直してください。")
        return sched, warnings, False

    # --- バリデーション ---
    tochoku_counts = [0] * num_staff
    nichoku_counts = [0] * num_staff
    for s in range(num_staff):
        for d in range(num_days):
            if sched[s][d] == "当直":
                tochoku_counts[s] += 1
            elif sched[s][d] == "日直":
                nichoku_counts[s] += 1

    for d in range(num_days):
        t_count = sum(1 for s in range(num_staff) if sched[s][d] == "当直")
        if t_count == 0:
            warnings.append(f"{d + 1}日: 当直が割り当てられていません")
        elif t_count > 1:
            warnings.append(f"{d + 1}日: 当直が{t_count}人います（1人のみ必要）")

        if holiday_flags[d] or closed_flags[d]:
            n_count = sum(1 for s in range(num_staff) if sched[s][d] == "日直")
            if n_count > 1:
                warnings.append(f"{d + 1}日: 日直が{n_count}人います（1人のみ必要）")
            # require_all_nichoku=True（ICU）の場合のみ日直未充足を警告
            elif n_count == 0 and require_all_nichoku:
                warnings.append(f"{d + 1}日: 日直が割り当てられていません（日祝・休診日）")

    for s in range(num_staff):
        if tochoku_counts[s] > night_limits[s]:
            warnings.append(
                f"職員{staff_ids[s]}: 当直{tochoku_counts[s]}回（上限{night_limits[s]}回）"
            )
        if nichoku_counts[s] > day_limits[s]:
            warnings.append(
                f"職員{staff_ids[s]}: 日直{nichoku_counts[s]}回（上限{day_limits[s]}回）"
            )
        total = tochoku_counts[s] + nichoku_counts[s]
        if total > total_limit:
            warnings.append(
                f"職員{staff_ids[s]}: 日当直合計{total}回（上限{total_limit}回）"
            )

        for d in range(num_days):
            if sched[s][d] not in DUTY_TYPES:
                continue
            for offset in range(1, min_gap + 1):
                prev = d - offset
                if prev >= 0 and sched[s][prev] in DUTY_TYPES:
                    warnings.append(
                        f"職員{staff_ids[s]}: {prev + 1}日と{d + 1}日の間隔が中{min_gap}日未満です"
                    )

    return sched, warnings, emergency_used
