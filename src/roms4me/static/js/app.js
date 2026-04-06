/** @type {string|null} */
let currentSystem = null;

/** Row currently displayed in the analysis panel (null when panel is closed). */
let _currentAnalysisRow = null;

const statusText = document.getElementById("status-text");

// --- Queue ---

/** @type {Array<{system: string, file_name: string, game_name: string, plan: string, note: string}>} */
const exportQueue = [];

/**
 * Settings snapshot captured at queue-add time, keyed by system name.
 * @type {Record<string, {dest: string, rom_only: boolean, archive_format: string, region_priority: string}>}
 */
const exportSystemSettings = {};

// --- API helpers ---

async function fetchJson(url, opts = {}) {
    const res = await fetch(url, opts);
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || res.statusText);
    }
    return res.json();
}

function setStatus(msg) {
    /** Set the status bar text, stripping any [color] prefix. */
    statusText.textContent = msg.replace(/^\[(green|yellow|red|blue)\]/, "");
}

function esc(str) {
    const d = document.createElement("div");
    d.textContent = str;
    return d.innerHTML;
}

// --- Scan log rendering ---

/** Color map for [color] prefixed log lines. */
const LOG_COLORS = {
    green: "log-ok",
    yellow: "log-other",
    red: "log-missing",
    blue: "log-system",
};

/** Patterns to colorize only the keyword portion, not the whole line. */
const KEYWORD_PATTERN = /^(\s*\S+\s*)(GREEN|YELLOW|RED)(:.*)$/;

function appendScanLogLine(container, line) {
    /** Append a log line, parsing [color] prefix from backend. */
    const div = document.createElement("div");
    div.className = "log-line";

    // Parse [color] prefix
    const colorMatch = line.match(/^\[(green|yellow|red|blue)\](.*)/);
    if (colorMatch) {
        const cls = LOG_COLORS[colorMatch[1]];
        const text = colorMatch[2];
        // Only color the emoji + keyword (GREEN/YELLOW/RED), not the rest
        const kwMatch = text.match(KEYWORD_PATTERN);
        if (kwMatch) {
            div.innerHTML =
                '<span class="' + cls + '">' + esc(kwMatch[1] + kwMatch[2]) + '</span>' +
                esc(kwMatch[3]);
        } else {
            // For blue (system headers) and completion lines, color the whole thing
            div.innerHTML = '<span class="' + cls + '">' + esc(text) + '</span>';
        }
    } else {
        div.textContent = line;
    }

    container.appendChild(div);
}

// --- Views ---

function showView(name) {
    document.getElementById("welcome-view").hidden = name !== "welcome";
    document.getElementById("scan-log-view").hidden = name !== "scan-log";
    document.getElementById("game-list").hidden = name !== "game-list";
}

// --- Welcome / Stats ---

async function loadWelcome() {
    try {
        const stats = await fetchJson("/api/stats");
        const el = document.getElementById("welcome-content");

        if (stats.systems === 0 && stats.dat_files === 0) {
            el.innerHTML =
                "<h4>Welcome to roms4me</h4>" +
                "<p>Get started by adding your DAT and ROM directories in Settings.</p>" +
                '<button id="welcome-settings" class="outline">Open Settings</button>';
            document.getElementById("welcome-settings").addEventListener("click", () => {
                document.getElementById("btn-settings").click();
            });
        } else {
            let html = "<h4>roms4me</h4>" +
                '<div class="welcome-stats">' +
                '<div class="stat-card"><div class="stat-value">' + stats.systems + '</div><div class="stat-label">Systems</div></div>' +
                '<div class="stat-card"><div class="stat-value">' + stats.dat_files + '</div><div class="stat-label">DAT Files</div></div>' +
                '<div class="stat-card"><div class="stat-value">' + stats.rom_paths + '</div><div class="stat-label">ROM Paths</div></div>' +
                '<div class="stat-card"><div class="stat-value">' + stats.scanned_games + '</div><div class="stat-label">Scanned Games</div></div>' +
                "</div>";
            if (!stats.last_scan) {
                html += '<p>No scan yet. Click <strong>&#x21bb;</strong> to scan your ROMs.</p>';
            } else {
                html += "<p>Select a system from the sidebar to view results.</p>";
            }
            el.innerHTML = html;
        }

        updateLastScanTime(stats.last_scan);

        // Notify about stale scan data
        if (stats.stale_systems && stats.stale_systems.length > 0) {
            const n = stats.stale_systems.length;
            setStatus(n + " system(s) have results from removed paths \u2014 Sync to clean up");
        }
    } catch (e) {
        setStatus("Error loading stats: " + e.message);
    }
}

function updateLastScanTime(isoTime) {
    const el = document.getElementById("last-scan-time");
    if (isoTime) {
        const d = new Date(isoTime);
        el.textContent = "Last Sync: " + d.toLocaleString();
    } else {
        el.textContent = "";
    }
}

// --- Sidebar ---

async function loadSystems() {
    /** Load sidebar from ROM paths, with pre-scan ratings. */
    try {
        const romPaths = await fetchJson("/api/roms/paths");
        let prescanResults = [];
        try {
            prescanResults = await fetchJson("/api/prescan-results");
        } catch (_) {}

        // Build rating lookup by system name
        const ratings = {};
        for (const pr of prescanResults) {
            ratings[pr.system] = pr;
        }

        const tree = document.getElementById("system-tree");
        tree.innerHTML = "";

        // Deduplicate by system name
        const seen = new Set();
        for (const rp of romPaths) {
            if (seen.has(rp.system)) continue;
            seen.add(rp.system);
            const li = document.createElement("li");
            const rating = ratings[rp.system];
            const dot = rating
                ? '<span class="rating-dot rating-' + rating.rating + '"></span> '
                : '<span class="rating-dot rating-none"></span> ';
            li.innerHTML = dot + esc(rp.system);
            li.dataset.system = rp.system;
            li.title = rp.path;
            li.addEventListener("click", () => selectSystem(rp.system));
            tree.appendChild(li);
        }
        if (romPaths.length === 0) {
            tree.innerHTML = "<li><em>No ROM paths configured.</em></li>";
        }
    } catch (e) {
        setStatus("Error loading systems: " + e.message);
    }
}

