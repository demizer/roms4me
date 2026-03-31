/**
 * DataGrid — full-featured HTML table component.
 *
 * Features:
 * - Proper <table> with table-layout: fixed
 * - Sticky header
 * - Click column header text → filter dialog with value checkboxes
 * - Click sort arrow → sort asc/desc
 * - Column resize via drag handle
 * - Selection column with checkboxes
 * - Ctrl+click, Shift+click multi-select
 * - Auto-width columns
 * - Row status class support
 */
class DataGrid {
    constructor(containerId, opts) {
        /** Initialize the DataGrid in the given container element. */
        this.container = document.getElementById(containerId);
        this.columns = opts.columns || [];
        this.allData = [];
        this.data = [];
        this.sortCol = null;
        this.sortDir = "asc";
        this.filters = {};       // key -> Set of allowed values (null = no filter)
        this.filterSearchText = {}; // key -> last search text in filter dialog
        this.selected = new Set();
        this.lastClickedIdx = null;
        this.onSelectionChange = null;
        this.onContextMenu = opts.onContextMenu || null;  // (rows, x, y) => [{label, action}]
        this.rowClassFn = opts.rowClassFn || null;
        this._ctxMenu = null;

        this.container.classList.add("dg");
        this.container.innerHTML = "";

        this.wrapperEl = document.createElement("div");
        this.wrapperEl.className = "dg-wrapper";
        this.container.appendChild(this.wrapperEl);

        this.tableEl = document.createElement("table");
        this.tableEl.className = "dg-table";
        this.wrapperEl.appendChild(this.tableEl);

        this.theadEl = document.createElement("thead");
        this.tableEl.appendChild(this.theadEl);

        this.tbodyEl = document.createElement("tbody");
        this.tableEl.appendChild(this.tbodyEl);

        this._renderHeader();
        this._bindEvents();
    }

    setData(data) {
        /** Set grid data, auto-fit columns, and render. */
        this.allData = data;
        this.selected.clear();
        this.lastClickedIdx = null;
        this._autoFitColumns();
        this._renderHeader();
        this._applyFiltersAndSort();
    }

    replaceRows(matchKey, matchValue, newRow) {
        /** Replace all rows where row[matchKey] === matchValue with a single newRow.
         *  Updates active filters to include new values so rows don't vanish.
         *  Does NOT re-render — call refresh() after a batch of updates. */
        let replaced = false;
        this.allData = this.allData.filter((r) => {
            if (r[matchKey] === matchValue) {
                if (!replaced) {
                    // Update filters: if old value was allowed, also allow new value
                    for (const key of Object.keys(this.filters)) {
                        const oldVal = String(r[key] ?? "");
                        const newVal = String(newRow[key] ?? "");
                        if (oldVal !== newVal && this.filters[key].has(oldVal)) {
                            this.filters[key].add(newVal);
                        }
                    }
                    Object.assign(r, newRow);
                    replaced = true;
                    return true;
                }
                return false;
            }
            return true;
        });
        if (!replaced) {
            // New row — add its values to any active filters
            for (const key of Object.keys(this.filters)) {
                this.filters[key].add(String(newRow[key] ?? ""));
            }
            this.allData.push(newRow);
        }
    }

    refresh() {
        /** Re-apply filters, sort, and render. Call after batch updates.
         *  Prunes stale filter values that no longer exist in the data. */
        this.selected.clear();
        this.lastClickedIdx = null;
        if (this._selectAllCheckbox) {
            this._selectAllCheckbox.checked = false;
            this._selectAllCheckbox.indeterminate = false;
        }
        // Prune filter values that no longer exist in the data
        for (const key of Object.keys(this.filters)) {
            const existing = new Set(this.allData.map((r) => String(r[key] ?? "")));
            for (const v of this.filters[key]) {
                if (!existing.has(v)) this.filters[key].delete(v);
            }
        }
        this._applyFiltersAndSort();
        if (this.onSelectionChange) this.onSelectionChange(this.getSelectedRows());
    }

    setFilter(key, allowedValues) {
        /** Set a filter on a column. allowedValues is a Set or null to clear. */
        if (allowedValues) {
            this.filters[key] = allowedValues;
        } else {
            delete this.filters[key];
        }
        this._updateFilterUI();
        this._applyFiltersAndSort();
    }

    getSelectedRows() {
        /** Return array of currently selected row objects. */
        return [...this.selected].map((i) => this.data[i]).filter(Boolean);
    }

    // ---- Header ----

