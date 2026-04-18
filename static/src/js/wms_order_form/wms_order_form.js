/** @odoo-module **/
import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { onMounted, onWillUnmount } from "@odoo/owl";

/**
 * WmsOrderFormController — extends Odoo's FormController with a
 * persistent barcode-scan bar injected between the control panel and
 * the form sheet.
 *
 * Scanning (barcode gun fires Enter after each code) calls
 * action_scan_item on the backend, which routes to scan_pick or
 * scan_pack depending on the order's current status — no button
 * clicks needed.
 */
class WmsOrderFormController extends FormController {
    setup() {
        super.setup();
        this._wmsOrm     = useService("orm");
        this._scanBarEl  = null;

        onMounted(()     => this._mountScanBar());
        onWillUnmount(() => this._unmountScanBar());
    }

    // ── Build + inject the scan bar DOM ──────────────────────────
    _mountScanBar() {
        // Clean up any stale bar from previous navigation
        document.querySelector(".wms-scan-bar")?.remove();

        const bar = document.createElement("div");
        bar.className = "wms-scan-bar";
        bar.innerHTML = `
            <span class="wms-scan-icon"><i class="fa fa-barcode"></i></span>
            <input class="wms-scan-input"
                   placeholder="Scan item barcode to pick / pack..."
                   autocomplete="off" spellcheck="false"/>
            <span class="wms-scan-status wms-scan-ready">READY</span>
        `;

        // Insert immediately after Odoo's control panel
        const cp = document.querySelector(".o_control_panel");
        if (cp) {
            cp.insertAdjacentElement("afterend", bar);
        } else {
            // Fallback: prepend to the view content area
            document.querySelector(".o_content")?.prepend(bar);
        }

        this._scanBarEl = bar;
        const input  = bar.querySelector("input");
        const status = bar.querySelector(".wms-scan-status");

        // Auto-focus — cursor blinks immediately when form opens
        requestAnimationFrame(() => input.focus());

        input.addEventListener("keydown", async (ev) => {
            if (ev.key !== "Enter") return;
            const val = ev.target.value.trim();
            if (!val) return;

            ev.target.value = "";
            this._setStatus(status, "SCANNING...", "wms-scan-searching");

            try {
                const recordId = this.model.root.resId;
                if (!recordId) {
                    this._flash(status, input, "SAVE ORDER FIRST", "wms-scan-error");
                    return;
                }

                // Pass kob.wms.user id from localStorage so the backend can
                // log the correct worker identity (shared Odoo account scenario)
                const worker = (() => {
                    try { return JSON.parse(localStorage.getItem("wms_worker") || "null") || {}; }
                    catch { return {}; }
                })();

                const res = await this._wmsOrm.call(
                    "wms.sales.order",
                    "action_scan_item",
                    [[recordId], val, worker.id || false]
                );

                if (res.ok) {
                    const label = res.all_done
                        ? `✓ ${res.msg}  —  ALL DONE`
                        : `✓ ${res.msg}`;
                    this._setStatus(status, label, "wms-scan-found");
                    // Reload form reactively — OWL re-renders qtys in the list
                    await this.model.root.load();
                } else {
                    this._flash(status, input, `✗  ${res.error}`, "wms-scan-error");
                    return;
                }
            } catch (err) {
                console.error("[WMS] scan_item RPC error:", err);
                this._flash(status, input, "RPC ERROR — see console", "wms-scan-error");
                return;
            }

            // Reset bar and re-focus for the next scan
            this._scheduleReset(status, input);
        });
    }

    /** Briefly show an error message then restore READY and re-focus. */
    _flash(status, input, msg, cls) {
        this._setStatus(status, msg, cls);
        this._scheduleReset(status, input);
    }

    /** After 1.8 s: reset status label → READY and restore cursor to scan input. */
    _scheduleReset(status, input) {
        setTimeout(() => {
            this._setStatus(status, "READY", "wms-scan-ready");
            // Re-focus even if OWL re-rendered (the bar DOM node survives patching)
            this._scanBarEl?.querySelector("input")?.focus();
        }, 1800);
    }

    _setStatus(el, text, cls) {
        el.textContent = text;
        el.className   = `wms-scan-status ${cls}`;
    }

    _unmountScanBar() {
        this._scanBarEl?.remove();
        this._scanBarEl = null;
    }
}

// Register as a named view type — applied via js_class="wms_order_form" on <form>
registry.category("views").add("wms_order_form", {
    ...formView,
    Controller: WmsOrderFormController,
});