async function selectSystem(systemName) {
    /** Show system view: pre-scan info, matched DATs, and CRC results if available. */
    currentSystem = systemName;

    document.querySelectorAll("#system-tree li").forEach((li) => {
        li.classList.toggle("active", li.dataset.system === systemName);
    });

    // Show the game list view immediately so the user sees something
    document.getElementById("game-list-title").textContent = systemName;
    showView("game-list");
    setStatus("Loading " + systemName + "...");

    try {
        // Fetch data in parallel
        const [matchedDats, prescanResults, resultData] = await Promise.all([
            fetchJson("/api/matched-dats/" + encodeURIComponent(systemName)).catch(() => []),
            fetchJson("/api/prescan-results").catch(() => []),
            fetchJson("/api/results/" + encodeURIComponent(systemName) + "?view=all").catch(() => (
                { rows: [], owned_count: 0, missing_count: 0, unmatched_count: 0, total_count: 0 }
            )),
        ]);
        const prescan = prescanResults.find((p) => p.system === systemName);

        // Header: title
        document.getElementById("game-list-title").textContent = systemName;

        // Header: meta info
        const meta = document.getElementById("game-list-meta");
        let metaHtml = "";
        if (matchedDats.length > 0) {
            metaHtml += "DAT: " + matchedDats.map((d) => esc(d.filename)).join(", ");
        } else {
            metaHtml += "<em>No matching DAT</em>";
        }
        if (prescan) {
            metaHtml += " | " + prescan.rom_file_count + " ROM files";
            metaHtml += " | " + prescan.dat_game_count + " in DAT";
        }
        meta.innerHTML = metaHtml;

        // Status summary badges
        const summaryEl = document.getElementById("status-summary");
        if (resultData.total_count > 0) {
            const hasVerified = resultData.rows.some((r) => r.status === "ok");
            const ownedLabel = hasVerified ? "verified" : "unverified";
            const ownedClass = hasVerified ? "ok" : "unverified";
            let badges = '<span class="status-badge ' + ownedClass + '" title="' + (hasVerified ? "CRC verified" : "Matched by name, not yet CRC verified") + '">' + resultData.owned_count + " " + ownedLabel + "</span>";
            if (resultData.unmatched_count > 0) {
                badges += '<span class="status-badge unmatched" title="ROM files with no DAT match — CRC verify may identify these">' + resultData.unmatched_count + " unmatched</span>";
            }
            badges += '<span class="status-badge missing-count" title="DAT games not in your collection">' + resultData.missing_count + " missing</span>";
            summaryEl.innerHTML = badges;
        } else {
            summaryEl.innerHTML = "";
        }

        // Toolbar buttons
        const analyzeBtn = document.getElementById("btn-analyze");
        const viewAnalysisBtn = document.getElementById("btn-view-analysis");
        const exportBtn = document.getElementById("btn-add-queue");
        const deleteBtn = document.getElementById("btn-exclude");
        analyzeBtn.disabled = true;
        exportBtn.disabled = true;

        // Wire up analyze button
        analyzeBtn.onclick = () => startAnalysis(systemName);
        viewAnalysisBtn.onclick = () => {
            const rows = gameGrid.getSelectedRows();
            if (rows.length === 1) showRomAnalysis(rows[0]);
        };
        exportBtn.onclick = () => {
            const rows = gameGrid.getSelectedRows();
            if (rows.length > 0) addToQueue(rows);
        };
        deleteBtn.onclick = () => {
            const rows = gameGrid.getSelectedRows();
            if (rows.length > 0) setRowPlan(rows, "exclude");
        };

        // Grid data — all rows, default filter hides "missing"
        gameGrid.filters = {};
        gameGrid.setData(resultData.rows);
        gameGrid.setFilter("status", new Set(["ok", "unverified", "unmatched", "matched"]));
        gameGrid.onSelectionChange = (selected) => {
            const n = selected.length;
            const allAnalyzed = n > 0 && selected.every((r) => r.status && r.status !== "unverified");
            analyzeBtn.disabled = n === 0;
            analyzeBtn.textContent = allAnalyzed ? "Re-analyze (" + n + ")" : n > 0 ? "Analyze (" + n + ")" : "Analyze";
            viewAnalysisBtn.hidden = !(allAnalyzed && n === 1);
            exportBtn.disabled = n === 0;
            exportBtn.textContent = n > 0 ? "Add to Queue (" + n + ")" : "Add to Queue";
            deleteBtn.hidden = n === 0;
            deleteBtn.textContent = "Exclude (" + n + ")";
        };

        setStatus(systemName + " (" + resultData.owned_count + " owned, " + resultData.missing_count + " missing)");
    } catch (e) {
        setStatus("Error: " + e.message);
    }
}

// Close verify panel
document.getElementById("verify-panel-close").addEventListener("click", () => {
    document.getElementById("verify-panel").hidden = true;
    _currentAnalysisRow = null;
});

async function startAnalysis(systemName) {
    /** Analyze selected ROMs — kick off background task, poll for progress. */
    const selected = gameGrid.getSelectedRows();
    if (selected.length === 0) return;

    const files = [...new Set(selected.map((r) => r.file_name).filter(Boolean))];
    if (files.length === 0) {
        setStatus("No files to analyze (selected rows have no file)");
        return;
    }

    // Open split panel
    const verifyPanel = document.getElementById("verify-panel");
    const verifyLog = document.getElementById("verify-log");
    verifyPanel.querySelector("#verify-panel-header strong").textContent = "Verification Log";
    verifyPanel.hidden = false;
    verifyLog.innerHTML = "";
    Resize.initVertical("resize-verify", "verify-panel");

    const analyzeBtn = document.getElementById("btn-analyze");
    analyzeBtn.disabled = true;

    // Start the background analysis
    try {
        const start = await fetchJson("/api/analyze/" + encodeURIComponent(systemName), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ files }),
        });
        if (start.status === "already_running") {
            appendScanLogLine(verifyLog, "[red]A task is already in progress");
            analyzeBtn.disabled = false;
            return;
        }
    } catch (e) {
        appendScanLogLine(verifyLog, "[red]Error: " + e.message);
        analyzeBtn.disabled = false;
        return;
    }

    // Poll for progress
    let transientEl = null;
    const pollInterval = setInterval(async () => {
        try {
            const status = await fetchJson("/api/refresh/status");
            for (const msg of status.messages) {
                if (msg.transient) {
                    if (!transientEl) {
                        transientEl = document.createElement("div");
                        transientEl.className = "log-line log-progress";
                        verifyLog.appendChild(transientEl);
                    }
                    transientEl.textContent = msg.text.replace(/^\[(green|yellow|red|blue)\]/, "");
                } else {
                    if (transientEl) {
                        transientEl.remove();
                        transientEl = null;
                    }
                    appendScanLogLine(verifyLog, msg.text);
                }
            }
            verifyLog.scrollTop = verifyLog.scrollHeight;

            // Apply live row updates to the grid
            if (status.updated_rows && status.updated_rows.length > 0) {
                for (const row of status.updated_rows) {
                    gameGrid.replaceRows("file_name", row.file_name, row);
                }
                gameGrid.refresh();
            }

            if (status.done) {
                clearInterval(pollInterval);
                analyzeBtn.disabled = false;

                // Reload table data
                const resultData = await fetchJson("/api/results/" + encodeURIComponent(systemName) + "?view=all");
                gameGrid.allData = resultData.rows;

                // Focus on analyzed ROMs: filter Game column to show
                // analyzed rows and any related rows (same game name),
                // with all statuses visible so nothing is hidden
                const analyzedFiles = new Set(files);
                const analyzedNames = new Set();
                for (const r of resultData.rows) {
                    if (analyzedFiles.has(r.file_name)) {
                        analyzedNames.add(String(r.description ?? ""));
                    }
                }
                if (analyzedNames.size > 0) {
                    gameGrid.filters = {};
                    gameGrid.setFilter("status", new Set(["ok", "unverified", "unmatched", "matched", "duplicate"]));
                    gameGrid.setFilter("description", analyzedNames);
                } else {
                    gameGrid.refresh();
                }

                // Update badges
                const summaryEl = document.getElementById("status-summary");
                const hasVerified = resultData.rows.some((r) => r.status === "ok" || r.status === "matched");
                const ownedLabel = hasVerified ? "verified" : "unverified";
                const ownedClass = hasVerified ? "ok" : "unverified";
                let badges = '<span class="status-badge ' + ownedClass + '">' + resultData.owned_count + " " + ownedLabel + "</span>";
                if (resultData.unmatched_count > 0) {
                    badges += '<span class="status-badge unmatched">' + resultData.unmatched_count + " unmatched</span>";
                }
                badges += '<span class="status-badge missing-count">' + resultData.missing_count + " missing</span>";
                summaryEl.innerHTML = badges;
            }
        } catch (e) {
            clearInterval(pollInterval);
            appendScanLogLine(verifyLog, "[red]Poll error: " + e.message);
            analyzeBtn.disabled = false;
        }
    }, 500);
}