    _renderHeader() {
        /** Render the table header row. */
        this.theadEl.innerHTML = "";
        const tr = document.createElement("tr");

        // Selection column
        const selTh = document.createElement("th");
        selTh.className = "dg-th dg-th-sel";
        const selAll = document.createElement("input");
        selAll.type = "checkbox";
        selAll.title = "Select all";
        selAll.addEventListener("change", () => {
            if (selAll.checked) {
                this.selected = new Set(this.data.map((_, i) => i));
            } else {
                this.selected.clear();
            }
            this._updateSelectionUI();
        });
        this._selectAllCheckbox = selAll;
        selTh.appendChild(selAll);
        tr.appendChild(selTh);

        // Data columns
        this.columns.forEach((col, colIdx) => {
            const th = document.createElement("th");
            th.className = "dg-th" + (col.align === "center" ? " dg-th-center" : "");
            th.style.width = col.width + "px";
            if (col.align) th.style.textAlign = col.align;

            // Inner wrapper for label + sort
            const inner = document.createElement("div");
            inner.className = "dg-th-inner";

            // Label (click → filter)
            const label = document.createElement("span");
            label.className = "dg-th-label";
            label.textContent = col.label;
            label.title = "Click to filter";
            label.addEventListener("click", (e) => {
                e.stopPropagation();
                this._showFilterDialog(col, colIdx, th);
            });
            inner.appendChild(label);

            // Filter indicator
            const filterDot = document.createElement("span");
            filterDot.className = "dg-th-filter-dot";
            inner.appendChild(filterDot);

            // Sort arrow — always visible, clickable
            const arrow = document.createElement("span");
            arrow.className = "dg-th-sort";
            arrow.textContent = "\u25B4\u25BE"; // ▴▾
            arrow.title = "Click to sort";
            arrow.addEventListener("click", (e) => {
                e.stopPropagation();
                this._toggleSort(colIdx);
            });
            inner.appendChild(arrow);

            th.appendChild(inner);

            // Resize handle — a real element on the right edge
            const grip = document.createElement("div");
            grip.className = "dg-resize-handle";
            grip.addEventListener("mousedown", (e) => {
                e.preventDefault();
                e.stopPropagation();
                this._startResize(th, col, e.clientX);
            });
            th.appendChild(grip);

            col._thEl = th;
            col._arrowEl = arrow;
            col._filterDotEl = filterDot;
            tr.appendChild(th);
        });

        this.theadEl.appendChild(tr);
        this._updateSortUI();
        this._updateFilterUI();
    }

    // ---- Body ----

    _renderBody() {
        /** Render table body rows from current filtered/sorted data. */
        this.tbodyEl.innerHTML = "";
        for (let r = 0; r < this.data.length; r++) {
            const row = this.data[r];
            const tr = document.createElement("tr");
            tr.className = "dg-row";
            tr.dataset.index = r;
            if (this.rowClassFn) {
                const cls = this.rowClassFn(row);
                if (cls) tr.classList.add(...cls.split(/\s+/).filter(Boolean));
            }
            if (this.selected.has(r)) tr.classList.add("dg-selected");

            // Selection checkbox
            const selTd = document.createElement("td");
            selTd.className = "dg-td dg-td-sel";
            const cb = document.createElement("input");
            cb.type = "checkbox";
            cb.checked = this.selected.has(r);
            cb.addEventListener("change", (e) => {
                e.stopPropagation();
                this._toggleRowSelection(r);
            });
            selTd.appendChild(cb);
            tr.appendChild(selTd);

            // Data cells
            for (const col of this.columns) {
                const td = document.createElement("td");
                td.className = "dg-td";
                td.style.width = col.width + "px";
                if (col.align) td.style.textAlign = col.align;
                const val = String(row[col.key] ?? "");
                if (col.render) {
                    col.render(td, val, row);
                } else {
                    td.textContent = val;
                }
                td.title = val;
                tr.appendChild(td);
            }

            this.tbodyEl.appendChild(tr);
        }
    }

    // ---- Events ----

