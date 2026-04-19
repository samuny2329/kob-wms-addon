/** @odoo-module **/

import { Component, useState, useRef, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

const ORDER_FIELDS = [
    "id", "name", "ref", "customer", "platform", "courier_id",
    "awb", "box_barcode", "status", "expected_total", "picked_total",
    "packed_total", "all_picked", "all_packed", "sla_status",
];

const LINE_FIELDS = [
    "id", "sku", "product_name", "expected_qty", "picked_qty", "packed_qty",
];

export class WmsScanScreen extends Component {
    static template = "kob_wms.WmsScanScreen";
    static props = {
        "*": true,
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");
        this.scanInputRef = useRef("scanInput");

        this.state = useState({
            orders: [],
            currentOrder: null,
            currentLines: [],
            mode: this.props.action?.context?.default_mode || "pick",
            scanValue: "",
            history: [],
            loading: true,
            activeTab: "items",   // items | activity | flow
        });

        // Workflow steps for the Flow / ERD tab
        this.FLOW_STEPS = [
            { key: "pending",  label: "Pending",  icon: "📥", desc: "Synced from platform" },
            { key: "picking",  label: "Picking",  icon: "📦", desc: "Worker picking items" },
            { key: "picked",   label: "Picked",   icon: "✓",  desc: "All items picked" },
            { key: "packing",  label: "Packing",  icon: "🗂", desc: "Worker packing items" },
            { key: "packed",   label: "Packed",   icon: "📮", desc: "Box closed" },
            { key: "shipped",  label: "Shipped",  icon: "🚚", desc: "Dispatched to courier" },
        ];

        // Status → mode tab mapping. When an order transitions between
        // states the screen auto-advances to the correct tab.
        this.STATUS_TO_MODE = {
            pending:  "pick",
            picking:  "pick",
            picked:   "pack",
            packing:  "pack",   // overridden to 'box' when all_packed=True
            packed:   "ship",
            shipped:  "ship",
            cancelled: "pick",
        };

        // Per-mode independent state — selected order, scan input and
        // history don't cross-contaminate between modes.
        this.modeState = {
            pick: { selectedId: null, history: [] },
            pack: { selectedId: null, history: [] },
            box:  { selectedId: null, history: [] },
            ship: { selectedId: null, history: [] },
        };

        onMounted(async () => {
            await this.loadOrders();
            this._focus();
        });
    }

    // ------------------------------------------------------------------
    // Flow helpers — map order status to the correct mode tab
    // ------------------------------------------------------------------
    _modeForStatus(order) {
        if (!order) return this.state.mode;
        // Special case: order in "packing" state with all items packed
        // → ready to Close Box
        if (order.status === "packing" && order.all_packed) return "box";
        return this.STATUS_TO_MODE[order.status] || this.state.mode;
    }

    _saveCurrentModeState() {
        // Persist the currently-selected order + history into its mode bucket
        this.modeState[this.state.mode] = {
            selectedId: this.state.currentOrder?.id || null,
            history: [...this.state.history],
        };
    }

    _restoreModeState(mode) {
        const saved = this.modeState[mode] || { selectedId: null, history: [] };
        this.state.history = saved.history;
        return saved.selectedId;
    }

    // ------------------------------------------------------------------
    // Data loading
    // ------------------------------------------------------------------
    _domainForMode() {
        switch (this.state.mode) {
            case "pick":
                return [["status", "in", ["pending", "picking"]]];
            case "pack":
                return [["status", "in", ["picked", "packing"]]];
            case "box":
                return [["status", "=", "packing"]];
            case "ship":
                return [["status", "=", "packed"]];
            default:
                // Guard: unknown mode — return impossible domain instead of [] (which loads ALL orders)
                console.warn("[WMS] _domainForMode: unknown mode:", this.state.mode);
                return [["id", "=", 0]];
        }
    }

    async loadOrders(opts = {}) {
        this.state.loading = true;
        try {
            const orders = await this.orm.searchRead(
                "wms.sales.order",
                this._domainForMode(),
                ORDER_FIELDS,
                { limit: 100, order: "sla_pick_deadline asc, create_date desc" }
            );
            this.state.orders = orders;

            // Try to restore this mode's last selected order if possible
            const savedId = this.modeState[this.state.mode]?.selectedId;
            const savedOrder = savedId && orders.find(o => o.id === savedId);
            const fallbackCurrent = this.state.currentOrder
                && orders.find(o => o.id === this.state.currentOrder.id);
            const preferred = opts.forceSelectId
                ? orders.find(o => o.id === opts.forceSelectId)
                : savedOrder || fallbackCurrent || orders[0];

            if (preferred) {
                await this.selectOrder(preferred, { skipAutoMode: true });
            } else {
                this.state.currentOrder = null;
                this.state.currentLines = [];
            }
        } catch (err) {
            this.notification.add(err.data?.message || err.message, { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    async selectOrder(order, opts = {}) {
        // Auto-advance to the mode that matches this order's status —
        // "แถบใครแถบมัน — วิ่งตาม Flow"
        if (!opts.skipAutoMode) {
            const targetMode = this._modeForStatus(order);
            if (targetMode !== this.state.mode) {
                this._saveCurrentModeState();
                this.state.mode = targetMode;
                this._restoreModeState(targetMode);
                // reload the queue for the new mode but keep THIS order selected
                await this.loadOrders({ forceSelectId: order.id });
                return;
            }
        }

        this.state.currentOrder = order;
        this.modeState[this.state.mode].selectedId = order.id;
        const lines = await this.orm.searchRead(
            "wms.sales.order.line",
            [["order_id", "=", order.id]],
            LINE_FIELDS,
            { order: "sequence, id" }
        );
        this.state.currentLines = lines;
        this._focus();
    }

    async _reloadCurrent() {
        if (!this.state.currentOrder) return;
        const [updated] = await this.orm.searchRead(
            "wms.sales.order",
            [["id", "=", this.state.currentOrder.id]],
            ORDER_FIELDS,
        );
        if (!updated) return;

        // Has the status advanced past this mode? If so, auto-switch to
        // the next tab so the worker always sees the right queue.
        const targetMode = this._modeForStatus(updated);
        if (targetMode !== this.state.mode) {
            this.notification.add(
                _t("Order advanced to %(mode)s stage ✓", { mode: targetMode.toUpperCase() }),
                { type: "info" },
            );
            this._saveCurrentModeState();
            // Carry the selected order into the next mode so scanning
            // continues on the same order
            this.modeState[targetMode].selectedId = updated.id;
            this.state.mode = targetMode;
            this._restoreModeState(targetMode);
            await this.loadOrders({ forceSelectId: updated.id });
            return;
        }

        // Otherwise just refresh the current row + queue badges
        this.state.currentOrder = updated;
        const lines = await this.orm.searchRead(
            "wms.sales.order.line",
            [["order_id", "=", updated.id]],
            LINE_FIELDS,
            { order: "sequence, id" },
        );
        this.state.currentLines = lines;

        const ids = this.state.orders.map(o => o.id);
        if (ids.length) {
            const updatedAll = await this.orm.searchRead(
                "wms.sales.order",
                [["id", "in", ids]],
                ORDER_FIELDS,
            );
            const map = new Map(updatedAll.map(o => [o.id, o]));
            this.state.orders = this.state.orders.map(o => map.get(o.id) || o);
        }
    }

    // ------------------------------------------------------------------
    // UI handlers
    // ------------------------------------------------------------------
    async setMode(mode) {
        if (mode === this.state.mode) return;
        this._saveCurrentModeState();
        this.state.mode = mode;
        this._restoreModeState(mode);
        await this.loadOrders();
    }

    async onScanKeydown(ev) {
        if (ev.key !== "Enter") return;
        ev.preventDefault();
        await this.doScan();
    }

    async doScan() {
        const code = (this.state.scanValue || "").trim();
        if (!code) {
            this.notification.add(_t("Please scan or type a barcode first."), {
                type: "warning",
            });
            this._focus();
            return;
        }
        if (!this.state.currentOrder) {
            this.notification.add(_t("No order selected."), { type: "warning" });
            return;
        }

        const method = this.state.mode === "pick" ? "scan_pick"
            : this.state.mode === "pack" ? "scan_pack"
                : this.state.mode === "box" ? "close_box"
                    : null;

        if (!method) {
            this.notification.add(_t("Switch to pick/pack/box mode first."), {
                type: "warning",
            });
            return;
        }

        const now = new Date().toLocaleTimeString();
        try {
            await this.orm.call(
                "wms.sales.order",
                method,
                [[this.state.currentOrder.id], code],
            );
            this.state.history.unshift({
                mode: this.state.mode,
                code,
                time: now,
                ok: true,
            });
            this.state.history = this.state.history.slice(0, 30);
            this.notification.add(`✓ ${this.state.mode.toUpperCase()}: ${code}`, {
                type: "success",
            });
            this.state.scanValue = "";
            await this._reloadCurrent();
        } catch (err) {
            const msg = err.data?.message || err.message || "Unknown error";
            this.state.history.unshift({
                mode: this.state.mode,
                code,
                time: now,
                ok: false,
                error: msg,
            });
            this.state.history = this.state.history.slice(0, 30);
            this.notification.add(`✗ ${msg}`, { type: "danger" });
            this.state.scanValue = "";
        }
        this._focus();
    }

    async shipOrder() {
        if (!this.state.currentOrder) return;
        try {
            await this.orm.call(
                "wms.sales.order",
                "action_ship",
                [[this.state.currentOrder.id]],
            );
            this.notification.add(_t("Order shipped ✓"), { type: "success" });
            await this.loadOrders();
        } catch (err) {
            this.notification.add(err.data?.message || err.message, { type: "danger" });
        }
    }

    async openFormView() {
        if (!this.state.currentOrder) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "wms.sales.order",
            res_id: this.state.currentOrder.id,
            view_mode: "form",
            views: [[false, "form"]],
            target: "current",
        });
    }

    async printReport(reportRef) {
        if (!this.state.currentOrder) return;
        this.action.doAction({
            type: "ir.actions.report",
            report_name: reportRef,
            report_type: "qweb-pdf",
            context: { active_ids: [this.state.currentOrder.id] },
        });
    }

    _focus() {
        setTimeout(() => {
            if (this.scanInputRef.el) {
                this.scanInputRef.el.focus();
                this.scanInputRef.el.select();
            }
        }, 50);
    }

    // ------------------------------------------------------------------
    // Helpers for template
    // ------------------------------------------------------------------
    lineProgress(line) {
        if (this.state.mode === "pack") {
            const total = line.picked_qty || line.expected_qty || 1;
            const done = line.packed_qty || 0;
            return { done, total, pct: total ? (done / total) * 100 : 0 };
        }
        return {
            done: line.picked_qty || 0,
            total: line.expected_qty || 1,
            pct: line.expected_qty ? (line.picked_qty / line.expected_qty) * 100 : 0,
        };
    }

    lineIsDone(line) {
        const p = this.lineProgress(line);
        return p.done >= p.total && p.total > 0;
    }

    courierLabel(order) {
        if (order?.courier_id && Array.isArray(order.courier_id)) {
            return order.courier_id[1];
        }
        return "—";
    }

    slaClass(order) {
        return {
            on_track: "sla-ok",
            at_risk: "sla-warn",
            breached: "sla-bad",
            done: "sla-done",
        }[order?.sla_status] || "";
    }

    platformLabel(order) {
        return (order?.platform || "").toUpperCase();
    }

    canShip() {
        return this.state.currentOrder?.status === "packed";
    }

    progressPct() {
        const o = this.state.currentOrder;
        if (!o || !o.expected_total) return 0;
        const done = this.state.mode === "pack"
            ? (o.packed_total || 0)
            : (o.picked_total || 0);
        return Math.min(100, Math.round((done / o.expected_total) * 100));
    }

    setTab(tab) {
        this.state.activeTab = tab;
    }

    flowStepClass(stepKey) {
        const current = this.state.currentOrder?.status;
        if (!current) return "pending";
        const order = ["pending", "picking", "picked", "packing", "packed", "shipped"];
        const currentIdx = order.indexOf(current);
        const stepIdx = order.indexOf(stepKey);
        if (stepIdx < currentIdx) return "done";
        if (stepIdx === currentIdx) return "active";
        return "pending";
    }
}

registry.category("actions").add("kob_wms.scan_screen", WmsScanScreen);