// --- DataGrid ---

function renderPlanCell(td, val, row) {
    /** Render the Plan column — "modify" is a clickable link that shows the export plan. */
    if (!val) {
        td.textContent = "";
        return;
    }
    if (val === "modify") {
        const link = document.createElement("a");
        link.href = "#";
        link.textContent = "modify";
        link.className = "plan-link plan-modify";
        link.addEventListener("click", (e) => {
            e.preventDefault();
            e.stopPropagation();
            showExportPlan(row);
        });
        td.appendChild(link);
    } else if (val === "ok") {
        td.textContent = "ok";
        td.classList.add("plan-ok");
    } else if (val === "exclude") {
        td.textContent = "exclude";
        td.classList.add("plan-exclude");
    } else {
        td.textContent = val;
    }
}

async function setRowPlan(rows, plan) {
    /** Set the plan field on selected rows via API and update the grid. */
    const files = [...new Set(rows.map((r) => r.file_name).filter(Boolean))];
    if (files.length === 0) return;

    try {
        await fetchJson("/api/results/" + encodeURIComponent(currentSystem), {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ files, plan }),
        });
        // Update local data and re-render
        for (const row of rows) {
            row.plan = plan;
        }
        gameGrid.refresh();
    } catch (e) {
        setStatus("Error: " + e.message);
    }
}

// --- Queue functions ---

/** Pending rows waiting for export-settings confirmation. */
let _pendingQueueRows = [];

function addToQueue(rows) {
    /** Open export-settings modal for the given rows, then add on confirm. */
    if (!rows.length) return;
    _pendingQueueRows = rows;

    // Load saved settings for this system from the API
    fetchJson("/api/config/export-settings/" + encodeURIComponent(currentSystem))
        .then((s) => _openExportSettingsModal(s, rows.length))
        .catch(() => _openExportSettingsModal({}, rows.length));
}

function _openExportSettingsModal(settings, rowCount) {
    /** Pre-fill the export settings modal and open it. */
    document.getElementById("export-settings-title").textContent =
        "Export Settings — " + (currentSystem || "");
    document.getElementById("export-dest-input").value = settings.dest || "";
    document.getElementById("export-rom-only").checked = settings.rom_only !== false;
    document.getElementById("export-one-game").checked = settings.one_game_one_rom !== false;
    document.getElementById("export-use-7z").checked = settings.archive_format === "7z";
    document.getElementById("export-region-input").value =
        settings.region_priority || "USA, World, Europe, Japan";
    document.getElementById("export-conflict-notice").hidden = true;

    // Region row visible only when one_game_one_rom is on
    const oneGame = document.getElementById("export-one-game");
    const regionRow = document.getElementById("export-region-row");
    regionRow.hidden = !oneGame.checked;
    oneGame.onchange = () => { regionRow.hidden = !oneGame.checked; };

    const confirmBtn = document.getElementById("export-settings-confirm");
    confirmBtn.textContent = "Add " + rowCount + " to Queue";

    Modal.open("export-settings-modal");
}

document.getElementById("export-settings-cancel").addEventListener("click", () => {
    _pendingQueueRows = [];
    Modal.close("export-settings-modal");
});