    _bindEvents() {
        /** Bind click and context menu events on table body. */
        this.tbodyEl.addEventListener("click", (e) => {
            const tr = e.target.closest("tr.dg-row");
            if (!tr || e.target.tagName === "INPUT") return;
            const idx = parseInt(tr.dataset.index, 10);
            this._handleRowClick(idx, e);
        });

        this.tbodyEl.addEventListener("contextmenu", (e) => {
            if (!this.onContextMenu) return;
            const tr = e.target.closest("tr.dg-row");
            if (!tr) return;
            e.preventDefault();
            const idx = parseInt(tr.dataset.index, 10);
            // If right-clicked row is not selected, select only it
            if (!this.selected.has(idx)) {
                this.selected.clear();
                this.selected.add(idx);
                this.lastClickedIdx = idx;
                this._updateSelectionUI();
            }
            this._showContextMenu(e.clientX, e.clientY);
        });

        document.addEventListener("mousedown", (e) => {
            if (this._ctxMenu && !e.target.closest(".dg-context-menu")) {
                this._hideContextMenu();
            }
        });
    }

    _showContextMenu(x, y) {
        /** Show a context menu at the given coordinates. */
        this._hideContextMenu();
        const rows = this.getSelectedRows();
        if (rows.length === 0) return;
        const items = this.onContextMenu(rows, x, y);
        if (!items || items.length === 0) return;

        const menu = document.createElement("div");
        menu.className = "dg-context-menu";
        for (const item of items) {
            const el = document.createElement("div");
            el.className = "dg-context-item";
            el.textContent = item.label;
            el.addEventListener("click", (e) => {
                e.stopPropagation();
                this._hideContextMenu();
                item.action(rows);
            });
            menu.appendChild(el);
        }
        document.body.appendChild(menu);
        // Position, keeping within viewport
        const rect = menu.getBoundingClientRect();
        menu.style.left = Math.min(x, window.innerWidth - rect.width - 4) + "px";
        menu.style.top = Math.min(y, window.innerHeight - rect.height - 4) + "px";
        this._ctxMenu = menu;
    }

    _hideContextMenu() {
        if (this._ctxMenu) {
            this._ctxMenu.remove();
            this._ctxMenu = null;
        }
    }

    _handleRowClick(idx, e) {
        /** Handle row click with ctrl/shift/normal selection. */
        if (e.shiftKey && this.lastClickedIdx !== null) {
            const from = Math.min(this.lastClickedIdx, idx);
            const to = Math.max(this.lastClickedIdx, idx);
            if (!e.ctrlKey && !e.metaKey) this.selected.clear();
            for (let i = from; i <= to; i++) this.selected.add(i);
        } else if (e.ctrlKey || e.metaKey) {
            if (this.selected.has(idx)) this.selected.delete(idx);
            else this.selected.add(idx);
        } else {
            this.selected.clear();
            this.selected.add(idx);
        }
        this.lastClickedIdx = idx;
        this._updateSelectionUI();
    }

    _toggleRowSelection(idx) {
        /** Toggle row via checkbox. */
        if (this.selected.has(idx)) this.selected.delete(idx);
        else this.selected.add(idx);
        this._updateSelectionUI();
    }

    _updateSelectionUI() {
        /** Sync row highlights and checkboxes with this.selected. */
        this.tbodyEl.querySelectorAll("tr.dg-row").forEach((tr) => {
            const idx = parseInt(tr.dataset.index, 10);
            const sel = this.selected.has(idx);
            tr.classList.toggle("dg-selected", sel);
            const cb = tr.querySelector("input[type=checkbox]");
            if (cb) cb.checked = sel;
        });
        if (this._selectAllCheckbox) {
            this._selectAllCheckbox.checked =
                this.data.length > 0 && this.selected.size === this.data.length;
            this._selectAllCheckbox.indeterminate =
                this.selected.size > 0 && this.selected.size < this.data.length;
        }
        if (this.onSelectionChange) this.onSelectionChange(this.getSelectedRows());
    }

    // ---- Sort ----

    _toggleSort(colIdx) {
        /** Toggle sort direction on a column. */
        if (this.sortCol === colIdx) {
            this.sortDir = this.sortDir === "asc" ? "desc" : "asc";
        } else {
            this.sortCol = colIdx;
            this.sortDir = "asc";
        }
        this._updateSortUI();
        this._applyFiltersAndSort();
    }

    _updateSortUI() {
        /** Update sort arrow visuals. */
        this.columns.forEach((col, i) => {
            if (!col._arrowEl) return;
            if (i === this.sortCol) {
                col._arrowEl.textContent = this.sortDir === "asc" ? "\u25B2" : "\u25BC";
                col._arrowEl.classList.add("dg-th-sort-active");
            } else {
                col._arrowEl.textContent = "\u25B4\u25BE";
                col._arrowEl.classList.remove("dg-th-sort-active");
            }
        });
    }

    // ---- Filter (DataGrip-style value checkboxes) ----

