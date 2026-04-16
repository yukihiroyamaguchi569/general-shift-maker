/**
 * 当直表 一括作成システム - フロントエンドロジック
 */

// =========================================================
// タイプ設定（フロントエンド用）
// =========================================================

const SHIFT_TYPES = {
    icu: {
        name: "icu",
        displayName: "ICU当直",
        defaultMinGap: 2,
        fallbackMinGap: 1,
        hasEmergencyPanel: false,
        downloadFilename: "ICU当直表.xlsx",
    },
    junya: {
        name: "junya",
        displayName: "準夜当直",
        defaultMinGap: 3,
        fallbackMinGap: 2,
        hasEmergencyPanel: true,
        downloadFilename: "準夜当直表.xlsx",
    },
    resident: {
        name: "resident",
        displayName: "レジデント当直",
        defaultMinGap: 3,
        fallbackMinGap: 2,
        hasEmergencyPanel: true,
        downloadFilename: "当直表.xlsx",
    },
};

// =========================================================
// タイプ別状態管理
// =========================================================

const state = {};
for (const key of Object.keys(SHIFT_TYPES)) {
    state[key] = {
        uploadedData: null,
        originalSchedule: null,
        generatedSchedule: null,
        closedFlags: [],
    };
}

// 共通状態
let holidayIndices = [];
let activeTab = "icu";

// =========================================================
// DOM ヘルパー（タイプ別IDから要素取得）
// =========================================================

function el(id, type) {
    return document.getElementById(type ? `${id}-${type}` : id);
}

// =========================================================
// 年月ピッカー初期化
// =========================================================

{
    const now = new Date();
    const next = new Date(now.getFullYear(), now.getMonth() + 1, 1);
    const yyyy = next.getFullYear();
    const mm = String(next.getMonth() + 1).padStart(2, "0");
    document.getElementById("targetMonth").value = `${yyyy}-${mm}`;
}

document.getElementById("targetMonth").addEventListener("change", async () => {
    await fetchHolidays();
    for (const type of Object.keys(SHIFT_TYPES)) {
        if (state[type].uploadedData) {
            state[type].closedFlags = loadClosedDays(type, state[type].uploadedData.dates.length);
            const sched = state[type].generatedSchedule || state[type].uploadedData.schedule;
            renderTable(type, state[type].uploadedData.staff_ids, state[type].uploadedData.dates, sched);
        }
    }
});

// =========================================================
// 祝日取得
// =========================================================

async function fetchHolidays() {
    const monthVal = document.getElementById("targetMonth").value;
    if (!monthVal) return;
    const [yearStr, monthStr] = monthVal.split("-");
    try {
        const res = await fetch(`/api/holidays?year=${yearStr}&month=${parseInt(monthStr)}`);
        if (res.ok) {
            const data = await res.json();
            holidayIndices = data.holiday_indices;
        }
    } catch (e) {
        console.error("祝日取得エラー:", e);
        holidayIndices = [];
    }
}

// =========================================================
// タブ切替
// =========================================================

function switchTab(type) {
    // タブボタンの active 切替
    document.querySelectorAll(".tab-btn").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.tab === type);
    });
    // タブコンテンツの表示切替
    document.querySelectorAll(".tab-content").forEach(content => {
        content.classList.toggle("active", content.id === `tab-${type}`);
    });
    activeTab = type;
}

// =========================================================
// ドラッグ&ドロップ + ファイル選択（各タイプ）
// =========================================================

for (const type of Object.keys(SHIFT_TYPES)) {
    const dropZone = el("dropZone", type);
    const fileInput = el("fileInput", type);

    dropZone.addEventListener("click", () => fileInput.click());

    dropZone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropZone.classList.add("drag-over");
    });
    dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag-over"));
    dropZone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropZone.classList.remove("drag-over");
        const files = e.dataTransfer.files;
        if (files.length > 0) handleFileUpload(type, files[0]);
    });

    fileInput.addEventListener("change", () => {
        if (fileInput.files.length > 0) handleFileUpload(type, fileInput.files[0]);
    });

    el("generateBtn", type).addEventListener("click", () => generateShift(type));
    el("downloadBtn", type).addEventListener("click", () => downloadShift(type));
}

// =========================================================
// ファイルアップロード
// =========================================================

