/**
 * Drag-to-resize for panel handles.
 *
 * Usage: add class="resize-handle" to a thin div between two panels,
 * then call Resize.init(handleId, leftPanelId_or_null, rightPanelId_or_null).
 *
 * Exactly one of leftPanel / rightPanel should be the fixed-width panel
 * being resized. The other side flexes naturally.
 */
const Resize = {
    init(handleId, leftPanelId, rightPanelId) {
        const handle = document.getElementById(handleId);
        const leftPanel = leftPanelId ? document.getElementById(leftPanelId) : null;
        const rightPanel = rightPanelId ? document.getElementById(rightPanelId) : null;
        if (!handle) return;

        const storageKey = "resize-width-" + handleId;
        const targetPanel = leftPanel || rightPanel;

        // Restore saved width
        const saved = localStorage.getItem(storageKey);
        if (saved && targetPanel) targetPanel.style.width = saved + "px";

        let startX = 0;
        let startWidth = 0;
        let panel = null;
        let direction = 1; // 1 = drag right grows panel, -1 = drag right shrinks

        handle.addEventListener("mousedown", (e) => {
            e.preventDefault();
            if (leftPanel) {
                panel = leftPanel;
                direction = 1;
                startWidth = leftPanel.offsetWidth;
            } else if (rightPanel) {
                panel = rightPanel;
                direction = -1;
                startWidth = rightPanel.offsetWidth;
            }
            startX = e.clientX;
            handle.classList.add("dragging");
            document.body.style.cursor = "col-resize";
            document.body.style.userSelect = "none";
            document.addEventListener("mousemove", onMouseMove);
            document.addEventListener("mouseup", onMouseUp);
        });

        function onMouseMove(e) {
            const dx = e.clientX - startX;
            const newWidth = Math.max(80, startWidth + dx * direction);
            panel.style.width = newWidth + "px";
        }

        function onMouseUp() {
            handle.classList.remove("dragging");
            document.body.style.cursor = "";
            document.body.style.userSelect = "";
            document.removeEventListener("mousemove", onMouseMove);
            document.removeEventListener("mouseup", onMouseUp);
            if (panel) localStorage.setItem(storageKey, panel.offsetWidth);
        }
    },
};

/** Initialize a vertical (horizontal drag) resize handle. Idempotent. Persists height to localStorage. */
Resize.initVertical = function(handleId, panelId) {
    const handle = document.getElementById(handleId);
    const panel = document.getElementById(panelId);
    if (!handle || !panel) return;
    if (handle._resizeInit) return;
    handle._resizeInit = true;

    const storageKey = "resize-height-" + panelId;

    // Restore saved height
    const saved = localStorage.getItem(storageKey);
    if (saved) panel.style.height = saved + "px";

    let startY = 0;
    let startHeight = 0;

    handle.addEventListener("mousedown", (e) => {
        e.preventDefault();
        startY = e.clientY;
        startHeight = panel.offsetHeight;
        document.body.style.cursor = "row-resize";
        document.body.style.userSelect = "none";

        function onMove(e) {
            const dy = startY - e.clientY;
            panel.style.height = Math.max(80, startHeight + dy) + "px";
        }

        function onUp() {
            document.body.style.cursor = "";
            document.body.style.userSelect = "";
            document.removeEventListener("mousemove", onMove);
            document.removeEventListener("mouseup", onUp);
            localStorage.setItem(storageKey, panel.offsetHeight);
        }

        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
    });
};

Resize.init("resize-left", "sidebar", null);
Resize.initVertical("resize-verify", "verify-panel");