document.getElementById("export-settings-confirm").addEventListener("click", () => {
    const dest = document.getElementById("export-dest-input").value.trim();
    const romOnly = document.getElementById("export-rom-only").checked;
    const oneGame = document.getElementById("export-one-game").checked;
    const use7z = document.getElementById("export-use-7z").checked;
    const regionRaw = document.getElementById("export-region-input").value.trim();
    const regionPriority = regionRaw ? regionRaw.split(",").map((s) => s.trim()).filter(Boolean) : [];

    // Save settings to config
    fetchJson("/api/config/export-settings/" + encodeURIComponent(currentSystem), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            dest,
            rom_only: romOnly,
            one_game_one_rom: oneGame,
            archive_format: use7z ? "7z" : "zip",
            region_priority: regionRaw,
        }),
    }).catch(() => {});

    // Build candidate items from pending rows
    const candidates = _pendingQueueRows
        .filter((r) => r.file_name)
        .map((r) => ({
            system: currentSystem,
            file_name: r.file_name,
            game_name: r.game_name || r.description || "",
            plan: r.plan || "",
            note: r.note || "",
        }));

    // Deduplicate against already-queued items (by file_name + system)
    const newItems = candidates.filter(
        (c) => !exportQueue.some((q) => q.file_name === c.file_name && q.system === c.system)
    );

    // One-game-one-ROM deduplication
    const conflicts = [];
    let finalItems = newItems;
    if (oneGame) {
        // Merge new items with existing same-system queue entries for conflict detection
        const existing = exportQueue.filter((q) => q.system === currentSystem);
        const pool = [...existing, ...newItems];

        // Group pool by game_name
        const byGame = {};
        for (const item of pool) {
            const key = item.game_name || item.file_name;
            byGame[key] = byGame[key] || [];
            byGame[key].push(item);
        }

        // Pick winner for each game group using region priority
        const winners = new Set();
        for (const [game, items] of Object.entries(byGame)) {
            if (items.length <= 1) {
                winners.add(items[0].file_name);
                continue;
            }
            // Score each item by first matching region in priority list
            const scored = items.map((item) => {
                const name = item.game_name || item.file_name;
                const idx = regionPriority.findIndex((r) => name.toLowerCase().includes(r.toLowerCase()));
                return { item, score: idx === -1 ? regionPriority.length : idx };
            });
            scored.sort((a, b) => a.score - b.score);
            const winner = scored[0].item;
            winners.add(winner.file_name);
            for (const { item } of scored.slice(1)) {
                if (newItems.some((n) => n.file_name === item.file_name)) {
                    conflicts.push({ kept: winner.game_name || winner.file_name, dropped: item.game_name || item.file_name });
                }
            }
        }

        // Remove existing queue entries that lost
        for (let i = exportQueue.length - 1; i >= 0; i--) {
            if (exportQueue[i].system === currentSystem && !winners.has(exportQueue[i].file_name)) {
                exportQueue.splice(i, 1);
            }
        }
        // Only add new items that won
        finalItems = newItems.filter((item) => winners.has(item.file_name));
    }

    if (conflicts.length > 0) {
        const notice = document.getElementById("export-conflict-notice");
        notice.textContent = conflicts.map(
            (c) => "Kept \"" + c.kept + "\", dropped \"" + c.dropped + "\""
        ).join("\n");
        notice.hidden = false;
        // Keep modal open so user sees the conflict summary
        exportQueue.push(...finalItems);
        updateQueueButton();
        document.getElementById("export-settings-confirm").textContent = "Close";
        document.getElementById("export-settings-confirm").onclick = () => {
            Modal.close("export-settings-modal");
            // Reset button
            document.getElementById("export-settings-confirm").onclick = null;
        };
        return;
    }

    // Snapshot the settings for this system at queue-add time
    exportSystemSettings[currentSystem] = {
        dest,
        rom_only: romOnly,
        archive_format: use7z ? "7z" : "zip",
        region_priority: regionRaw,
    };

    exportQueue.push(...finalItems);
    _pendingQueueRows = [];
    updateQueueButton();
    Modal.close("export-settings-modal");

    // Refresh the analysis panel if it's showing one of the just-queued files
    if (_currentAnalysisRow && finalItems.some((i) => i.file_name === _currentAnalysisRow.file_name)) {
        showRomAnalysis(_currentAnalysisRow, "export");
    }

    const added = finalItems.length;
    setStatus(added > 0
        ? "Added " + added + " item(s) to queue (" + exportQueue.length + " total)"
        : "Items already in queue");
});

function updateQueueButton() {
    /** Show/hide the queue toolbar button with count badge. */
    const btn = document.getElementById("btn-queue");
    if (exportQueue.length > 0) {
        btn.hidden = false;
        btn.textContent = "Queue (" + exportQueue.length + ")";
    } else {
        btn.hidden = true;
        btn.textContent = "Queue";
    }
}

function showQueue() {
    /** Show the queue in the verify panel. */
    const verifyPanel = document.getElementById("verify-panel");
    const verifyLog = document.getElementById("verify-log");
    const header = verifyPanel.querySelector("#verify-panel-header strong");
    verifyPanel.hidden = false;
    verifyLog.innerHTML = "";
    header.textContent = "Export Queue (" + exportQueue.length + " items)";
    Resize.initVertical("resize-verify", "verify-panel");

    if (exportQueue.length === 0) {
        appendScanLogLine(verifyLog, "Queue is empty");
        return;
    }

    // Group by system
    const bySystem = {};
    for (const item of exportQueue) {
        bySystem[item.system] = bySystem[item.system] || [];
        bySystem[item.system].push(item);
    }

    for (const [system, items] of Object.entries(bySystem)) {
        const s = exportSystemSettings[system] || {};
        const fmt = s.archive_format === "7z" ? "7z" : "zip";
        const flags = [s.dest || "(no destination)", fmt, s.rom_only !== false ? "ROM only" : null].filter(Boolean);
        appendScanLogLine(verifyLog, "[blue]" + system + " — " + flags.join(" · ") + " (" + items.length + " item" + (items.length !== 1 ? "s" : "") + ")");
        for (const item of items) {
            const plan = item.plan ? " [" + item.plan + "]" : "";
            appendScanLogLine(verifyLog, "  " + item.game_name + plan);
        }
    }

    // Process and clear buttons
    const btnRow = document.createElement("div");
    btnRow.style.cssText = "display:flex;gap:0.5rem;padding:0.5rem;";
    const processBtn = document.createElement("button");
    processBtn.className = "outline";
    processBtn.textContent = "Process Queue";
    processBtn.style.cssText = "font-size:0.8rem;padding:0.25rem 0.75rem;margin:0;";
    processBtn.addEventListener("click", () => processQueue());
    const clearBtn = document.createElement("button");
    clearBtn.className = "outline secondary";
    clearBtn.textContent = "Clear Queue";
    clearBtn.style.cssText = "font-size:0.8rem;padding:0.25rem 0.75rem;margin:0;";
    clearBtn.addEventListener("click", () => {
        exportQueue.length = 0;
        for (const k of Object.keys(exportSystemSettings)) delete exportSystemSettings[k];
        updateQueueButton();
        showQueue();
    });
    btnRow.appendChild(processBtn);
    btnRow.appendChild(clearBtn);
    verifyLog.appendChild(btnRow);
}

async function pollUntilDone(verifyLog) {
    /** Poll /api/refresh/status until done, appending lines to verifyLog. */
    return new Promise((resolve, reject) => {
        let transientEl = null;
        const interval = setInterval(async () => {
            try {
                const status = await fetchJson("/api/refresh/status");
                for (const msg of status.messages) {
                    if (msg.transient) {
                        if (!transientEl) {
                            transientEl = document.createElement("div");
                            transientEl.className = "log-line log-progress";
                            verifyLog.appendChild(transientEl);
                        }
                        transientEl.textContent = msg.text.replace(/^\[(green|yellow|red|blue)\]/, "");
                    } else {
                        if (transientEl) { transientEl.remove(); transientEl = null; }
                        appendScanLogLine(verifyLog, msg.text);
                    }
                }
                verifyLog.scrollTop = verifyLog.scrollHeight;
                if (status.done) {
                    clearInterval(interval);
                    resolve();
                }
            } catch (e) {
                clearInterval(interval);
                reject(e);
            }
        }, 500);
    });
}