async function handleFileUpload(type, file) {
    if (!file.name.match(/\.(xlsx?|csv)$/i)) {
        alert("xlsx または csv 形式のファイルを選択してください");
        return;
    }

    const formData = new FormData();
    formData.append("file", file);

    try {
        showLoading(type, true);
        await fetchHolidays();

        const res = await fetch(`/api/${type}/upload`, { method: "POST", body: formData });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "アップロードに失敗しました");
        }

        const data = await res.json();
        state[type].uploadedData = data;
        state[type].originalSchedule = data.schedule.map(row => [...row]);
        state[type].generatedSchedule = null;

        const numDays = data.dates.length;
        state[type].closedFlags = loadClosedDays(type, numDays);

        el("fileName", type).textContent = file.name;
        el("staffCount", type).textContent = `（${data.staff_ids.length}名 × ${numDays}日）`;
        el("fileInfo", type).classList.remove("hidden");

        el("generateBtn", type).disabled = false;
        resetGenerateBtnLabel(type);
        el("downloadBtn", type).disabled = true;

        renderTable(type, data.staff_ids, data.dates, data.schedule);
        hideWarnings(type);
        if (SHIFT_TYPES[type].hasEmergencyPanel) hidePanel(el("emergencyPanel", type));

        // アップロード済みバッジを表示
        el("tab-badge", type).classList.remove("hidden");
        // 全て作成ボタンの有効化チェック
        updateGlobalButtons();

    } catch (err) {
        alert(err.message);
    } finally {
        showLoading(type, false);
    }
}

// =========================================================
// シフト生成（タイプ別）
// =========================================================

async function generateShift(type) {
    const s = state[type];
    if (!s.uploadedData) return;

    const cfg = SHIFT_TYPES[type];
    const maxTotalDuties = Math.max(1, parseInt(document.getElementById("maxTotalDuties").value) || 6);
    const numDays = s.uploadedData.dates.length;

    const holidaySet = new Set(holidayIndices);
    const holidayFlagsArr = Array.from({ length: numDays }, (_, i) => holidaySet.has(i));

    let bestSchedule = null;
    let bestWarnings = null;
    let bestEmergencyUsed = false;

    const callGenerate = async (minGap) => {
        el("loadingText", type).textContent = `${cfg.displayName} 生成中...`;
        const res = await fetch(`/api/${type}/generate`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                staff_ids: s.uploadedData.staff_ids,
                day_limits: s.uploadedData.day_limits,
                night_limits: s.uploadedData.night_limits,
                dates: s.uploadedData.dates,
                schedule: s.originalSchedule.map(row => [...row]),
                holiday_flags: holidayFlagsArr,
                closed_flags: s.closedFlags,
                max_total_duties: maxTotalDuties,
                min_gap: minGap,
            }),
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "シフト生成に失敗しました");
        }
        return await res.json();
    };

    try {
        showLoading(type, true);

        // デフォルトmin_gapで生成
        const result = await callGenerate(cfg.defaultMinGap);
        bestSchedule = result.schedule;
        bestWarnings = result.warnings || [];
        bestEmergencyUsed = result.emergency_used || false;

        // 警告がある場合、フォールバックmin_gapで再試行
        if (bestWarnings.length > 0) {
            const fallbackResult = await callGenerate(cfg.fallbackMinGap);
            const fallbackWarnings = fallbackResult.warnings || [];
            if (fallbackWarnings.length < bestWarnings.length) {
                bestSchedule = fallbackResult.schedule;
                bestWarnings = fallbackWarnings;
                bestEmergencyUsed = fallbackResult.emergency_used || false;
            }
        }

        state[type].generatedSchedule = bestSchedule;
        resetGenerateBtnLabel(type, true);
        el("downloadBtn", type).disabled = false;

        renderTable(type, s.uploadedData.staff_ids, s.uploadedData.dates, bestSchedule);

        // 緊急割当パネル（対応タイプのみ）
        if (cfg.hasEmergencyPanel) {
            if (bestEmergencyUsed) {
                showPanel(el("emergencyPanel", type));
            } else {
                hidePanel(el("emergencyPanel", type));
            }
        }

        // 警告表示
        if (bestWarnings && bestWarnings.length > 0) {
            showWarnings(type, bestWarnings);
        } else {
            hideWarnings(type);
        }

        updateGlobalButtons();

    } catch (err) {
        alert(err.message);
    } finally {
        showLoading(type, false);
    }
}

// =========================================================
// 全て作成
// =========================================================

async function generateAll() {
    const uploadedTypes = Object.keys(SHIFT_TYPES).filter(t => state[t].uploadedData);
    if (uploadedTypes.length === 0) return;

    document.getElementById("generateAllBtn").disabled = true;
    try {
        await Promise.all(uploadedTypes.map(type => generateShift(type)));
    } finally {
        updateGlobalButtons();
    }
}

document.getElementById("generateAllBtn").addEventListener("click", generateAll);

// =========================================================
// ダウンロード（タイプ別）
// =========================================================