    _showFilterDialog(col, colIdx, thEl) {
        /** Show a filter dropdown with checkboxes for unique values. */
        this._closeFilterDialog();

        const grid = this;

        // Only show values from rows that pass all OTHER column filters
        const otherFilterKeys = Object.keys(this.filters).filter((k) => k !== col.key);
        let filteredData = this.allData;
        if (otherFilterKeys.length > 0) {
            filteredData = filteredData.filter((row) => {
                return otherFilterKeys.every((key) => {
                    const val = String(row[key] ?? "");
                    return this.filters[key].has(val);
                });
            });
        }
        const uniqueVals = [...new Set(filteredData.map((r) => String(r[col.key] ?? "")))].sort();

        // Track which values are checked — start from current filter or all
        // Use a separate working copy so we don't corrupt the live filter
        const currentFilter = this.filters[col.key];
        const checked = currentFilter ? new Set(currentFilter) : new Set(uniqueVals);

        const dialog = document.createElement("div");
        dialog.className = "dg-filter-dialog";

        // Position below header
        const rect = thEl.getBoundingClientRect();
        const wrapRect = this.wrapperEl.getBoundingClientRect();
        dialog.style.left = Math.max(0, rect.left - wrapRect.left) + "px";
        dialog.style.top = (rect.bottom - wrapRect.top) + "px";
        dialog.style.minWidth = Math.max(rect.width, 220) + "px";

        // Warning about other active filters
        if (otherFilterKeys.length > 0) {
            const warn = document.createElement("div");
            warn.className = "dg-filter-warn";
            const otherLabels = otherFilterKeys.map((k) => {
                const c = this.columns.find((col) => col.key === k);
                return c ? c.label : k;
            });
            warn.textContent = "Additional filters applied: " + otherLabels.join(", ");
            dialog.appendChild(warn);
        }

        // Search input — restore previous search text
        const search = document.createElement("input");
        search.type = "text";
        search.placeholder = "Search...";
        search.className = "dg-filter-search";
        search.value = this.filterSearchText[col.key] || "";
        dialog.appendChild(search);

        // Select all / none
        const controls = document.createElement("div");
        controls.className = "dg-filter-controls";
        const selAllBtn = document.createElement("a");
        selAllBtn.href = "#";
        selAllBtn.textContent = "All";
        const selNoneBtn = document.createElement("a");
        selNoneBtn.href = "#";
        selNoneBtn.textContent = "None";
        controls.appendChild(selAllBtn);
        controls.appendChild(selNoneBtn);
        dialog.appendChild(controls);

        // Checkbox list
        const listEl = document.createElement("div");
        listEl.className = "dg-filter-list";
        dialog.appendChild(listEl);

        /** Apply the current checked set to the grid immediately. */
        function applyFilter() {
            // Compare against all unique values to decide if filter is active
            let allChecked = true;
            for (const v of uniqueVals) {
                if (!checked.has(v)) { allChecked = false; break; }
            }
            if (allChecked) {
                delete grid.filters[col.key];
            } else {
                grid.filters[col.key] = new Set(checked);
            }
            grid._updateFilterUI();
            grid._applyFiltersAndSort();
        }

        let showOnlyChecked = false;

        /** Render checkbox list, filtered by search text and checked-only mode. */
        function renderList() {
            listEl.innerHTML = "";
            const ft = search.value.trim().toLowerCase();
            for (const val of uniqueVals) {
                if (ft && !val.toLowerCase().includes(ft)) continue;
                if (showOnlyChecked && !checked.has(val)) continue;
                const label = document.createElement("label");
                label.className = "dg-filter-item";
                const cb = document.createElement("input");
                cb.type = "checkbox";
                cb.checked = checked.has(val);
                cb.addEventListener("change", () => {
                    if (cb.checked) checked.add(val);
                    else checked.delete(val);
                    applyFilter();
                });
                label.appendChild(cb);
                label.appendChild(document.createTextNode(" " + (val || "(empty)")));
                listEl.appendChild(label);
            }
        }

        renderList();

        search.addEventListener("input", () => {
            grid.filterSearchText[col.key] = search.value;
            renderList();
        });

        /** Get the values currently visible in the checkbox list. */
        function getVisibleVals() {
            const ft = search.value.trim().toLowerCase();
            if (!ft) return uniqueVals;
            return uniqueVals.filter((v) => v.toLowerCase().includes(ft));
        }

        selAllBtn.addEventListener("click", (e) => {
            e.preventDefault();
            for (const val of getVisibleVals()) checked.add(val);
            renderList();
            applyFilter();
        });

        selNoneBtn.addEventListener("click", (e) => {
            e.preventDefault();
            for (const val of getVisibleVals()) checked.delete(val);
            showOnlyChecked = false;
            renderList();
            applyFilter();
        });

        // Close on click outside
        this._filterDialog = dialog;
        this._filterClickAway = (e) => {
            if (!dialog.contains(e.target) && !thEl.contains(e.target)) {
                this._closeFilterDialog();
            }
        };
        setTimeout(() => document.addEventListener("click", this._filterClickAway), 0);

        this.wrapperEl.appendChild(dialog);
        search.focus();
    }

