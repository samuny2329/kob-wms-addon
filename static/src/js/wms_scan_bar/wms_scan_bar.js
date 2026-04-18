/** @odoo-module **/
import { Component, useState, useRef, onMounted, onPatched } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { Dialog } from "@web/core/dialog/dialog";

// ── Close Box Dialog ──────────────────────────────────────────────────────────
/**
 * WmsCloseBoxDialog — auto-pops when all items are packed.
 * Shows the system-calculated recommended box, an override dropdown for
 * emergency cases, then closes the box and auto-prints the AWB.
 */
class WmsCloseBoxDialog extends Component {
    static template = "kob_wms.WmsCloseBoxDialog";
    static components = { Dialog };

    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");
        this.state  = useState({
            overrideCode: "",   // empty = use recommendation
            loading: false,
            error: "",
        });
    }

    /** Box code that will actually be used when closing. */
    get effectiveCode() {
        return this.state.overrideCode || (this.props.suggestion && this.props.suggestion.box_code) || "";
    }

    get effectiveLabel() {
        if (this.state.overrideCode) {
            const found = (this.props.boxes || []).find(b => b.code === this.state.overrideCode);
            return found ? found.label : this.state.overrideCode;
        }
        return (this.props.suggestion && this.props.suggestion.box_label) || "—";
    }

    onBoxChange(ev) {
        this.state.overrideCode = ev.target.value;
    }

    onCancel() {
        this.props.close();
    }

    async onCloseBox() {
        if (this.state.loading) return;
        this.state.loading = true;
        this.state.error   = "";

        try {
            const worker = (() => {
                try { return JSON.parse(localStorage.getItem("wms_worker") || "null") || {}; }
                catch { return {}; }
            })();

            const res = await this.orm.call(
                "wms.sales.order",
                "select_box_and_close",
                [[this.props.recordId], this.effectiveCode, worker.id || false]
            );

            if (!res.ok) {
                this.state.error   = res.error || "Unknown error";
                this.state.loading = false;
                return;
            }

            // Auto-print AWB if the backend returned a print action
            if (res.awb_action) {
                await this.action.doAction(res.awb_action);
            }

            this.props.close();
            // Navigate back to Pack Queue — worker is ready for next order
            await this.action.doAction("kob_wms.action_wms_pack_screen");

        } catch (err) {
            console.error("[WMS] close_box error:", err);
            this.state.error   = "Server error — see console";
            this.state.loading = false;
        }
    }
}

// ── Scan Bar Widget ───────────────────────────────────────────────────────────
/**
 * WmsScanBar — Odoo view_widget placed at the top of the order form sheet.
 * Routes each scan to scan_pick or scan_pack based on order status.
 * When packing is complete, auto-opens WmsCloseBoxDialog.
 */
class WmsScanBar extends Component {
    static template = "kob_wms.WmsScanBar";
    // No strict static props — Widget wrapper passes dynamic props

    setup() {
        this.orm    = useService("orm");
        this.dialog = useService("dialog");
        this.action = useService("action");
        this.inputRef  = useRef("scanInput");
        this.statusRef = useRef("scanStatus");
        this._refocus  = false;

        onMounted(() => this._focus());
        onPatched(() => {
            if (this._refocus) {
                this._refocus = false;
                this._focus();
            }
        });
    }

    _focus() {
        requestAnimationFrame(() => this.inputRef.el?.focus());
    }

    async onKeydown(ev) {
        if (ev.key !== "Enter") return;
        const val = ev.target.value.trim();
        if (!val) return;
        ev.target.value = "";

        this._setStatus("SCANNING...", "wms-scan-searching");

        try {
            const recordId = this.props.record.resId;
            if (!recordId) {
                this._flash("SAVE ORDER FIRST", "wms-scan-error");
                return;
            }

            const worker = (() => {
                try { return JSON.parse(localStorage.getItem("wms_worker") || "null") || {}; }
                catch { return {}; }
            })();

            const res = await this.orm.call(
                "wms.sales.order",
                "action_scan_item",
                [[recordId], val, worker.id || false]
            );

            if (!res.ok) {
                this._flash(`✗  ${res.error}`, "wms-scan-error");
                return;
            }

            // ── All packed → open close box dialog → then back to Pack Queue ──
            if (res.all_done && res.phase === "pack") {
                this._setStatus("✓ PACKING COMPLETE — Select box...", "wms-scan-found");
                await this.props.record.load();
                await this._openCloseBoxDialog(recordId);
                this._scheduleReset();
                return;
            }

            // ── All picked → show message → navigate back to Pick Queue ──
            if (res.all_done && res.phase === "pick") {
                this._setStatus("✓ ALL PICKED  —  Returning to queue...", "wms-scan-found");
                await this.props.record.load();
                setTimeout(() => {
                    this.action.doAction("kob_wms.action_wms_pick_screen");
                }, 1500);
                return;
            }

            // ── Normal scan — show progress ───────────────────────────────
            this._setStatus(`✓ ${res.msg}`, "wms-scan-found");
            this._refocus = true;
            await this.props.record.load();

        } catch (err) {
            console.error("[WMS] scan_item error:", err);
            this._flash("RPC ERROR — see console", "wms-scan-error");
            return;
        }

        this._scheduleReset();
    }

    async _openCloseBoxDialog(recordId) {
        try {
            const data = await this.orm.call(
                "wms.sales.order",
                "action_get_close_box_data",
                [[recordId]]
            );

            this.dialog.add(WmsCloseBoxDialog, {
                recordId:   recordId,
                record:     this.props.record,
                orderName:  data.order_name,
                suggestion: data.suggestion,
                boxes:      data.boxes || [],
            });
        } catch (err) {
            console.error("[WMS] get_close_box_data error:", err);
            this._setStatus("Could not load box data", "wms-scan-error");
        }
    }

    _setStatus(text, cls) {
        const el = this.statusRef.el;
        if (!el) return;
        el.textContent = text;
        el.className   = `wms-scan-status ${cls}`;
    }

    _flash(msg, cls) {
        this._setStatus(msg, cls);
        this._scheduleReset();
    }

    _scheduleReset() {
        setTimeout(() => {
            this._setStatus("READY", "wms-scan-ready");
            this._focus();
        }, 1800);
    }
}

// Odoo 18: view_widgets registry expects { component } object
registry.category("view_widgets").add("wms_scan_bar", { component: WmsScanBar });
