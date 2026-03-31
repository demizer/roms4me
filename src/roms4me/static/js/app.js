/** @type {string|null} */
let currentSystem = null;

const statusText = document.getElementById("status-text");

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
            document.getElementById("welcome-settings").addEventListener("click", async () => {
                await loadSettingsPaths();
                Modal.open("settings-modal");
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
        const exportBtn = document.getElementById("btn-add-queue");
        const deleteBtn = document.getElementById("btn-delete");
        analyzeBtn.disabled = true;
        exportBtn.disabled = true;

        // Wire up analyze button
        analyzeBtn.onclick = () => startAnalysis(systemName);
        deleteBtn.onclick = () => {
            const rows = gameGrid.getSelectedRows();
            if (rows.length > 0) setRowPlan(rows, "delete");
        };

        // Grid data — all rows, default filter hides "missing"
        gameGrid.filters = {};
        gameGrid.setData(resultData.rows);
        gameGrid.setFilter("status", new Set(["ok", "unverified", "unmatched", "matched"]));
        gameGrid.onSelectionChange = (selected) => {
            const n = selected.length;
            analyzeBtn.disabled = n === 0;
            analyzeBtn.textContent = n > 0 ? "Analyze (" + n + ")" : "Analyze";
            exportBtn.disabled = n === 0;
            exportBtn.textContent = n > 0 ? "Add to Queue (" + n + ")" : "Add to Queue";
            deleteBtn.hidden = n === 0;
            deleteBtn.textContent = "Delete (" + n + ")";
        };

        setStatus(systemName + " (" + resultData.owned_count + " owned, " + resultData.missing_count + " missing)");
    } catch (e) {
        setStatus("Error: " + e.message);
    }
}

// Close verify panel
document.getElementById("verify-panel-close").addEventListener("click", () => {
    document.getElementById("verify-panel").hidden = true;
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
    } else if (val === "delete") {
        td.textContent = "delete";
        td.classList.add("plan-delete");
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
        { key: "file_name", label: "File name", width: 300, minChars: 20 },
        { key: "plan", label: "Plan", width: 80, align: "center", render: renderPlanCell },
        { key: "note", label: "Note", width: 300, minChars: 15 },
    ],
    rowClassFn: (row) => {
        const classes = [];
        if (row.status && row.status !== "-") classes.push("status-" + row.status);
        if (row.plan === "delete") classes.push("plan-row-delete");
        return classes.join(" ") || null;
    },
    onContextMenu: (rows) => {
        const items = [];
        items.push({
            label: "Delete",
            action: (rows) => setRowPlan(rows, "delete"),
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
    startBackgroundTask("/api/refresh", "Pre-scanning...", async () => {
        await loadWelcome();
        await loadSystems();
        if (currentSystem) await selectSystem(currentSystem);
    });
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
async function startBackgroundTask(url, title, onDone) {
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
        const start = await fetchJson(url, { method: "POST" });
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
    Modal.open("settings-modal");
});

// Refresh welcome stats when settings closes
const settingsEl = document.getElementById("settings-modal");
new MutationObserver(() => {
    if (!settingsEl.classList.contains("is-open")) {
        loadWelcome();
    }
}).observe(settingsEl, { attributes: true, attributeFilter: ["class"] });

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
                await fetchJson("/api/dats/paths/" + dp.id, { method: "DELETE" });
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
                await fetchJson("/api/roms/paths/" + rp.id, { method: "DELETE" });
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