async function downloadShift(type) {
    const s = state[type];
    if (!s.generatedSchedule) return;

    const closedDaysArr = s.closedFlags.map((f, i) => f ? i : -1).filter(i => i >= 0);

    try {
        showLoading(type, true);
        const res = await fetch(`/api/${type}/download`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                staff_ids: s.uploadedData.staff_ids,
                day_limits: s.uploadedData.day_limits,
                night_limits: s.uploadedData.night_limits,
                dates: s.uploadedData.dates,
                schedule: s.generatedSchedule,
                closed_days: closedDaysArr,
            }),
        });
        if (!res.ok) throw new Error("ダウンロードに失敗しました");

        const blob = await res.blob();
        triggerDownload(blob, SHIFT_TYPES[type].downloadFilename);
    } catch (err) {
        alert(err.message);
    } finally {
        showLoading(type, false);
    }
}

// =========================================================
// 全てダウンロード（ZIP）
// =========================================================

async function downloadAll() {
    const generatedTypes = Object.keys(SHIFT_TYPES).filter(t => state[t].generatedSchedule);
    if (generatedTypes.length === 0) return;

    const types = {};
    for (const type of generatedTypes) {
        const s = state[type];
        const closedDaysArr = s.closedFlags.map((f, i) => f ? i : -1).filter(i => i >= 0);
        types[type] = {
            staff_ids: s.uploadedData.staff_ids,
            day_limits: s.uploadedData.day_limits,
            night_limits: s.uploadedData.night_limits,
            dates: s.uploadedData.dates,
            schedule: s.generatedSchedule,
            closed_days: closedDaysArr,
        };
    }

    try {
        document.getElementById("downloadAllBtn").disabled = true;
        const res = await fetch("/api/download-all", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ types }),
        });
        if (!res.ok) throw new Error("一括ダウンロードに失敗しました");

        const blob = await res.blob();
        triggerDownload(blob, "当直表一括.zip");
    } catch (err) {
        alert(err.message);
    } finally {
        updateGlobalButtons();
    }
}

document.getElementById("downloadAllBtn").addEventListener("click", downloadAll);

// =========================================================
// ログアウト
// =========================================================

document.getElementById("logoutBtn").addEventListener("click", async () => {
    await fetch("/api/logout", { method: "POST" });
    window.location.href = "/login";
});

// =========================================================
// テーブル描画
// =========================================================

function renderTable(type, staffIds, dates, schedule) {
    const s = state[type];
    const numDays = dates.length;
    const holidaySet = new Set(holidayIndices);

    let html = "<thead><tr>";
    html += '<th class="staff-col">職員番号</th>';
    for (let d = 0; d < numDays; d++) {
        const isHoliday = holidaySet.has(d) || s.closedFlags[d];
        html += `<th class="${isHoliday ? "holiday-header" : ""}">${dates[d]}</th>`;
    }
    html += '<th class="stats-col">当直</th><th class="stats-col">日直</th></tr>';

    // 休診日プルダウン行
    html += `<tr class="closed-row"><td class="staff-col closed-label">休診日</td>`;
    for (let d = 0; d < numDays; d++) {
        const checked = s.closedFlags[d] ? "selected" : "";
        html += `<td><select class="closed-select" data-day="${d}" data-type="${type}" onchange="onClosedChange(this)">
            <option value="">　</option>
            <option value="休" ${checked}>休</option>
        </select></td>`;
    }
    html += '<td class="stats-col"></td><td class="stats-col"></td></tr></thead>';

    html += "<tbody>";
    for (let i = 0; i < staffIds.length; i++) {
        html += `<tr><td class="staff-col">${escapeHtml(staffIds[i])}</td>`;
        let tochokuCount = 0;
        let nichokuCount = 0;

        for (let d = 0; d < numDays; d++) {
            const shift = schedule[i] && schedule[i][d] != null ? schedule[i][d] : "";
            const isFixed = s.originalSchedule
                ? (s.originalSchedule[i][d] && s.originalSchedule[i][d].trim() !== "")
                : false;
            html += `<td class="${getCellClass(shift, isFixed)}">${escapeHtml(shift)}</td>`;
            if (shift === "当直") tochokuCount++;
            if (shift === "日直") nichokuCount++;
        }
        html += `<td class="stats-col">${tochokuCount}</td><td class="stats-col">${nichokuCount}</td></tr>`;
    }

    // 当直計行
    html += '<tr class="summary-row"><td class="staff-col">当直計</td>';
    for (let d = 0; d < numDays; d++) {
        const cnt = staffIds.reduce((acc, _, i) => acc + (schedule[i] && schedule[i][d] === "当直" ? 1 : 0), 0);
        html += `<td class="${cnt === 0 ? "text-red-600 font-bold" : "text-gray-600"}">${cnt}</td>`;
    }
    html += '<td class="stats-col"></td><td class="stats-col"></td></tr>';

    // 日直計行
    html += '<tr class="summary-row"><td class="staff-col">日直計</td>';
    for (let d = 0; d < numDays; d++) {
        const isHolidayOrClosed = holidaySet.has(d) || s.closedFlags[d];
        const cnt = staffIds.reduce((acc, _, i) => acc + (schedule[i] && schedule[i][d] === "日直" ? 1 : 0), 0);
        let cls = "text-gray-400";
        if (isHolidayOrClosed) cls = cnt === 0 ? "text-red-600 font-bold" : "text-gray-600";
        html += `<td class="${cls}">${isHolidayOrClosed || cnt > 0 ? cnt : ""}</td>`;
    }
    html += '<td class="stats-col"></td><td class="stats-col"></td></tr></tbody>';

    el("scheduleTable", type).innerHTML = html;
    showPanel(el("tablePanel", type));
}

