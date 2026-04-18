/** @odoo-module **/
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { onMounted, onWillUnmount } from "@odoo/owl";

/**
 * WmsListController — extends Odoo's ListController with a
 * persistent barcode-scan bar that sits between the control panel
 * and the list rows.  Scanning (or typing + Enter) looks up a
 * wms.sales.order by name or platform ref and opens its form.
 */
class WmsListController extends ListController {
    setup() {
        super.setup();
        this._wmsAction  = useService("action");
        this._wmsOrm     = useService("orm");
        this._scanBarEl  = null;

        onMounted(()     => this._mountScanBar());
        onWillUnmount(() => this._unmountScanBar());
    }

    // ── Build + inject the scan bar DOM ──────────────────────────
    _mountScanBar() {
        // Remove any stale bar from a previous navigation
        document.querySelector(".wms-scan-bar")?.remove();

        const bar = document.createElement("div");
        bar.className = "wms-scan-bar";
        bar.innerHTML = `
            <span class="wms-scan-icon"><i class="fa fa-barcode"></i></span>
            <input class="wms-scan-input"
                   placeholder="Scan order barcode to open..."
                   autocomplete="off" spellcheck="false"/>
            <span class="wms-scan-status wms-scan-ready">READY</span>
        `;

        // Insert immediately after the Odoo control panel
        const cp = document.querySelector(".o_control_panel");
        if (cp) {
            cp.insertAdjacentElement("afterend", bar);
        } else {
            document.querySelector(".o_content")?.prepend(bar);
        }

        this._scanBarEl = bar;
        const input     = bar.querySelector("input");
        const status    = bar.querySelector(".wms-scan-status");

        // Autofocus — cursor blinks immediately
        requestAnimationFrame(() => input.focus());

        input.addEventListener("keydown", async (ev) => {
            if (ev.key !== "Enter") return;
            const val = ev.target.value.trim();
            if (!val) return;

            ev.target.value = "";
            this._setStatus(status, "SEARCHING...", "wms-scan-searching");

            try {
                await this._handleScan(val, input, status);
            } catch {
                this._setStatus(status, "ERROR", "wms-scan-error");
                setTimeout(() => {
                    this._setStatus(status, "READY", "wms-scan-ready");
                    input.focus();
                }, 1500);
            }
        });
    }

    /**
     * Default scan handler — find the order and open its form.
     * Subclasses can override this to change the scan behaviour.
     */
    async _handleScan(val, input, status) {
        const rows = await this._wmsOrm.searchRead(
            "wms.sales.order",
            ["|", "|", "|",
                ["name",        "=ilike", val],   // SO number
                ["ref",         "=ilike", val],   // platform ref (case-insensitive)
                ["awb",         "=ilike", val],   // AWB / tracking no.
                ["box_barcode", "=",      val],   // box barcode sticker
            ],
            ["id"],
            { limit: 1 }
        );

        if (rows.length) {
            this._setStatus(status, "FOUND ✓", "wms-scan-found");
            await this._wmsAction.doAction({
                type: "ir.actions.act_window",
                res_model: "wms.sales.order",
                res_id: rows[0].id,
                views: [[false, "form"]],
                target: "current",
            });
        } else {
            this._setStatus(status, "NOT FOUND ✗", "wms-scan-error");
            setTimeout(() => {
                this._setStatus(status, "READY", "wms-scan-ready");
                input.focus();
            }, 1500);
        }
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

/**
 * WmsOutboundListController — scan-to-ship variant for the Outbound Queue.
 * Scanning a barcode calls action_list_ship directly without opening the form.
 * Worker just scans and moves on — no tapping required.
 */
class WmsOutboundListController extends WmsListController {
    async _handleScan(val, input, status) {
        // 1. Find the order — only packed orders can be shipped from this screen
        const rows = await this._wmsOrm.searchRead(
            "wms.sales.order",
            ["&", ["status", "=", "packed"],
             "|", "|", "|",
                ["name",        "=ilike", val],
                ["ref",         "=ilike", val],
                ["awb",         "=ilike", val],
                ["box_barcode", "=",      val],
            ],
            ["id", "name"],
            { limit: 1 }
        );

        if (!rows.length) {
            this._setStatus(status, "NOT FOUND (not packed?) ✗", "wms-scan-error");
            setTimeout(() => {
                this._setStatus(status, "READY", "wms-scan-ready");
                input.focus();
            }, 1800);
            return;
        }

        // 2. Ship the order directly — pass scanned value so Python can set AWB
        this._setStatus(status, "SHIPPING...", "wms-scan-searching");

        const res = await this._wmsOrm.call(
            "wms.sales.order",
            "action_list_ship",
            [[rows[0].id], val]   // val may become AWB if order has none yet
        );

        if (!res.ok) {
            this._setStatus(status, `✗  ${res.error}`, "wms-scan-error");
        } else {
            const awbPart = res.awb ? ` | AWB: ${res.awb}` : '';
            this._setStatus(status, `✓  SHIPPED: ${res.name}${awbPart}`, "wms-scan-found");
        }

        setTimeout(() => {
            this._setStatus(status, "READY", "wms-scan-ready");
            input.focus();
        }, 2000);
    }
}

// ── Register view types ───────────────────────────────────────────────────────

// Pick / Pack / Dispatch queues — scan opens form
registry.category("views").add("wms_list", {
    ...listView,
    Controller: WmsListController,
});

// Outbound queue — scan ships directly
registry.category("views").add("wms_outbound_list", {
    ...listView,
    Controller: WmsOutboundListController,
});