async function processQueue() {
    /** Export queued ROMs using the settings snapshot captured at queue-add time. */
    const verifyLog = document.getElementById("verify-log");

    // Group by system, preserving insertion order
    const bySystem = {};
    for (const item of exportQueue) {
        bySystem[item.system] = bySystem[item.system] || [];
        bySystem[item.system].push(item);
    }

    // Validate all systems have a destination in the snapshot
    for (const system of Object.keys(bySystem)) {
        const s = exportSystemSettings[system] || {};
        if (!s.dest || !s.dest.trim()) {
            verifyLog.innerHTML = "";
            appendScanLogLine(verifyLog, "[red]No export destination set for " + system + " — use Add to Queue to configure");
            return;
        }
    }

    verifyLog.innerHTML = "";
    appendScanLogLine(verifyLog, "[blue]Exporting " + exportQueue.length + " item(s)...");

    for (const [system, items] of Object.entries(bySystem)) {
        const s = exportSystemSettings[system] || {};
        const dest = s.dest || "";
        const regionPriority = s.region_priority
            ? s.region_priority.split(",").map((r) => r.trim()).filter(Boolean)
            : [];
        const archiveFormat = s.archive_format || "zip";
        const romOnly = s.rom_only !== false;
        const files = items.map((i) => i.file_name);

        appendScanLogLine(verifyLog, "[blue]" + system + " → " + dest);
        try {
            const start = await fetchJson("/api/export/" + encodeURIComponent(system), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    files, dest,
                    region_priority: regionPriority,
                    archive_format: archiveFormat,
                    rom_only: romOnly,
                }),
            });
            if (start.status === "already_running") {
                appendScanLogLine(verifyLog, "[red]A task is already running — please wait and try again");
                return;
            }
            await pollUntilDone(verifyLog);
        } catch (e) {
            appendScanLogLine(verifyLog, "[red]Error: " + e.message);
            return;
        }
    }

    exportQueue.length = 0;
    for (const k of Object.keys(exportSystemSettings)) delete exportSystemSettings[k];
    updateQueueButton();
}

// Queue toolbar button
document.getElementById("btn-queue").addEventListener("click", () => showQueue());

function _fmtSize(bytes) {
    if (!bytes) return "0 B";
    const units = ["B", "KB", "MB", "GB"];
    let i = 0;
    let n = bytes;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return (i === 0 ? n : n.toFixed(1)) + " " + units[i];
}

async function showRomAnalysis(row, activeTab = "data") {
    /** Show ROM analysis Data/Logs/Export tabs in the verify panel. */
    _currentAnalysisRow = row;
    const verifyPanel = document.getElementById("verify-panel");
    const verifyLog = document.getElementById("verify-log");
    const header = verifyPanel.querySelector("#verify-panel-header strong");

    header.textContent = row.file_name || "ROM Analysis";
    verifyPanel.hidden = false;
    verifyLog.innerHTML = '<div class="ra-panel-view"><p style="color:var(--pico-muted-color)">Loading…</p></div>';
    Resize.initVertical("resize-verify", "verify-panel");

    let data;
    try {
        data = await fetchJson(
            "/api/rom-details/" + encodeURIComponent(currentSystem) +
            "?file=" + encodeURIComponent(row.file_name)
        );
    } catch (e) {
        verifyLog.innerHTML = '<div class="ra-panel-view"><p style="color:var(--pico-del-color)">' + e.message + "</p></div>";
        return;
    }

    // ── Tab scaffold ────────────────────────────────────────────────────────
    const wrapper = document.createElement("div");
    wrapper.className = "ra-panel-view";
    const frag = document.createDocumentFragment();
    const tabBar = document.createElement("div");
    tabBar.className = "ra-tabs";
    const panes = {};

    for (const [id, label] of [["data", "Data"], ["logs", "Logs"], ["export", "Export plan"]]) {
        const btn = document.createElement("button");
        btn.className = "ra-tab" + (id === activeTab ? " active" : "");
        btn.textContent = label;
        btn.addEventListener("click", () => {
            tabBar.querySelectorAll(".ra-tab").forEach(b => b.classList.toggle("active", b === btn));
            Object.entries(panes).forEach(([k, p]) => { p.hidden = k !== id; });
        });
        tabBar.appendChild(btn);
        const pane = document.createElement("div");
        pane.className = "ra-tab-pane";
        pane.hidden = id !== activeTab;
        panes[id] = pane;
    }
    frag.appendChild(tabBar);
    for (const pane of Object.values(panes)) frag.appendChild(pane);

    // ── Data tab ────────────────────────────────────────────────────────────
    const meta = document.createElement("div");
    meta.className = "rom-analysis-meta";
    const containerLabel = data.compressed
        ? (data.file_type || "archive").toUpperCase() + " archive"
        : (data.file_type || "—");
    for (const [lbl, val] of [
        ["File", data.file_name],
        ["Container", containerLabel],
        ["ROM format", data.rom_type || "—"],
        ["Size", _fmtSize(data.size)],
        ["On disk", data.exists ? "Yes" : "Not found"],
    ]) {
        const span = document.createElement("span");
        span.innerHTML = "<strong>" + lbl + ":</strong> " + val;
        meta.appendChild(span);
    }
    panes.data.appendChild(meta);

    if (data.file_type === "zip" || data.file_type === "7z") {
        const sec = document.createElement("div");
        sec.className = "rom-analysis-section";
        const h = document.createElement("h6");
        h.textContent = "Archive contents (" + data.embedded.length + " file" + (data.embedded.length === 1 ? "" : "s") + ")";
        sec.appendChild(h);
        if (data.archive_error) {
            const p = document.createElement("p");
            p.style.color = "var(--pico-del-color)";
            p.textContent = data.archive_error;
            sec.appendChild(p);
        } else if (data.embedded.length === 0) {
            const p = document.createElement("p");
            p.style.color = "var(--pico-muted-color)";
            p.textContent = "Empty archive.";
            sec.appendChild(p);
        } else {
            const table = document.createElement("table");
            table.className = "rom-analysis-table";
            table.innerHTML = "<thead><tr><th>Name</th><th>Type</th><th>Size</th><th>Compressed</th><th>CRC</th></tr></thead>";
            const tbody = document.createElement("tbody");
            const romExts = new Set(["z64","v64","n64","sfc","smc","nes","gba","gbc","gb","md","smd","bin","iso","chd","cue","img","cdi"]);
            const sorted = [...data.embedded].sort((a, b) => (romExts.has(a.type) ? 0 : 1) - (romExts.has(b.type) ? 0 : 1));
            for (const f of sorted) {
                const tr = document.createElement("tr");
                if (romExts.has(f.type)) tr.className = "primary-file";
                tr.innerHTML =
                    "<td>" + f.name + "</td>" +
                    '<td class="type-badge">' + (f.type || "—") + "</td>" +
                    "<td>" + _fmtSize(f.size) + "</td>" +
                    "<td>" + _fmtSize(f.compress_size) + "</td>" +
                    '<td class="crc">' + f.crc + "</td>";
                tbody.appendChild(tr);
            }
            table.appendChild(tbody);
            sec.appendChild(table);
        }
        panes.data.appendChild(sec);
    }

    if (data.db_rows && data.db_rows.length > 0) {
        const sec = document.createElement("div");
        sec.className = "rom-analysis-section";
        const h = document.createElement("h6");
        h.textContent = "DAT match candidates (" + data.db_rows.length + ")";
        sec.appendChild(h);
        const table = document.createElement("table");
        table.className = "rom-analysis-table";
        table.innerHTML = "<thead><tr><th>Game</th><th>Status</th><th>Plan</th><th>Note</th></tr></thead>";
        const tbody = document.createElement("tbody");
        for (const r of data.db_rows) {
            const tr = document.createElement("tr");
            tr.innerHTML =
                "<td>" + (r.description || r.game_name) + "</td>" +
                "<td>" + (r.status || "—") + "</td>" +
                "<td>" + (r.plan || "—") + "</td>" +
                "<td>" + (r.note || "—") + "</td>";
            tbody.appendChild(tr);
        }
        table.appendChild(tbody);
        sec.appendChild(table);
        panes.data.appendChild(sec);
    }

    // ── Logs tab ────────────────────────────────────────────────────────────
    if (data.log && data.log.trim()) {
        const logContainer = document.createElement("div");
        logContainer.style.fontSize = "0.78rem";
        for (const line of data.log.split("\n")) {
            appendScanLogLine(logContainer, line);
        }
        panes.logs.appendChild(logContainer);
    } else {
        const p = document.createElement("p");
        p.style.color = "var(--pico-muted-color)";
        p.textContent = "No analysis log available. Run analysis to populate this tab.";
        panes.logs.appendChild(p);
    }

    // ── Export tab ──────────────────────────────────────────────────────────
    const inQueue = exportQueue.some(
        (q) => q.file_name === row.file_name && q.system === currentSystem
    );

    // Use the settings snapshot captured at queue-add time
    const exportSettings = inQueue ? (exportSystemSettings[currentSystem] || {}) : {};

    if (data.export_steps && data.export_steps.length > 0) {
        const callout = document.createElement("div");
        callout.className = "ra-callout";
        if (inQueue) {
            const dest = exportSettings.dest || "(no destination set)";
            const fmt = exportSettings.archive_format === "7z" ? "7z" : "zip";
            const romOnly = exportSettings.rom_only !== false;
            callout.innerHTML =
                '<span class="ra-callout-icon">&#10003;</span>' +
                '<div class="ra-callout-body">' +
                '<strong>Queued</strong>' +
                'Destination: ' + esc(dest) + ' &nbsp;&bull;&nbsp; Format: ' + fmt +
                (romOnly ? ' &nbsp;&bull;&nbsp; ROM only' : '') +
                '</div>';
            callout.style.borderLeftColor = "var(--pico-ins-color, #4caf50)";
            callout.style.background = "color-mix(in srgb, var(--pico-ins-color, #4caf50) 10%, var(--pico-card-background-color, transparent))";
        } else {
            callout.innerHTML =
                '<span class="ra-callout-icon">&#9432;</span>' +
                '<div class="ra-callout-body">' +
                '<strong>Auto-generated plan</strong>' +
                'Steps shown are based on analysis only. Click \u201cAdd to Queue\u201d to configure destination, format, and region settings before exporting.' +
                '</div>';
        }
        panes.export.appendChild(callout);

        // Filter steps based on settings when queued
        let steps = data.export_steps;
        const romOnly = exportSettings.rom_only !== false;
        const use7z = exportSettings.archive_format === "7z";
        if (inQueue && !romOnly) {
            steps = steps.filter((s) => s.name !== "remove_embedded");
        }

        const sec = document.createElement("div");
        sec.className = "rom-analysis-section";
        const h = document.createElement("h6");
        h.textContent = data.export_target
            ? (use7z && inQueue ? data.export_target.replace(/\.zip$/, ".7z") : data.export_target)
            : "Export plan";
        sec.appendChild(h);
        const table = document.createElement("table");
        table.className = "rom-analysis-table";
        table.innerHTML = "<thead><tr><th>Step</th><th>Description</th></tr></thead>";
        const tbody = document.createElement("tbody");
        for (const step of steps) {
            const tr = document.createElement("tr");
            let desc = step.description;
            if (inQueue && use7z && step.name === "compress_package") {
                desc = desc.replace(/\.zip\b/g, ".7z");
            }
            tr.innerHTML =
                '<td class="type-badge">' + step.name + "</td>" +
                "<td>" + esc(desc) + "</td>";
            tbody.appendChild(tr);
        }
        table.appendChild(tbody);
        sec.appendChild(table);
        panes.export.appendChild(sec);
    } else {
        const p = document.createElement("p");
        p.style.color = "var(--pico-muted-color)";
        p.textContent = data.db_rows && data.db_rows.length > 0
            ? "No export steps needed."
            : "Run analysis first to generate an export plan.";
        panes.export.appendChild(p);
    }

    wrapper.appendChild(frag);
    verifyLog.innerHTML = "";
    verifyLog.appendChild(wrapper);
}

