/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { Component, useState, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import {
    WmsTopNav,
    MODE_ACTIONS, MODE_ACCENT,
    getSlaClass, getPlatformBadge,
} from "../wms_pick_pos/wms_pick_screen";

export class WmsOutboundScreen extends Component {
    static template   = "kob_wms.WmsOutboundScreen";
    static components = { WmsTopNav };
    static props      = { ...standardActionServiceProps };

    get accentColor() { return MODE_ACCENT.outbound; }
    get activeMode()  { return "outbound"; }

    setup() {
        this.orm           = useService("orm");
        this.notification  = useService("notification");
        this.actionService = useService("action");
        this.scanInputRef  = useRef("scanInput");

        this.state = useState({
            orders: [], selectedOrderId: null, currentOrder: null,
            loading: true, lastScan: "", lastScanOk: null, processing: false,
        });

        this._scanBuffer = "";
        this._scanTimer  = null;
        this._globalKeyHandler = this._onGlobalKey.bind(this);
        this._rejectHandler    = (ev) => { ev.preventDefault(); ev.stopImmediatePropagation(); };

        onMounted(() => {
            this.loadOrders();
            this._focusScan();
            document.addEventListener("keydown", this._globalKeyHandler, true);
            window.addEventListener("unhandledrejection", this._rejectHandler, true);
        });
        onWillUnmount(() => {
            document.removeEventListener("keydown", this._globalKeyHandler, true);
            window.removeEventListener("unhandledrejection", this._rejectHandler, true);
        });
    }

    goToMode(mode) {
        const action = MODE_ACTIONS[mode];
        if (action) this.actionService.doAction(action);
    }
    onClickBack() { this.actionService.doAction("kob_wms.action_wms_dashboard"); }

    _onGlobalKey(ev) {
        if (this.scanInputRef.el && document.activeElement === this.scanInputRef.el) return;
        if (ev.ctrlKey || ev.altKey || ev.metaKey) return;
        if (ev.key === "Escape") { this.deselectOrder(); return; }
        if (ev.key === "F1") { ev.preventDefault(); this.goToMode("pick");     return; }
        if (ev.key === "F2") { ev.preventDefault(); this.goToMode("pack");     return; }
        if (ev.key === "F3") { ev.preventDefault(); this.goToMode("outbound"); return; }
        if (ev.key === "F4") { ev.preventDefault(); this.goToMode("dispatch"); return; }
        if (ev.key === "Enter" && this._scanBuffer.length >= 3) {
            ev.preventDefault();
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

    async loadOrders() {
        this.state.loading = true;
        this.state.orders = await this.orm.searchRead("wms.sales.order",
            [["status", "=", "packed"]],
            ["id", "name", "ref", "customer", "platform", "status",
             "awb", "courier_id", "box_barcode", "packed_at", "expected_total",
             "sla_status", "sla_ship_deadline"],
            { limit: 200, order: "sla_ship_deadline asc, packed_at asc" });
        this.state.loading = false;
    }

    selectOrder(order) {
        this.state.selectedOrderId = order.id;
        this.state.currentOrder    = order;
        this._focusScan();
    }

    deselectOrder() {
        this.state.selectedOrderId = null;
        this.state.currentOrder    = null;
        this._focusScan();
    }

    async onBarcodeScanned(code) {
        if (this.state.processing) return;
        this.state.lastScan = code;

        // No order selected → find order
        if (!this.state.selectedOrderId) {
            let match = this.state.orders.find(
                o => o.ref === code || o.name === code || o.box_barcode === code)
                     || this.state.orders.find(
                o => (o.ref  && o.ref.includes(code)) ||
                     (o.name && o.name.includes(code)));
            if (match) {
                this.selectOrder(match);
                this.state.lastScanOk = true;
            } else {
                this.state.lastScanOk = false;
                this.notification.add(_t("Packed order not found: ") + code, { type: "danger" });
            }
            return;
        }

        // Order selected → AWB scan → ship
        this.state.processing = true;
        const result = await this.orm.call(
            "wms.sales.order", "set_awb_and_ship",
            [[this.state.selectedOrderId], code]);

        if (result && result.ok) {
            this.state.lastScanOk = true;
            this.notification.add(
                (this.state.currentOrder.ref || this.state.currentOrder.name) +
                " → Shipped! AWB: " + code,
                { type: "success" });
            this.deselectOrder();
            await this.loadOrders();
        } else {
            this.state.lastScanOk = false;
            this.notification.add((result && result.error) || "Ship error", { type: "danger" });
        }
        this.state.processing = false;
        this._focusScan();
    }

    getSlaClass(order)      { return getSlaClass(order); }
    getPlatformBadge(order) { return getPlatformBadge(order.platform); }

    get courierGroups() {
        const map = {};
        for (const o of this.state.orders) {
            const name = o.courier_id ? o.courier_id[1] : "No Courier";
            map[name] = (map[name] || 0) + 1;
        }
        return Object.entries(map).map(([name, count]) => ({ name, count }));
    }
}

registry.category("actions").add("kob_wms.outbound_screen", WmsOutboundScreen);
