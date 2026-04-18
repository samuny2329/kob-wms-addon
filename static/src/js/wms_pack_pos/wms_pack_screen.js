/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { Component, useState, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import {
    WmsTopNav, WmsPickCard,
    MODE_ACTIONS, MODE_ACCENT,
    getSlaClass, getPlatformBadge, getPlatformIcon,
} from "../wms_pick_pos/wms_pick_screen";

export class WmsPackScreen extends Component {
    static template   = "kob_wms.WmsPackScreen";
    static components = { WmsTopNav, WmsPickCard };
    static props      = { ...standardActionServiceProps };

    get accentColor() { return MODE_ACCENT.pack; }
    get activeMode()  { return "pack"; }

    setup() {
        this.orm           = useService("orm");
        this.notification  = useService("notification");
        this.actionService = useService("action");
        this.scanInputRef  = useRef("scanInput");

        this.state = useState({
            orders: [], selectedOrderId: null, currentOrder: null, currentLines: [],
            loading: true, flashLineId: null, flashType: null,
            scanning: false, processing: false,
            lastScan: "", lastScanOk: null,
            viewMode: "card", boxMode: false,
            // Auto-box sizing
            boxSizes: [], boxSizesLoaded: false,
            suggestedBoxCode: null, suggesting: false, suggestionNote: "",
        });

        this._scanBuffer = "";
        this._scanTimer  = null;
        this._globalKeyHandler = this._onGlobalKey.bind(this);
        this._rejectHandler    = (ev) => { ev.preventDefault(); ev.stopImmediatePropagation(); };

        onMounted(() => {
            this.loadOrders();
            this.loadBoxSizes();
            this._focusScan();
            document.addEventListener("keydown", this._globalKeyHandler, true);
            window.addEventListener("unhandledrejection", this._rejectHandler, true);
        });
        onWillUnmount(() => {
            document.removeEventListener("keydown", this._globalKeyHandler, true);
            window.removeEventListener("unhandledrejection", this._rejectHandler, true);
        });
    }

    // ── Navigation ─────────────────────────────────────────────
    goToMode(mode) {
        const action = MODE_ACTIONS[mode];
        if (action) this.actionService.doAction(action);
    }
    onClickBack() { this.actionService.doAction("kob_wms.action_wms_dashboard"); }

    // ── Keyboard / scanner ─────────────────────────────────────
    _onGlobalKey(ev) {
        if (this.scanInputRef.el && document.activeElement === this.scanInputRef.el) return;
        if (ev.ctrlKey || ev.altKey || ev.metaKey) return;
        if (ev.key === "Escape") { this.deselectOrder(); return; }
        if (ev.key === "F1") { ev.preventDefault(); this.goToMode("pick");     return; }
        if (ev.key === "F2") { ev.preventDefault(); this.goToMode("pack");     return; }
        if (ev.key === "F3") { ev.preventDefault(); this.goToMode("outbound"); return; }
        if (ev.key === "F4") { ev.preventDefault(); this.goToMode("dispatch"); return; }
        if (ev.key === "Enter" && this._scanBuffer.length >= 3) {
            ev.preventDefault(); ev.stopPropagation();
            this.onBarcodeScanned(this._scanBuffer.trim());
            this._scanBuffer = "";
            clearTimeout(this._scanTimer);
            return;
        }
        if (ev.key.length === 1) {
            this._scanBuffer += ev.key;
            clearTimeout(this._scanTimer);
            this._scanTimer = setTimeout(() => { this._scanBuffer = ""; }, 100);
        }
    }

    _focusScan() {
        setTimeout(() => {
            const el = this.scanInputRef.el;
            if (el) { el.value = ""; el.focus(); }
        }, 50);
    }

    onScanKeydown(ev) {
        if (ev.key !== "Enter") return;
        ev.preventDefault();
        const code = (ev.target.value || "").trim();
        if (code.length >= 2) this.onBarcodeScanned(code);
        ev.target.value = "";
        this._focusScan();
    }

    // ── Box sizes ────────────────────────────────────────────────
    async loadBoxSizes() {
        this.state.boxSizes = await this.orm.searchRead(
            "wms.box.size",
            [["active", "=", true]],
            ["id", "code", "label", "length", "width", "height", "volume_cm3"],
            { order: "sequence asc, volume_cm3 asc", limit: 50 });
        this.state.boxSizesLoaded = true;
    }

    async autoSelectBox() {
        if (!this.state.selectedOrderId || this.state.suggesting) return;
        this.state.suggesting = true;
        this.state.suggestedBoxCode = null;
        this.state.suggestionNote = "";

        const result = await this.orm.call(
            "wms.sales.order", "get_recommended_box",
            [[this.state.selectedOrderId]]);

        if (result && result.ok) {
            this.state.suggestedBoxCode = result.box_code;
            this.state.suggestionNote   = result.note || "";
            this._scrollToBox(result.box_code);
        } else {
            this.notification.add(
                (result && result.error) || _t("Auto-size error"), { type: "warning" });
        }
        this.state.suggesting = false;
    }

    _scrollToBox(code) {
        // Wait one tick for OWL to re-render the highlighted card, then scroll it into view
        setTimeout(() => {
            const btn = document.querySelector(`[data-box-code="${code}"]`);
            if (btn) btn.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
        }, 80);
    }

    // ── Data ────────────────────────────────────────────────────
    async loadOrders() {
        this.state.loading = true;
        this.state.orders = await this.orm.searchRead("wms.sales.order",
            [["status", "in", ["picked", "packing"]]],
            ["id", "name", "ref", "customer", "platform", "status",
             "expected_total", "picked_total", "packed_total", "all_packed",
             "sla_status", "sla_pack_deadline", "picking_id"],
            { limit: 200, order: "sla_pack_deadline asc, create_date desc" });
        this.state.loading = false;
    }

    async selectOrder(order) {
        this.state.selectedOrderId  = order.id;
        this.state.currentOrder     = order;
        this.state.suggestedBoxCode = null;
        this.state.suggestionNote   = "";
        this.state.currentLines     = await this.orm.searchRead("wms.sales.order.line",
            [["order_id", "=", order.id]],
            ["id", "sku", "product_name", "product_id",
             "expected_qty", "picked_qty", "packed_qty", "product_barcode"],
            { order: "sequence, id" });
        // If order is already fully packed, enter box mode + auto-suggest immediately
        if (order.all_packed) {
            this.state.boxMode = true;
            this.autoSelectBox();
        } else {
            this.state.boxMode = false;
        }
        this._focusScan();
    }

    deselectOrder() {
        this.state.selectedOrderId = null;
        this.state.currentOrder    = null;
        this.state.currentLines    = [];
        this.state.boxMode         = false;
        this._focusScan();
    }

    // ── Scan ────────────────────────────────────────────────────
    async onBarcodeScanned(code) {
        if (this.state.scanning) return;
        this.state.lastScan = code;

        if (!this.state.selectedOrderId) {
            let match = this.state.orders.find(o => o.ref === code || o.name === code)
                     || this.state.orders.find(o =>
                            (o.ref  && o.ref.includes(code)) ||
                            (o.name && o.name.includes(code)));
            if (match) {
                await this.selectOrder(match);
                this.state.lastScanOk = true;
            } else {
                this.state.lastScanOk = false;
                this.notification.add(_t("Order not found: ") + code, { type: "danger" });
            }
            return;
        }

        if (this.state.boxMode) {
            this.state.scanning = false;
            this.notification.add(_t("Select box size to complete packing."), { type: "warning" });
            return;
        }

        this.state.scanning = true;
        const _wmsWorker = (() => { try { return JSON.parse(localStorage.getItem("wms_worker") || "{}"); } catch(e) { return {}; } })();
        const result = await this.orm.call(
            "wms.sales.order", "scan_pack",
            [[this.state.selectedOrderId], code, _wmsWorker.id || false]);

        if (result && result.ok) {
            const line = this.state.currentLines.find(l =>
                l.sku === code || l.product_barcode === code);
            if (line) {
                this.state.flashLineId = line.id;
                this.state.flashType   = "success";
                setTimeout(() => { this.state.flashLineId = null; this.state.flashType = null; }, 850);
            }
            this.state.lastScanOk = true;
            await this._reloadCurrent();
            if (result.all_packed || this.state.currentOrder?.all_packed) {
                this.state.boxMode = true;
                this.notification.add(_t("All packed! Auto-selecting box…"), { type: "info" });
                this.autoSelectBox();
            }
        } else {
            this.state.lastScanOk = false;
            this.state.flashType  = "error";
            setTimeout(() => { this.state.flashType = null; }, 850);
            this.notification.add((result && result.error) || "Pack error", { type: "danger" });
        }
        this.state.scanning = false;
        this._focusScan();
    }

    async _reloadCurrent() {
        if (!this.state.selectedOrderId) return;
        const orders = await this.orm.searchRead("wms.sales.order",
            [["id", "=", this.state.selectedOrderId]],
            ["id", "name", "ref", "customer", "platform", "status",
             "expected_total", "picked_total", "packed_total", "all_packed",
             "sla_status", "sla_pack_deadline", "picking_id"]);
        if (orders.length) this.state.currentOrder = orders[0];
        this.state.currentLines = await this.orm.searchRead("wms.sales.order.line",
            [["order_id", "=", this.state.selectedOrderId]],
            ["id", "sku", "product_name", "product_id",
             "expected_qty", "picked_qty", "packed_qty", "product_barcode"],
            { order: "sequence, id" });
        await this.loadOrders();
    }

    // ── Box selection → close packing → print label → send to Outbound ──
    async selectBox(size) {
        if (!this.state.selectedOrderId || this.state.processing) return;
        this.state.processing = true;

        const orderId  = this.state.selectedOrderId;
        const orderRef = this.state.currentOrder?.ref || this.state.currentOrder?.name || "";
        const _wmsWorker = (() => { try { return JSON.parse(localStorage.getItem("wms_worker") || "{}"); } catch(e) { return {}; } })();

        const packResult = await this.orm.call(
            "wms.sales.order", "select_box_and_close",
            [[orderId], size, _wmsWorker.id || false]);

        if (!packResult || !packResult.ok) {
            this.notification.add((packResult && packResult.error) || "Pack error", { type: "danger" });
            this.state.processing = false;
            return;
        }

        // Show stock warning if picking validation failed (packing is done, but stock NOT deducted)
        if (packResult.stock_warning) {
            this.notification.add(
                _t("⚠️ Packed ✓ but STOCK NOT DEDUCTED: %s", packResult.stock_warning),
                { type: "warning", sticky: true }
            );
        } else {
            // Normal success
            this.notification.add(
                _t("%s → Packed ✓ (box %s) — ready for Outbound", orderRef, size),
                { type: "success" });
        }
        window.open(`/report/pdf/kob_wms.report_wms_awb_label/${orderId}`, "_blank");

        this.deselectOrder();
        await this.loadOrders();
        this.state.processing = false;
    }

    // ── Helpers ─────────────────────────────────────────────────
    get progressPct() {
        const o = this.state.currentOrder;
        if (!o || !o.picked_total) return 0;
        return Math.round(((o.packed_total || 0) / o.picked_total) * 100);
    }

    getProductImage(line) {
        return line.product_id
            ? "/web/image?model=product.product&field=image_128&id=" + line.product_id[0]
            : false;
    }

    getSlaClass(order)      { return getSlaClass(order); }
    getPlatformBadge(order) { return getPlatformBadge(order.platform); }
    getPlatformIcon(p)      { return getPlatformIcon(p); }

    orderProgress(order) {
        if (!order.picked_total) return 0;
        return Math.round(((order.packed_total || 0) / order.picked_total) * 100);
    }
}

registry.category("actions").add("kob_wms.pack_screen", WmsPackScreen);