    _closeFilterDialog() {
        /** Remove the filter dialog if open. */
        if (this._filterDialog) {
            this._filterDialog.remove();
            this._filterDialog = null;
        }
        if (this._filterClickAway) {
            document.removeEventListener("click", this._filterClickAway);
            this._filterClickAway = null;
        }
    }

    _updateFilterUI() {
        /** Show/hide filter indicator dots on headers. */
        this.columns.forEach((col) => {
            if (col._filterDotEl) {
                col._filterDotEl.textContent = this.filters[col.key] ? " \u25CF" : "";
            }
        });
    }

    // ---- Filter + Sort pipeline ----

    _applyFiltersAndSort() {
        /** Apply active filters and sort, then re-render. */
        let data = this.allData;

        // Filter by checked values
        const filterKeys = Object.keys(this.filters);
        if (filterKeys.length > 0) {
            data = data.filter((row) => {
                return filterKeys.every((key) => {
                    const val = String(row[key] ?? "");
                    return this.filters[key].has(val);
                });
            });
        }

        // Sort
        if (this.sortCol !== null) {
            const col = this.columns[this.sortCol];
            const dir = this.sortDir;
            data = [...data].sort((a, b) => {
                const av = a[col.key] ?? "";
                const bv = b[col.key] ?? "";
                const an = parseFloat(av);
                const bn = parseFloat(bv);
                let cmp;
                if (!isNaN(an) && !isNaN(bn)) {
                    cmp = an - bn;
                } else {
                    cmp = String(av).localeCompare(String(bv), undefined, { sensitivity: "base" });
                }
                return dir === "asc" ? cmp : -cmp;
            });
        }

        this.data = data;
        this.selected.clear();
        this.lastClickedIdx = null;
        this._renderBody();
    }

    // ---- Resize ----

    _startResize(th, col, startX) {
        /** Start column resize drag from the handle element. */
        const startWidth = col.width;
        const colIdx = this.columns.indexOf(col);
        const minWidth = (col.minChars || 3) * 8 + 24; // Rough char width + padding

        const onMove = (e) => {
            const dx = e.clientX - startX;
            const newWidth = Math.max(minWidth, startWidth + dx);
            col.width = newWidth;
            th.style.width = newWidth + "px";
            // Sync body cells via colgroup would be ideal, but direct update works
            const cellIdx = colIdx + 1; // +1 for selection column
            this.tbodyEl.querySelectorAll("tr").forEach((tr) => {
                const td = tr.children[cellIdx];
                if (td) td.style.width = newWidth + "px";
            });
        };

        const onUp = () => {
            document.body.style.cursor = "";
            document.body.style.userSelect = "";
            document.removeEventListener("mousemove", onMove);
            document.removeEventListener("mouseup", onUp);
        };

        document.body.style.cursor = "col-resize";
        document.body.style.userSelect = "none";
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
    }

    // ---- Auto-width ----

    _autoFitColumns() {
        /** Measure widest value per autoWidth column and set width. */
        if (!this.allData.length) return;

        const ruler = document.createElement("span");
        ruler.style.cssText = "position:absolute;visibility:hidden;white-space:nowrap;font-size:0.875rem;";
        document.body.appendChild(ruler);

        for (const col of this.columns) {
            if (!col.autoWidth) continue;

            ruler.textContent = col.label;
            let maxW = ruler.offsetWidth;

            const sample = this.allData.length > 200
                ? this.allData.filter((_, i) => i % Math.ceil(this.allData.length / 200) === 0)
                : this.allData;

            for (const row of sample) {
                ruler.textContent = String(row[col.key] ?? "");
                const w = ruler.offsetWidth;
                if (w > maxW) maxW = w;
            }

            let newWidth = maxW + 24;
            if (col.maxAutoWidth) newWidth = Math.min(newWidth, col.maxAutoWidth);
            col.width = newWidth;
        }

        ruler.remove();
    }
}
