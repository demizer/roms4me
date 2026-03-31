/**
 * Modal — reusable stacking modal system using plain divs.
 *
 * Supports multiple modals open at once (stacked).
 * Later-opened modals appear on top with a higher z-index.
 * Escape closes the topmost modal only.
 * Backdrop click closes only that modal.
 *
 * Usage:
 *   <div class="modal" id="my-modal">
 *     <div class="modal-backdrop"></div>
 *     <div class="modal-panel">
 *       <header class="modal-header">
 *         <h3>Title</h3>
 *         <button class="modal-close" aria-label="Close">&times;</button>
 *       </header>
 *       <div class="modal-body">...</div>
 *     </div>
 *   </div>
 *
 *   Modal.open("my-modal")
 *   Modal.close("my-modal")
 */
const Modal = (() => {
    const BASE_Z = 1000;
    /** @type {string[]} Stack of open modal ids, last = topmost */
    const stack = [];

    function _updateZIndices() {
        stack.forEach((id, i) => {
            const el = document.getElementById(id);
            if (el) el.style.zIndex = String(BASE_Z + i * 10);
        });
    }

    return {
        /** Open a modal. Stacks on top of any already-open modals. */
        open(id) {
            const el = document.getElementById(id);
            if (!el) return;
            // Don't double-open
            if (stack.includes(id)) return;
            stack.push(id);
            el.classList.add("is-open");
            _updateZIndices();
            document.body.style.overflow = "hidden";
            // Focus first visible input
            requestAnimationFrame(() => {
                const input = el.querySelector(
                    "input:not([hidden]):not([type=hidden])"
                );
                if (input) input.focus();
            });
        },

        /** Close a specific modal. */
        close(id) {
            const el = document.getElementById(id);
            if (!el) return;
            el.classList.remove("is-open");
            el.style.zIndex = "";
            const idx = stack.indexOf(id);
            if (idx !== -1) stack.splice(idx, 1);
            _updateZIndices();
            if (stack.length === 0) {
                document.body.style.overflow = "";
            }
        },

        /** Close the topmost modal. */
        closeTop() {
            if (stack.length === 0) return;
            this.close(stack[stack.length - 1]);
        },

        /** Close all open modals. */
        closeAll() {
            while (stack.length > 0) {
                this.close(stack[stack.length - 1]);
            }
        },

        /** Check if a modal is open. */
        isOpen(id) {
            return stack.includes(id);
        },
    };
})();

// Wire up .modal-close buttons and .modal-backdrop clicks
document.addEventListener("click", (e) => {
    const closeBtn = e.target.closest(".modal-close");
    if (closeBtn) {
        const modal = closeBtn.closest(".modal");
        if (modal) Modal.close(modal.id);
        return;
    }
    if (e.target.classList.contains("modal-backdrop")) {
        const modal = e.target.closest(".modal");
        if (modal) Modal.close(modal.id);
    }
});

// Escape closes topmost modal only
document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
        Modal.closeTop();
    }
});