function getCellClass(shift, isFixed) {
    if (shift === "当直") return "shift-tochoku" + (isFixed ? " shift-fixed" : "");
    if (shift === "日直") return "shift-nichoku" + (isFixed ? " shift-fixed" : "");
    if (shift.trim() !== "") return "shift-fixed-cell" + (isFixed ? " shift-fixed" : "");
    return "";
}

// =========================================================
// 休診日変更
// =========================================================

function onClosedChange(select) {
    const d = parseInt(select.dataset.day);
    const type = select.dataset.type;
    state[type].closedFlags[d] = select.value === "休";
    saveClosedDays(type);

    // ヘッダー色更新
    const table = el("scheduleTable", type);
    const ths = table.querySelectorAll("thead tr:first-child th");
    const th = ths[d + 1];
    if (th) {
        const isHoliday = new Set(holidayIndices).has(d) || state[type].closedFlags[d];
        th.classList.toggle("holiday-header", isHoliday);
    }
}

// =========================================================
// localStorage 保存・復元（タイプ別）
// =========================================================

function saveClosedDays(type) {
    const monthVal = document.getElementById("targetMonth").value;
    if (!monthVal) return;
    const indices = state[type].closedFlags.map((f, i) => f ? i : -1).filter(i => i >= 0);
    localStorage.setItem(`closedDays_${type}_${monthVal}`, JSON.stringify(indices));
}

function loadClosedDays(type, numDays) {
    const monthVal = document.getElementById("targetMonth").value;
    if (!monthVal) return Array(numDays).fill(false);
    const saved = localStorage.getItem(`closedDays_${type}_${monthVal}`);
    if (!saved) return Array(numDays).fill(false);
    try {
        const indices = JSON.parse(saved);
        const flags = Array(numDays).fill(false);
        for (const i of indices) {
            if (i >= 0 && i < numDays) flags[i] = true;
        }
        return flags;
    } catch {
        return Array(numDays).fill(false);
    }
}

// =========================================================
// UI ユーティリティ
// =========================================================

function showPanel(elem) {
    if (elem) elem.classList.remove("panel-hidden");
}

function hidePanel(elem) {
    if (elem) elem.classList.add("panel-hidden");
}

function showLoading(type, show) {
    const loadingEl = el("loading", type);
    if (show) showPanel(loadingEl); else hidePanel(loadingEl);
    el("generateBtn", type).disabled = show || !state[type].uploadedData;
    el("downloadBtn", type).disabled = show || !state[type].generatedSchedule;
}

function showWarnings(type, warnings) {
    el("warningsList", type).innerHTML = warnings.map(w => `<li>${escapeHtml(w)}</li>`).join("");
    showPanel(el("warningsPanel", type));
}

function hideWarnings(type) {
    hidePanel(el("warningsPanel", type));
    setTimeout(() => { if (el("warningsList", type)) el("warningsList", type).innerHTML = ""; }, 500);
}

function resetGenerateBtnLabel(type, done = false) {
    const btn = el("generateBtn", type);
    const label = done ? "再作成" : "シフト作成";
    btn.innerHTML = btn.innerHTML.replace(/シフト作成|再作成/, label);
}

function updateGlobalButtons() {
    const anyUploaded = Object.keys(SHIFT_TYPES).some(t => state[t].uploadedData);
    const anyGenerated = Object.keys(SHIFT_TYPES).some(t => state[t].generatedSchedule);
    document.getElementById("generateAllBtn").disabled = !anyUploaded;
    document.getElementById("downloadAllBtn").disabled = !anyGenerated;
}

function triggerDownload(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

// =========================================================
// 初期化
// =========================================================

fetchHolidays();
