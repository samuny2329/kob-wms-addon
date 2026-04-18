/** @odoo-module **/
/**
 * WMS Count Screen — Step-by-step guided inventory count
 * Works on desktop list view, mobile (360px), and handheld scanners.
 *
 * FLOW:
 *   tasks  → navigate  → count (product-by-product / lot-by-lot) → summary
 */
import { registry }                    from "@web/core/registry";
import { useService }                   from "@web/core/utils/hooks";
import { _t }                           from "@web/core/l10n/translation";
import { Component, useState, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { standardActionServiceProps }   from "@web/webclient/actions/action_service";

// ── helpers ──────────────────────────────────────────────────────────────────

function groupByProduct(quants) {
    /** [{product_id, product_name, product_code, lot_id, lot_name, expected_qty}]
     *  → [{product_id, product_name, product_code, lots: [{lot_id, lot_name, expected_qty, counted_qty}]}]
     */
    const map = {};
    for (const q of quants) {
        if (!map[q.product_id]) {
            map[q.product_id] = {
                product_id:   q.product_id,
                product_name: q.product_name,
                product_code: q.product_code,
                barcode:      q.barcode,
                lots: [],
            };
        }
        map[q.product_id].lots.push({
            lot_id:       q.lot_id,
            lot_name:     q.lot_name || "(ไม่มี Lot)",
            lot_ref:      q.lot_ref  || "",
            expiry_date:  q.expiry_date || "",
            expected_qty: q.expected_qty,
            counted_qty:  q.expected_qty,   // pre-fill with expected
            _key:         `${q.product_id}_${q.lot_id || 0}`,
        });
    }
    return Object.values(map);
}

function calcVariance(products) {
    let total = 0;
    for (const p of products) {
        for (const l of p.lots) {
            total += l.counted_qty - l.expected_qty;
        }
    }
    return total;
}

// ── Component ─────────────────────────────────────────────────────────────────

export class WmsCountScreen extends Component {
    static template = "kob_wms.WmsCountScreen";
    static props    = { ...standardActionServiceProps };

    setup() {
        this.orm           = useService("orm");
        this.notification  = useService("notification");
        this.actionService = useService("action");
        this.scanRef       = useRef("scanInput");

        this.state = useState({
            // screen: 'tasks' | 'navigate' | 'count' | 'summary'
            screen: "tasks",
            loading: true,
            submitting: false,

            // task list
            tasks: [],

            // selected task
            task: null,           // full task dict from get_my_count_tasks

            // count data (grouped by product)
            products: [],         // [{product_id, product_name, lots: [...]}]
            productIdx: 0,        // which product we're on

            // scan
            scanBuffer: "",
            scanFlash: null,      // 'ok' | 'error' | null

            // lot picker (bottom sheet)
            lotPicker: {
                visible: false,
                loading: false,
                product: null,    // product object being expanded
                results: [],      // [{lot_id, lot_name, lot_ref, expiry_date, qty}]
            },

            // summary
            submitDone: false,
        });

        this._scanTimer = null;
        this._keyHandler = this._onKey.bind(this);

        // Bind methods used with argument-passing arrow wrappers in the OWL
        // template (e.g. () => goToMode('...')).  OWL 2 destructures these
        // from `this`, so the method loses its `this` binding without this.
        this.goToMode       = this.goToMode.bind(this);
        this.selectTask     = this.selectTask.bind(this);
        this.adjustQty      = this.adjustQty.bind(this);
        this.setQty         = this.setQty.bind(this);
        this.openLotPicker  = this.openLotPicker.bind(this);
        this.pickLot        = this.pickLot.bind(this);
        this.closeLotPicker = this.closeLotPicker.bind(this);
        this._focusScan     = this._focusScan.bind(this);

        onMounted(async () => {
            document.addEventListener("keydown", this._keyHandler, true);
            await this.loadTasks();
        });
        onWillUnmount(() => {
            document.removeEventListener("keydown", this._keyHandler, true);
            if (this._scanTimer) clearTimeout(this._scanTimer);
        });
    }

    // ── Data loading ──────────────────────────────────────────────────────────

    async loadTasks() {
        this.state.loading = true;
        try {
            const kob_id = this._getKobUserId();
            const tasks = await this.orm.call(
                "wms.count.task", "get_my_count_tasks",
                [], { kob_user_id: kob_id }
            );
            this.state.tasks = tasks;
        } catch (e) {
            this.notification.add(_t("Cannot load count tasks: ") + e.message, { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    async selectTask(task) {
        this.state.loading = true;
        this.state.task    = task;
        this.state.screen  = "navigate";
        try {
            const res = await this.orm.call(
                "wms.count.task", "start_counting", [[task.id]]
            );
            if (!res.ok) {
                this.notification.add(res.error || _t("Cannot start counting."), { type: "danger" });
                this.state.screen = "tasks";
                return;
            }
            this.state.products   = groupByProduct(res.quants);
            this.state.productIdx = 0;
        } catch (e) {
            this.notification.add(_t("Cannot start counting."), { type: "danger" });
            this.state.screen = "tasks";
        } finally {
            this.state.loading = false;
        }
    }

    // ── Navigation ────────────────────────────────────────────────────────────

    goNavigate()  { this.state.screen = "navigate"; }
    goCount()     { this.state.screen = "count"; this.state.productIdx = 0; this._focusScan(); }
    goSummary()   { this.state.screen = "summary"; }
    backToTasks() { this.state.screen = "tasks"; this.state.task = null; this.state.products = []; }

    prevProduct() {
        if (this.state.productIdx > 0) this.state.productIdx--;
    }
    nextProduct() {
        const max = this.state.products.length - 1;
        if (this.state.productIdx < max) {
            this.state.productIdx++;
        } else {
            this.goSummary();
        }
    }

    // ── Current product helpers ───────────────────────────────────────────────

    get currentProduct() {
        return this.state.products[this.state.productIdx] || null;
    }

    get progressLabel() {
        return `${this.state.productIdx + 1} / ${this.state.products.length}`;
    }

    // ── Lot quantity editing ──────────────────────────────────────────────────

    adjustQty(lot, delta) {
        const val = (lot.counted_qty || 0) + delta;
        lot.counted_qty = Math.max(0, val);
    }

    setQty(lot, ev) {
        const v = parseFloat(ev.target.value);
        lot.counted_qty = isNaN(v) ? 0 : Math.max(0, v);
    }

    // ── Lot picker (bottom sheet) ─────────────────────────────────────────

    async openLotPicker(product) {
        this.state.lotPicker.product = product;
        this.state.lotPicker.results = [];
        this.state.lotPicker.loading = true;
        this.state.lotPicker.visible = true;
        try {
            const task = this.state.task;
            const lots = await this.orm.call(
                "wms.count.task", "search_lots_for_product",
                [], { product_id: product.product_id, location_id: task.location_id || false }
            );
            this.state.lotPicker.results = lots;
        } catch (e) {
            this.notification.add(_t("ไม่สามารถโหลด Lot ได้"), { type: "warning" });
        } finally {
            this.state.lotPicker.loading = false;
        }
    }

    pickLot(lotData) {
        const product = this.state.lotPicker.product;
        if (!product) return;
        const existing = product.lots.find(l => l.lot_id === lotData.lot_id);
        if (existing) {
            this.notification.add(`${lotData.lot_name} มีในรายการแล้ว`, { type: "info" });
        } else {
            product.lots.push({
                lot_id:       lotData.lot_id,
                lot_name:     lotData.lot_name,
                lot_ref:      lotData.lot_ref,
                expiry_date:  lotData.expiry_date,
                expected_qty: lotData.qty,
                counted_qty:  0,
                _key:         `picked_${lotData.lot_id}`,
            });
        }
        this.state.lotPicker.visible = false;
    }

    closeLotPicker() {
        this.state.lotPicker.visible = false;
    }

    addUnknownLot(product) {
        const lotName = prompt(_t("ชื่อ Lot ที่พบ (ไม่มีในระบบ):"));
        if (!lotName) return;
        product.lots.push({
            lot_id:       false,
            lot_name:     lotName,
            lot_ref:      "",
            expiry_date:  "",
            expected_qty: 0,
            counted_qty:  1,
            _key:         `new_${Date.now()}`,
        });
    }

    // ── Barcode scanner ───────────────────────────────────────────────────────

    _focusScan() {
        setTimeout(() => {
            if (this.scanRef.el) this.scanRef.el.focus();
        }, 150);
    }

    _onKey(ev) {
        if (this.state.screen !== "count") return;
        if (ev.key === "Enter") {
            ev.preventDefault();
            if (this.state.scanBuffer) this._processScan(this.state.scanBuffer);
            this.state.scanBuffer = "";
            if (this._scanTimer) { clearTimeout(this._scanTimer); this._scanTimer = null; }
            return;
        }
        if (ev.key.length === 1) {
            this.state.scanBuffer += ev.key;
            if (this._scanTimer) clearTimeout(this._scanTimer);
            this._scanTimer = setTimeout(() => {
                if (this.state.scanBuffer.length > 2) {
                    this._processScan(this.state.scanBuffer);
                }
                this.state.scanBuffer = "";
                this._scanTimer = null;
            }, 300);
        }
    }

    async _processScan(barcode) {
        const task = this.state.task;
        // Scan product barcode → navigate to that product in the count list
        const result = await this.orm.call(
            "wms.count.task", "resolve_product_barcode",
            [], { barcode, location_id: task.location_id || false }
        );
        if (!result.ok) {
            this.state.scanFlash = "error";
            this.notification.add(_t("ไม่พบสินค้า: ") + barcode, { type: "warning" });
            setTimeout(() => { this.state.scanFlash = null; }, 1200);
            return;
        }
        const pid = result.product_id;
        let idx = this.state.products.findIndex(p => p.product_id === pid);
        if (idx === -1) {
            // Product not in snapshot — add with empty lots
            this.state.products.push({
                product_id:   pid,
                product_name: result.product_name,
                product_code: result.product_code,
                barcode:      result.barcode,
                lots: [],
            });
            idx = this.state.products.length - 1;
            this.notification.add(
                `📦 ${result.product_name} — เพิ่มสินค้าใหม่`, { type: "info" }
            );
        } else {
            this.notification.add(
                `📦 ${result.product_name}`, { type: "success" }
            );
        }
        this.state.productIdx = idx;
        this.state.scanFlash = "ok";
        setTimeout(() => { this.state.scanFlash = null; }, 1000);
    }

    // ── Submit ────────────────────────────────────────────────────────────────

    get totalVariance() {
        return calcVariance(this.state.products);
    }

    buildEntries() {
        const entries = [];
        for (const p of this.state.products) {
            for (const l of p.lots) {
                entries.push({
                    product_id: p.product_id,
                    lot_id:     l.lot_id || false,
                    qty:        l.counted_qty,
                    barcode:    "",
                });
            }
        }
        return entries;
    }

    async submitCount() {
        if (this.state.submitting) return;
        this.state.submitting = true;
        try {
            const result = await this.orm.call(
                "wms.count.task", "submit_count_entries",
                [], {
                    task_id: this.state.task.id,
                    entries: this.buildEntries(),
                }
            );
            if (result.ok) {
                this.state.submitDone = true;
                this.notification.add(
                    _t("ส่งผลนับสำเร็จ: ") + result.task_name, { type: "success" }
                );
                // Refresh task list
                setTimeout(() => this.loadTasks(), 1500);
            } else {
                this.notification.add(result.error || _t("เกิดข้อผิดพลาด"), { type: "danger" });
            }
        } finally {
            this.state.submitting = false;
        }
    }

    backAfterSubmit() {
        this.state.submitDone = false;
        this.state.screen = "tasks";
        this.state.task   = null;
        this.state.products = [];
    }

    // ── Internal helpers ──────────────────────────────────────────────────────

    _getKobUserId() {
        try {
            return window._wmsKobUserId || null;
        } catch { return null; }
    }

    goToMode(action_ref) {
        this.actionService.doAction(action_ref);
    }
}

registry.category("actions").add("kob_wms.action_wms_count_screen", WmsCountScreen);