function showExportPlan(row) {
    /** Show the export plan for a ROM in the verify log panel. */
    const verifyPanel = document.getElementById("verify-panel");
    const verifyLog = document.getElementById("verify-log");
    verifyPanel.hidden = false;
    verifyLog.innerHTML = "";
    Resize.initVertical("resize-verify", "verify-panel");

    appendScanLogLine(verifyLog, "[blue]Export plan for: " + row.file_name);
    appendScanLogLine(verifyLog, "  Game: " + row.description);
    appendScanLogLine(verifyLog, "  Status: " + row.status);
    if (row.note) {
        appendScanLogLine(verifyLog, "  Note: " + row.note);
    }
    appendScanLogLine(verifyLog, "");

    // Fetch fresh analysis for this specific file
    if (currentSystem) {
        fetchJson("/api/analyze/" + encodeURIComponent(currentSystem), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ files: [row.file_name] }),
        }).then((data) => {
            for (const result of data.results) {
                if (result.export_plan) {
                    appendScanLogLine(verifyLog, "[blue]Export plan → " + result.export_plan.target_name);
                    for (const step of result.export_plan.steps) {
                        appendScanLogLine(verifyLog, "  " + step.name + ": " + step.description);
                    }
                }
                for (const s of result.suggestions) {
                    if (s.crc_match === true) {
                        appendScanLogLine(verifyLog, "[green]  ✓ Matched: " + s.dat_game_name);
                    }
                }
            }
        }).catch((e) => {
            appendScanLogLine(verifyLog, "[red]Error: " + e.message);
        });
    }
}

