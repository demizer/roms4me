/** @type {string|null} */
let currentSystem = null;

const statusText = document.getElementById("status-text");

// --- Queue ---

/** @type {Array<{system: string, file_name: string, game_name: string, plan: string, note: string}>} */
const exportQueue = [];

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
        const exportBtn = document.getElementById("btn-add-queue");
        const deleteBtn = document.getElementById("btn-exclude");
        analyzeBtn.disabled = true;
        exportBtn.disabled = true;

        // Wire up analyze button
        analyzeBtn.onclick = () => startAnalysis(systemName);
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
            analyzeBtn.disabled = n === 0;
            analyzeBtn.textContent = n > 0 ? "Analyze (" + n + ")" : "Analyze";
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

function addToQueue(rows) {
    /** Add selected rows to the export queue. */
    let added = 0;
    for (const row of rows) {
        if (!row.file_name) continue;
        // Avoid duplicates by file_name + system
        const exists = exportQueue.some(
            (q) => q.file_name === row.file_name && q.system === currentSystem
        );
        if (!exists) {
            exportQueue.push({
                system: currentSystem,
                file_name: row.file_name,
                game_name: row.game_name || row.description || "",
                plan: row.plan || "",
                note: row.note || "",
            });
            added++;
        }
    }
    updateQueueButton();
    if (added > 0) {
        setStatus("Added " + added + " item(s) to queue (" + exportQueue.length + " total)");
    } else {
        setStatus("Items already in queue");
    }
}

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
        appendScanLogLine(verifyLog, "[blue]" + system + " (" + items.length + " items)");
        for (const item of items) {
            const plan = item.plan ? " [" + item.plan + "]" : "";
            appendScanLogLine(verifyLog, "  " + item.game_name + plan);
        }
    }

    // Region priority input
    const regionRow = document.createElement("div");
    regionRow.style.cssText = "display:flex;gap:0.5rem;padding:0.5rem 0.5rem 0;align-items:center;";
    const regionLabel = document.createElement("label");
    regionLabel.textContent = "Region priority:";
    regionLabel.style.cssText = "font-size:0.8rem;white-space:nowrap;margin:0;";
    const regionInput = document.createElement("input");
    regionInput.type = "text";
    regionInput.value = "USA, World, Europe, Japan";
    regionInput.placeholder = "USA, World, Europe, Japan";
    regionInput.title = "When multiple versions of the same game are queued, prefer this region order. Leave blank to export all.";
    regionInput.style.cssText = "font-size:0.8rem;padding:0.2rem 0.4rem;margin:0;flex:1;";
    regionRow.appendChild(regionLabel);
    regionRow.appendChild(regionInput);
    verifyLog.appendChild(regionRow);

    // Destination path input
    const destRow = document.createElement("div");
    destRow.style.cssText = "display:flex;gap:0.5rem;padding:0.5rem 0.5rem 0;align-items:center;";
    const destLabel = document.createElement("label");
    destLabel.textContent = "Export to:";
    destLabel.style.cssText = "font-size:0.8rem;white-space:nowrap;margin:0;";
    const destInput = document.createElement("input");
    destInput.type = "text";
    destInput.placeholder = "/media/user/sdcard/Nintendo - SNES";
    destInput.style.cssText = "font-size:0.8rem;padding:0.2rem 0.4rem;margin:0;flex:1;";
    destRow.appendChild(destLabel);
    destRow.appendChild(destInput);
    verifyLog.appendChild(destRow);

    // Process and clear buttons
    const btnRow = document.createElement("div");
    btnRow.style.cssText = "display:flex;gap:0.5rem;padding:0.5rem;";
    const processBtn = document.createElement("button");
    processBtn.className = "outline";
    processBtn.textContent = "Process Queue";
    processBtn.style.cssText = "font-size:0.8rem;padding:0.25rem 0.75rem;margin:0;";
    processBtn.addEventListener("click", () => {
        const regionPriority = regionInput.value.trim()
            ? regionInput.value.split(",").map((s) => s.trim()).filter(Boolean)
            : [];
        processQueue(destInput.value.trim(), regionPriority);
    });
    const clearBtn = document.createElement("button");
    clearBtn.className = "outline secondary";
    clearBtn.textContent = "Clear Queue";
    clearBtn.style.cssText = "font-size:0.8rem;padding:0.25rem 0.75rem;margin:0;";
    clearBtn.addEventListener("click", () => {
        exportQueue.length = 0;
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

async function processQueue(dest, regionPriority = []) {
    /** Export queued ROMs to dest — calls /api/export per system. */
    const verifyLog = document.getElementById("verify-log");

    if (!dest) {
        verifyLog.innerHTML = "";
        appendScanLogLine(verifyLog, "[red]Please enter a destination path");
        return;
    }

    verifyLog.innerHTML = "";
    appendScanLogLine(verifyLog, "[blue]Exporting " + exportQueue.length + " item(s) to " + dest + "...");

    // Group by system, preserving insertion order
    const bySystem = {};
    for (const item of exportQueue) {
        bySystem[item.system] = bySystem[item.system] || [];
        bySystem[item.system].push(item);
    }

    for (const [system, items] of Object.entries(bySystem)) {
        const files = items.map((i) => i.file_name);
        try {
            const start = await fetchJson("/api/export/" + encodeURIComponent(system), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ files, dest, region_priority: regionPriority }),
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

async function showRomAnalysis(row) {
    /** Open the ROM analysis modal with Data / Logs / Export tabs. */
    const titleEl = document.getElementById("rom-analysis-title");
    const bodyEl = document.getElementById("rom-analysis-body");
    titleEl.textContent = row.file_name || "ROM Analysis";
    bodyEl.innerHTML = '<p style="color:var(--pico-muted-color)">Loading…</p>';
    Modal.open("rom-analysis-modal");

    let data;
    try {
        data = await fetchJson(
            "/api/rom-details/" + encodeURIComponent(currentSystem) +
            "?file=" + encodeURIComponent(row.file_name)
        );
    } catch (e) {
        bodyEl.innerHTML = '<p style="color:var(--pico-del-color)">' + e.message + "</p>";
        return;
    }

    // ── Tab scaffold ────────────────────────────────────────────────────────
    const frag = document.createDocumentFragment();
    const tabBar = document.createElement("div");
    tabBar.className = "ra-tabs";
    const panes = {};

    for (const [id, label] of [["data", "Data"], ["logs", "Logs"], ["export", "Export"]]) {
        const btn = document.createElement("button");
        btn.className = "ra-tab" + (id === "data" ? " active" : "");
        btn.textContent = label;
        btn.addEventListener("click", () => {
            tabBar.querySelectorAll(".ra-tab").forEach(b => b.classList.toggle("active", b === btn));
            Object.entries(panes).forEach(([k, p]) => { p.hidden = k !== id; });
        });
        tabBar.appendChild(btn);
        const pane = document.createElement("div");
        pane.className = "ra-tab-pane";
        pane.hidden = id !== "data";
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
    const verifyLog = document.getElementById("verify-log");
    if (verifyLog && verifyLog.textContent.trim()) {
        const logClone = verifyLog.cloneNode(true);
        logClone.style.fontSize = "0.78rem";
        panes.logs.appendChild(logClone);
    } else {
        const p = document.createElement("p");
        p.style.color = "var(--pico-muted-color)";
        p.textContent = "No analysis log available. Run analysis to populate this tab.";
        panes.logs.appendChild(p);
    }

    // ── Export tab ──────────────────────────────────────────────────────────
    const exportLoading = document.createElement("p");
    exportLoading.style.color = "var(--pico-muted-color)";
    exportLoading.textContent = "Loading…";
    panes.export.appendChild(exportLoading);

    if (currentSystem) {
        fetchJson("/api/analyze/" + encodeURIComponent(currentSystem), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ files: [row.file_name] }),
        }).then((resp) => {
            panes.export.innerHTML = "";
            let hasSteps = false;
            for (const result of (resp.results || [])) {
                if (!result.export_plan || result.export_plan.steps.length === 0) continue;
                hasSteps = true;
                const sec = document.createElement("div");
                sec.className = "rom-analysis-section";
                const h = document.createElement("h6");
                h.textContent = result.export_plan.target_name;
                sec.appendChild(h);
                const table = document.createElement("table");
                table.className = "rom-analysis-table";
                table.innerHTML = "<thead><tr><th>Step</th><th>Description</th></tr></thead>";
                const tbody = document.createElement("tbody");
                for (const step of result.export_plan.steps) {
                    const tr = document.createElement("tr");
                    tr.innerHTML =
                        '<td class="type-badge">' + step.name + "</td>" +
                        "<td>" + step.description + "</td>";
                    tbody.appendChild(tr);
                }
                table.appendChild(tbody);
                sec.appendChild(table);
                panes.export.appendChild(sec);
            }
            if (!hasSteps) {
                const p = document.createElement("p");
                p.style.color = "var(--pico-muted-color)";
                p.textContent = "No export steps needed.";
                panes.export.appendChild(p);
            }
        }).catch((e) => {
            panes.export.innerHTML = '<p style="color:var(--pico-del-color)">Error: ' + e.message + "</p>";
        });
    } else {
        panes.export.innerHTML = '<p style="color:var(--pico-muted-color)">No system selected.</p>';
    }

    bodyEl.innerHTML = "";
    bodyEl.appendChild(frag);
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
