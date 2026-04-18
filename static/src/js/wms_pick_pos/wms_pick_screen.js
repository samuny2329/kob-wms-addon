/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { Component, useState, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

// ── Theme colours per mode ────────────────────────────────────────
export const MODE_ACCENT = {
    pick:     "#714B67",
    pack:     "#1C6EA4",
    outbound: "#C2500A",
    dispatch: "#1A9B38",
};

// ── Action tag per mode ───────────────────────────────────────────
export const MODE_ACTIONS = {
    pick:     "kob_wms.pick_screen",
    pack:     "kob_wms.pack_screen",
    outbound: "kob_wms.outbound_screen",
    dispatch: "kob_wms.dispatch_screen",
};

// ── Platform badge helpers ────────────────────────────────────────
const PLATFORM_MAP = {
    shopee:  { badge: "text-bg-warning",         icon: "fa-shopping-bag" },
    lazada:  { badge: "text-bg-primary",         icon: "fa-shopping-cart" },
    tiktok:  { badge: "text-bg-dark",            icon: "fa-music" },
    pos:     { badge: "text-bg-info",            icon: "fa-desktop" },
    odoo:    { badge: "text-bg-secondary",       icon: "fa-cog" },
    manual:  { badge: "text-bg-light text-dark", icon: "fa-pencil" },
    all:     { badge: "text-bg-secondary",       icon: "fa-list" },
};

export function getSlaClass(order) {
    if (order.sla_status === "breached") return "badge text-bg-danger";
    if (order.sla_status === "at_risk")  return "badge text-bg-warning";
    return "badge text-bg-success";
}
export function getPlatformBadge(platform) {
    return "badge " + ((PLATFORM_MAP[platform] || PLATFORM_MAP.manual).badge);
}
export function getPlatformIcon(p) {
    return (PLATFORM_MAP[p] || PLATFORM_MAP.all).icon;
}

// ── WmsTopNav shared component ────────────────────────────────────
export class WmsTopNav extends Component {
    static template = "kob_wms.WmsTopNav";
    static props = {
        activeMode:  String,
        accentColor: { type: String, optional: true },
        onNavigate:  { type: Function, optional: true },
        onBack:      { type: Function, optional: true },
    };

    setup() {
        this.actionService = useService("action");
        const _w = (() => {
            try { return JSON.parse(localStorage.getItem("wms_worker") || "{}"); }
            catch { return {}; }
        })();
        this.workerName     = _w.name || "Worker";
        this.workerInitials = (this.workerName.match(/\b\w/g) || ["W"]).slice(0, 2).join("").toUpperCase();
    }

    getModeLabel() {
        const m = { pick: "Pick · F1", pack: "Pack · F2", outbound: "Outbound · F3", dispatch: "Dispatch · F4" };
        return m[this.props.activeMode] || this.props.activeMode;
    }

    logout() {
        localStorage.removeItem("wms_worker");
        this.actionService.doAction("kob_wms.action_wms_login_screen");
    }
}

// ── WmsPickCard shared component ──────────────────────────────────
export class WmsPickCard extends Component {
    static template = "kob_wms.WmsPickCard";
    static props = {
        line:        Object,
        imageUrl:    [String, Boolean],
        isFlashing:  Boolean,
        flashType:   { type: String, optional: true },
        isDone:      Boolean,
        accentColor: { type: String, optional: true },
        qtyField:    { type: String, optional: true },
        totalField:  { type: String, optional: true },
    };
    get qty()   { return this.props.line[this.props.qtyField   || "picked_qty"]   ?? 0; }
    get total() { return this.props.line[this.props.totalField || "expected_qty"] ?? 0; }
}

// ── WmsPickScreen ─────────────────────────────────────────────────
export class WmsPickScreen extends Component {
    static template   = "kob_wms.WmsPickScreen";
    static components = { WmsTopNav, WmsPickCard };
    static props      = { ...standardActionServiceProps };

    get accentColor() { return MODE_ACCENT.pick; }
    get activeMode()  { return "pick"; }

    setup() {
        this.orm           = useService("orm");
        this.notification  = useService("notification");
        this.actionService = useService("action");
        this.scanInputRef  = useRef("scanInput");

        this.state = useState({
            orders: [], selectedOrderId: null, currentOrder: null, currentLines: [],
            loading: true, flashLineId: null, flashType: null,
            scanning: false, lastScan: "", lastScanOk: null,
            filterPlatform: "all", searchQuery: "", viewMode: "card",
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

    // ── Navigation ──────────────────────────────────────────────
    goToMode(mode) {
        const action = MODE_ACTIONS[mode];
        if (action) this.actionService.doAction(action);
    }
    onClickBack() { this.actionService.doAction("kob_wms.action_wms_dashboard"); }

    // ── Keyboard / laser scanner ─────────────────────────────────
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
            const code = this._scanBuffer.trim();
            this._scanBuffer = "";
            clearTimeout(this._scanTimer);
            this.onBarcodeScanned(code);
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

    // ── Data ────────────────────────────────────────────────────
    async loadOrders() {
        this.state.loading = true;
        try {
            this.state.orders = await this.orm.searchRead(
                "wms.sales.order",
                [["status", "in", ["pending", "picking"]]],
                ["id", "name", "ref", "customer", "platform", "status",
                 "expected_total", "picked_total", "all_picked",
                 "sla_status", "sla_pick_deadline", "picking_id"],
                { limit: 200, order: "sla_pick_deadline asc, create_date desc" }
            );
        } catch {
            this.notification.add(_t("Failed to load orders"), { type: "danger" });
        }
        this.state.loading = false;
    }

    async selectOrder(order) {
        this.state.selectedOrderId = order.id;
        this.state.currentOrder    = order;
        this.state.lastScan        = "";
        this.state.lastScanOk      = null;
        try {
            this.state.currentLines = await this.orm.searchRead(
                "wms.sales.order.line",
                [["order_id", "=", order.id]],
                ["id", "sku", "product_name", "product_id",
                 "expected_qty", "picked_qty", "product_barcode"],
                { order: "sequence, id" }
            );
        } catch {
            this.notification.add(_t("Failed to load lines"), { type: "danger" });
        }
        this._focusScan();
    }

    deselectOrder() {
        this.state.selectedOrderId = null;
        this.state.currentOrder    = null;
        this.state.currentLines    = [];
        this.state.lastScan        = "";
        this.state.lastScanOk      = null;
        this._focusScan();
    }

    // ── Filtering ────────────────────────────────────────────────
    get filteredOrders() {
        let orders = this.state.orders;
        if (this.state.filterPlatform !== "all")
            orders = orders.filter(o => o.platform === this.state.filterPlatform);
        if (this.state.searchQuery) {
            const q = this.state.searchQuery.toLowerCase();
            orders = orders.filter(o =>
                (o.ref      && o.ref.toLowerCase().includes(q))      ||
                (o.name     && o.name.toLowerCase().includes(q))     ||
                (o.customer && o.customer.toLowerCase().includes(q)));
        }
        return orders;
    }
    get platforms() {
        const set = new Set(this.state.orders.map(o => o.platform).filter(Boolean));
        return ["all", ...set];
    }
    setFilter(p)      { this.state.filterPlatform = p; }
    onSearchInput(ev) { this.state.searchQuery = ev.target.value; }

    // ── Barcode scan ─────────────────────────────────────────────
    async onBarcodeScanned(code) {
        if (this.state.scanning) return;
        this.state.lastScan = code;

        if (!this.state.selectedOrderId) {
            let match = this.state.orders.find(o => o.ref === code || o.name === code)
                     || this.state.orders.find(o =>
                            (o.ref  && o.ref.includes(code)) ||
                            (o.name && o.name.includes(code)));
            if (!match) {
                try {
                    const r = await this.orm.searchRead("wms.sales.order",
                        ["|", "|", ["ref", "=", code], ["name", "=", code], ["ref", "ilike", code]],
                        ["id", "name", "ref", "customer", "platform", "status",
                         "expected_total", "picked_total", "all_picked",
                         "sla_status", "sla_pick_deadline", "picking_id"],
                        { limit: 1 });
                    if (r.length) match = r[0];
                } catch {}
            }
            if (match) {
                await this.selectOrder(match);
                this.state.lastScanOk = true;
                this.notification.add(code + " → " + (match.ref || match.name), { type: "success" });
            } else {
                this.state.lastScanOk = false;
                this.notification.add(_t("Order not found: ") + code, { type: "danger" });
            }
            return;
        }

        this.state.scanning = true;
        const _wmsWorker = (() => { try { return JSON.parse(localStorage.getItem("wms_worker") || "{}"); } catch(e) { return {}; } })();
        try {
            const result = await this.orm.call(
                "wms.sales.order", "scan_pick",
                [[this.state.selectedOrderId], code, _wmsWorker.id || false]);
            if (result && result.ok) {
                const codeUpper = code.toUpperCase();
                const line = this.state.currentLines.find(l =>
                    (l.sku && l.sku.toUpperCase() === codeUpper) ||
                    (l.product_barcode && l.product_barcode === code));
                if (line) {
                    this.state.flashLineId = line.id;
                    this.state.flashType   = "success";
                    setTimeout(() => { this.state.flashLineId = null; this.state.flashType = null; }, 850);
                }
                this.state.lastScanOk = true;
                await this._reloadCurrent();
                if (this.state.currentOrder && this.state.currentOrder.all_picked) {
                    this.notification.add(
                        (this.state.currentOrder.ref || this.state.currentOrder.name) + " — All picked! ✓",
                        { type: "success" });
                }
            } else {
                this.state.lastScanOk = false;
                this.state.flashType  = "error";
                setTimeout(() => { this.state.flashType = null; }, 850);
                this.notification.add((result && result.error) || "Scan error", { type: "danger" });
            }
        } catch (e) {
            if (e.event) e.event.preventDefault();
            this.state.lastScanOk = false;
            this.notification.add("Scan error", { type: "danger" });
        }
        this.state.scanning = false;
        this._focusScan();
    }

    async _reloadCurrent() {
        if (!this.state.selectedOrderId) return;
        const orders = await this.orm.searchRead("wms.sales.order",
            [["id", "=", this.state.selectedOrderId]],
            ["id", "name", "ref", "customer", "platform", "status",
             "expected_total", "picked_total", "all_picked",
             "sla_status", "sla_pick_deadline", "picking_id"]);
        if (orders.length) this.state.currentOrder = orders[0];
        this.state.currentLines = await this.orm.searchRead("wms.sales.order.line",
            [["order_id", "=", this.state.selectedOrderId]],
            ["id", "sku", "product_name", "product_id",
             "expected_qty", "picked_qty", "product_barcode"],
            { order: "sequence, id" });
        await this.loadOrders();
    }

    async completePick() {
        if (!this.state.currentOrder || !this.state.currentOrder.all_picked) return;
        this.notification.add(
            (this.state.currentOrder.ref || this.state.currentOrder.name) + " — Picking complete!",
            { type: "success" });
        this.deselectOrder();
        await this.loadOrders();
    }

    // ── Helpers ──────────────────────────────────────────────────
    get progressPct() {
        const o = this.state.currentOrder;
        if (!o || !o.expected_total) return 0;
        return Math.round((o.picked_total / o.expected_total) * 100);
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
        if (!order.expected_total) return 0;
        return Math.round((order.picked_total / order.expected_total) * 100);
    }
}

registry.category("actions").add("kob_wms.pick_screen", WmsPickScreen);