const gameGrid = new DataGrid("game-grid", {
    columns: [
        { key: "description", label: "Game", width: 250, autoWidth: true, maxAutoWidth: 400, minChars: 30 },
        { key: "status", label: "Status", width: 100, autoWidth: true, minChars: 5, align: "center" },
        { key: "rom_type", label: "Type", width: 55, align: "center" },
        { key: "file_name", label: "File name", width: 300, minChars: 20 },
        { key: "plan", label: "Plan", width: 80, align: "center", render: renderPlanCell },
        { key: "note", label: "Note", width: 300, minChars: 15 },
    ],
    rowClassFn: (row) => {
        const classes = [];
        if (row.status && row.status !== "-") classes.push("status-" + row.status);
        if (row.plan === "exclude") classes.push("plan-row-exclude");
        return classes.join(" ") || null;
    },
    onContextMenu: (rows) => {
        const items = [];
        // "View analysis" only makes sense for a single file row
        if (rows.length === 1 && rows[0].file_name) {
            items.push({
                label: "View analysis",
                action: (rows) => showRomAnalysis(rows[0]),
            });
        }
        items.push({
            label: "Add to Queue",
            action: (rows) => addToQueue(rows),
        });
        items.push({
            label: "Exclude",
            action: (rows) => setRowPlan(rows, "exclude"),
        });
        // Allow clearing the plan
        if (rows.some((r) => r.plan)) {
            items.push({
                label: "Clear plan",
                action: (rows) => setRowPlan(rows, ""),
            });
        }
        return items;
    },
});

function updateStatusSummary(results) {
    /** Update the status badge counts in the header. */
    const counts = { ok: 0, unverified: 0, missing: 0, bad_dump: 0, other: 0 };
    for (const g of results) {
        if (g.status === "ok") counts.ok++;
        else if (g.status === "unverified") counts.unverified++;
        else if (g.status === "missing") counts.missing++;
        else if (g.status === "bad_dump") counts.bad_dump++;
        else counts.other++;
    }
    const el = document.getElementById("status-summary");
    let html = "";
    if (counts.ok > 0) html += '<span class="status-badge ok" title="Verified (CRC match)">' + counts.ok + "</span>";
    if (counts.unverified > 0) html += '<span class="status-badge unverified" title="Unverified (filename match)">' + counts.unverified + "</span>";
    if (counts.missing > 0) html += '<span class="status-badge missing" title="Missing">' + counts.missing + "</span>";
    if (counts.bad_dump > 0) html += '<span class="status-badge bad" title="Bad dump">' + counts.bad_dump + "</span>";
    if (counts.other > 0) html += '<span class="status-badge mismatch" title="Mismatch">' + counts.other + "</span>";
    el.innerHTML = html;
}

// --- Refresh ---

document.getElementById("btn-sync").addEventListener("click", () => {
    const fetchOpts = currentSystem ? {
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ system_name: currentSystem }),
    } : {};
    const title = currentSystem ? `Syncing ${currentSystem}...` : "Pre-scanning...";
    startBackgroundTask("/api/refresh", title, async () => {
        await loadWelcome();
        await loadSystems();
        if (currentSystem) await selectSystem(currentSystem);
    }, fetchOpts);
});

document.getElementById("confirm-sync-yes").addEventListener("click", () => {
    Modal.close("confirm-sync-modal");
    Modal.close("settings-modal");
    document.getElementById("btn-sync").click();
});

document.getElementById("confirm-sync-no").addEventListener("click", () => {
    Modal.close("confirm-sync-modal");
});

/**
 * Start a background task (pre-scan or CRC scan), show log, poll for progress.
 * @param {string} url - POST endpoint to start the task
 * @param {string} title - Title for the log view
 * @param {Function} onDone - Callback when task completes
 */
async function startBackgroundTask(url, title, onDone, fetchOpts = {}) {
    const btn = document.getElementById("btn-sync");
    btn.disabled = true;
    setStatus(title);

    document.getElementById("scan-progress-li").hidden = false;
    document.getElementById("last-scan-li").hidden = true;

    showView("scan-log");
    document.getElementById("scan-log-title").textContent = title;
    const logEl = document.getElementById("scan-log");
    logEl.innerHTML = "";

    try {
        const start = await fetchJson(url, { method: "POST", ...fetchOpts });
        if (start.status === "already_running") {
            setStatus("A task is already in progress");
            btn.disabled = false;
            return;
        }
    } catch (e) {
        setStatus("Error: " + e.message);
        btn.disabled = false;
        return;
    }

    // Poll for progress
    let transientEl = null;
    const pollInterval = setInterval(async () => {
        try {
            const status = await fetchJson("/api/refresh/status");
            for (const msg of status.messages) {
                if (msg.transient) {
                    if (!transientEl) {
                        transientEl = document.createElement("div");
                        transientEl.className = "log-line log-progress";
                        logEl.appendChild(transientEl);
                    }
                    transientEl.textContent = msg.text;
                } else {
                    if (transientEl) {
                        transientEl.remove();
                        transientEl = null;
                    }
                    appendScanLogLine(logEl, msg.text);
                    setStatus(msg.text);
                }
            }
            logEl.scrollTop = logEl.scrollHeight;

            if (status.done) {
                clearInterval(pollInterval);
                if (status.timestamp) updateLastScanTime(status.timestamp);
                document.getElementById("scan-log-title").textContent = "Complete";
                btn.disabled = false;
                document.getElementById("scan-progress-li").hidden = true;
                document.getElementById("last-scan-li").hidden = false;
                if (onDone) await onDone();
            }
        } catch (e) {
            clearInterval(pollInterval);
            setStatus("Poll error: " + e.message);
            btn.disabled = false;
            document.getElementById("scan-progress-li").hidden = true;
            document.getElementById("last-scan-li").hidden = false;
        }
    }, 500);
}

// --- Settings & Add Path modals ---

let addpathMode = "dat";

document.getElementById("btn-settings").addEventListener("click", async () => {
    await loadSettingsPaths();
    await loadSettingsGeneral();
    await loadSettingsSaves();
    Modal.open("settings-modal");
});

// Settings tab navigation
document.querySelectorAll(".settings-nav-item").forEach((item) => {
    item.addEventListener("click", () => {
        document.querySelectorAll(".settings-nav-item").forEach((el) => el.classList.remove("active"));
        document.querySelectorAll(".settings-panel").forEach((el) => el.classList.remove("active"));
        item.classList.add("active");
        const panel = document.getElementById("settings-" + item.dataset.panel);
        if (panel) panel.classList.add("active");
    });
});

// Refresh welcome stats when settings closes
const settingsEl = document.getElementById("settings-modal");
new MutationObserver(() => {
    if (!settingsEl.classList.contains("is-open")) {
        loadWelcome();
    }
}).observe(settingsEl, { attributes: true, attributeFilter: ["class"] });

// --- Theme ---

function applyTheme(theme) {
    if (theme === "auto") {
        const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
        document.documentElement.dataset.theme = dark ? "dark" : "light";
    } else {
        document.documentElement.dataset.theme = theme;
    }
}

// Listen for OS theme changes when in auto mode
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", async () => {
    try {
        const { theme } = await fetchJson("/api/config/theme");
        if (theme === "auto") applyTheme("auto");
    } catch (_) {}
});

