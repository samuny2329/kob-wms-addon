/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { Component, useState, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import {
    WmsTopNav,
    MODE_ACTIONS, MODE_ACCENT,
} from "../wms_pick_pos/wms_pick_screen";

export class WmsDispatchScreen extends Component {
    static template   = "kob_wms.WmsDispatchScreen";
    static components = { WmsTopNav };
    static props      = { ...standardActionServiceProps };

    get accentColor() { return MODE_ACCENT.dispatch; }
    get activeMode()  { return "dispatch"; }

    setup() {
        this.orm           = useService("orm");
        this.notification  = useService("notification");
        this.actionService = useService("action");
        this.scanInputRef  = useRef("scanInput");
        this.successSound  = new Audio("/point_of_sale/static/src/sounds/bell.wav");

        this.state = useState({
            batches: [], selectedBatchId: null, currentBatch: null, scanItems: [],
            loading: true, lastScan: "", lastScanOk: null, dispatching: false,
            // Courier picker
            couriers: [], showCourierPicker: false,
        });

        this._scanBuffer = "";
        this._scanTimer  = null;
        this._globalKeyHandler = this._onGlobalKey.bind(this);
        this._rejectHandler    = (ev) => { ev.preventDefault(); ev.stopImmediatePropagation(); };

        onMounted(() => {
            this.loadBatches();
            this.loadCouriers();
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
        if (ev.key === "Escape") { this.deselectBatch(); return; }
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

    async loadBatches() {
        this.state.loading = true;
        this.state.batches = await this.orm.searchRead("wms.courier.batch",
            [["state", "in", ["draft", "scanning"]]],
            ["id", "name", "courier_id", "state", "scan_item_ids", "dispatched_at"],
            { limit: 50, order: "create_date desc" });
        this.state.loading = false;
    }

    async selectBatch(batch) {
        this.state.selectedBatchId = batch.id;
        this.state.currentBatch    = batch;
        if (batch.scan_item_ids && batch.scan_item_ids.length) {
            this.state.scanItems = await this.orm.searchRead("wms.scan.item",
                [["batch_id", "=", batch.id]],
                ["id", "barcode", "order_ref", "shop_name", "courier_id"],
                { order: "id desc" });
        } else {
            this.state.scanItems = [];
        }
        this._focusScan();
    }

    deselectBatch() {
        this.state.selectedBatchId = null;
        this.state.currentBatch    = null;
        this.state.scanItems       = [];
        this._focusScan();
    }

    async onBarcodeScanned(code) {
        this.state.lastScan = code;

        if (!this.state.selectedBatchId) {
            const match = this.state.batches.find(b => b.name === code);
            if (match) {
                await this.selectBatch(match);
                this.state.lastScanOk = true;
            } else {
                this.state.lastScanOk = false;
                this.notification.add(_t("Batch not found: ") + code, { type: "danger" });
            }
            return;
        }

        // Scan AWB into batch
        const items = await this.orm.searchRead("wms.scan.item",
            [["barcode", "=", code], ["batch_id", "=", false]],
            ["id", "barcode", "order_ref", "shop_name"],
            { limit: 1 });

        if (items.length) {
            await this.orm.write("wms.scan.item", [items[0].id],
                { batch_id: this.state.selectedBatchId });
            this.state.lastScanOk = true;
            this.successSound.currentTime = 0;
            try { this.successSound.play(); } catch {}
            this.notification.add(_t("Added: ") + code, { type: "success" });
            await this.selectBatch(this.state.currentBatch);
        } else {
            this.state.lastScanOk = false;
            this.notification.add(_t("AWB not found or already in batch: ") + code, { type: "danger" });
        }
        this._focusScan();
    }

    async loadCouriers() {
        this.state.couriers = await this.orm.searchRead(
            "wms.courier", [["active", "=", true]],
            ["id", "name"], { order: "name asc", limit: 50 });
    }

    createBatch() {
        // Show inline courier picker instead of creating directly
        this.state.showCourierPicker = true;
    }

    cancelCourierPicker() {
        this.state.showCourierPicker = false;
    }

    async confirmCreateBatch(courierId) {
        this.state.showCourierPicker = false;
        const id = await this.orm.create("wms.courier.batch", [{
            state: "scanning",
            courier_id: courierId,
        }]);
        await this.loadBatches();
        const batch = this.state.batches.find(b => b.id === id);
        if (batch) await this.selectBatch(batch);
    }

    async dispatchBatch() {
        if (!this.state.selectedBatchId || this.state.dispatching) return;
        this.state.dispatching = true;
        const result = await this.orm.call("wms.courier.batch", "action_dispatch",
            [[this.state.selectedBatchId]]);
        if (result) {
            this.notification.add(_t("Batch dispatched successfully!"), { type: "success" });
            this.deselectBatch();
            await this.loadBatches();
        }
        this.state.dispatching = false;
    }

    getBatchStateClass(state) {
        if (state === "scanning") return "badge text-bg-warning";
        if (state === "done")     return "badge text-bg-success";
        return "badge text-bg-secondary";
    }
}

registry.category("actions").add("kob_wms.dispatch_screen", WmsDispatchScreen);