// Load and apply theme on page load
(async () => {
    try {
        const { theme } = await fetchJson("/api/config/theme");
        applyTheme(theme);
    } catch (_) {}
})();

async function loadSettingsGeneral() {
    try {
        const { theme } = await fetchJson("/api/config/theme");
        const radio = document.querySelector('input[name="theme"][value="' + theme + '"]');
        if (radio) radio.checked = true;
    } catch (_) {}
    try {
        const { path } = await fetchJson("/api/config/path");
        const link = document.getElementById("config-path-link");
        if (link) {
            link.textContent = path;
            link.dataset.path = path;
        }
    } catch (_) {}
}

document.getElementById("theme-fieldset").addEventListener("change", async (e) => {
    const theme = e.target.value;
    try {
        await fetchJson("/api/config/theme", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ theme }),
        });
        applyTheme(theme);
    } catch (_) {}
});

// --- Saves path ---

async function loadSettingsSaves() {
    try {
        const { path } = await fetchJson("/api/config/saves-path");
        document.getElementById("saves-path-input").value = path || "";
    } catch (_) {}
}

document.getElementById("btn-save-saves-path").addEventListener("click", async () => {
    const path = document.getElementById("saves-path-input").value.trim();
    try {
        await fetchJson("/api/config/saves-path", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path }),
        });
        setStatus("Saves path updated");
    } catch (e) {
        setStatus("Error: " + e.message);
    }
});

document.getElementById("btn-add-dat-path").addEventListener("click", () => {
    addpathMode = "dat";
    document.getElementById("addpath-title").textContent = "Add DAT Path";
    document.getElementById("addpath-form").reset();
    Modal.open("addpath-modal");
});

document.getElementById("btn-add-rom-path").addEventListener("click", () => {
    addpathMode = "rom";
    document.getElementById("addpath-title").textContent = "Add ROM Path";
    document.getElementById("addpath-form").reset();
    Modal.open("addpath-modal");
});

document.getElementById("addpath-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const path = document.getElementById("addpath-path").value.trim();

    if (addpathMode === "dat") {
        try {
            setStatus("Scanning DAT directory...");
            const added = await fetchJson("/api/dats/paths", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ path }),
            });
            Modal.close("addpath-modal");
            await loadSettingsPaths();
            setStatus("Added " + added.length + " DAT file(s)");
            if (added.length > 0) {
                Modal.open("confirm-sync-modal");
            }
        } catch (err) {
            setStatus("Error: " + err.message);
        }
    } else {
        try {
            setStatus("Scanning ROM directories...");
            const added = await fetchJson("/api/roms/paths", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ path, system: "" }),
            });
            Modal.close("addpath-modal");
            await loadSettingsPaths();
            await loadSystems();
            setStatus("Added " + added.length + " ROM path(s)");
        } catch (err) {
            setStatus("Error: " + err.message);
        }
    }
});

async function loadSettingsPaths() {
    // Load DAT paths
    try {
        const datPaths = await fetchJson("/api/dats/paths");
        const datList = document.getElementById("dat-paths-list");
        datList.innerHTML = "";
        for (const dp of datPaths) {
            const li = document.createElement("li");
            const fileName = dp.path.split("/").pop();
            li.innerHTML =
                '<div class="path-entry"><strong>' + esc(dp.system) + '</strong>' +
                '<a href="#" class="path-link" data-path="' + esc(dp.path) + '">' + esc(fileName) + '</a></div>';
            const btn = document.createElement("button");
            btn.classList.add("outline", "secondary");
            btn.textContent = "Remove";
            btn.addEventListener("click", async () => {
                await fetchJson("/api/dats/paths", {
                    method: "DELETE",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ path: dp.path, system: dp.system }),
                });
                await loadSettingsPaths();
            });
            li.appendChild(btn);
            datList.appendChild(li);
        }
        if (datPaths.length === 0) {
            datList.innerHTML = "<li><em>No DAT paths configured.</em></li>";
        }
    } catch (e) {
        setStatus("Error loading DAT paths: " + e.message);
    }

    // Load ROM paths
    try {
        const romPaths = await fetchJson("/api/roms/paths");
        const romList = document.getElementById("rom-paths-list");
        romList.innerHTML = "";
        for (const rp of romPaths) {
            const li = document.createElement("li");
            const dirName = rp.path.split("/").pop();
            li.innerHTML =
                '<div class="path-entry"><strong>' + esc(rp.system) + '</strong>' +
                '<a href="#" class="path-link" data-path="' + esc(rp.path) + '">' + esc(dirName) + '</a></div>';
            const btn = document.createElement("button");
            btn.classList.add("outline", "secondary");
            btn.textContent = "Remove";
            btn.addEventListener("click", async () => {
                await fetchJson("/api/roms/paths", {
                    method: "DELETE",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ path: rp.path, system: rp.system }),
                });
                await loadSettingsPaths();
            });
            li.appendChild(btn);
            romList.appendChild(li);
        }
        if (romPaths.length === 0) {
            romList.innerHTML = "<li><em>No ROM paths configured.</em></li>";
        }
    } catch (e) {
        setStatus("Error loading ROM paths: " + e.message);
    }
}

// --- Path links: open in system file manager ---
document.addEventListener("click", async (e) => {
    const link = e.target.closest(".path-link");
    if (!link) return;
    e.preventDefault();
    const path = link.dataset.path;
    try {
        await fetchJson("/api/open-path", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path }),
        });
    } catch (_) {
        // Ignore errors silently
    }
});

// --- Home button ---
document.getElementById("btn-home").addEventListener("click", (e) => {
    e.preventDefault();
    currentSystem = null;
    document.querySelectorAll("#system-tree li").forEach((li) => li.classList.remove("active"));
    showView("welcome");
    loadWelcome();
});

// --- Scan progress link -> show log view ---
document.getElementById("scan-progress-link").addEventListener("click", (e) => {
    e.preventDefault();
    showView("scan-log");
});

// --- Last scan time click -> show logs ---
document.getElementById("last-scan-time").addEventListener("click", async (e) => {
    e.preventDefault();
    const logEl = document.getElementById("scan-log");

    // If log is already populated (from current session), just show it
    if (logEl.children.length > 0) {
        showView("scan-log");
        document.getElementById("scan-log-title").textContent = "Last Sync Log";
        return;
    }

    // Otherwise fetch saved log from DB
    try {
        const data = await fetchJson("/api/scan-log");
        if (!data.log) return;
        logEl.innerHTML = "";
        for (const line of data.log.split("\n")) {
            appendScanLogLine(logEl, line);
        }
        document.getElementById("scan-log-title").textContent = "Last Sync Log";
        showView("scan-log");
    } catch (_) {
        // Ignore
    }
});

// --- Init ---
showView("welcome");
loadSystems();
loadWelcome();
