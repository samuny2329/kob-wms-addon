# KOB WMS Pro — Claude Project Context

> วางไฟล์นี้ในโฟลเดอร์ `kob_wms/` หรือ root ของ project
> แล้วบอก Claude ว่า "อ่าน CLAUDE.md ก่อนแล้วช่วยต่อ"

---

## 1. Project Identity

| Field | Value |
|-------|-------|
| **Module name** | `kob_wms` |
| **Display name** | KOB WMS Pro |
| **Version** | `18.0.2.16.0` (see `__manifest__.py` for current) |
| **Company** | Kiss of Beauty (KOB) / SKINOXY |
| **Author** | KOB — sivaporn.t@kissofbeauty.co.th |
| **GitHub** | https://github.com/samuny2329/kob-wms |
| **Odoo version** | 18.0 |
| **License** | LGPL-3 |

---

## 2. Business Context

KOB คือธุรกิจ e-commerce ขายเครื่องสำอาง แบรนด์ Kiss of Beauty และ SKINOXY
ขายผ่าน Shopee, Lazada, TikTok, Odoo (B2B), POS (หน้าร้าน), Manual

**WMS นี้คือระบบคลังสินค้าแบบ fullscreen scan-based:**
- Worker scan barcode ที่หน้าจอ Pick / Pack / Outbound / Dispatch
- ระบบตัด stock อัตโนมัติเมื่อ pack เสร็จ
- ออก invoice อัตโนมัติ
- พิมพ์ AWB label
- Track SLA per platform

---

## 3. Tech Stack & Environment

### Odoo
```
Version  : Odoo 18.0 (Community)
Port     : 8018
DB name  : odoo18_db
Config   : config/odoo18_local.conf
```

### PostgreSQL
```
Host     : 127.0.0.1
Port     : 5433   ← non-default!
User     : odoo
Password : odoo
DB       : odoo18_db
```

### Python
```
venv path: venv/  (ใน odoo-18.0 folder)
```

### odoo18_local.conf (สำคัญ)
```ini
[options]
admin_passwd = admin
db_host = 127.0.0.1
db_port = 5433
db_user = odoo
db_password = odoo
db_name = odoo18_db
addons_path = addons,odoo/addons,
              odoo-19.0/manufacture-18.0,
              odoo-19.0/stock-logistics-warehouse-18.0,
              odoo-19.0/stock-logistics-reporting-18.0,
              custom_addons
http_port = 8018
data_dir  = data/
```

### Start Odoo
```bash
cd odoo-18.0
venv/Scripts/python odoo-bin -c config/odoo18_local.conf
```

### Upgrade kob_wms
```bash
venv/Scripts/python odoo-bin -c config/odoo18_local.conf \
  -u kob_wms -d odoo18_db --stop-after-init
```

---

## 4. Module Structure

```
kob_wms/
├── __manifest__.py          v18.0.2.11.0
├── __init__.py
├── CLAUDE.md                ← this file
├── .gitignore
│
├── models/
│   ├── wms_sales_order.py   ← core fulfilment logic (Pick/Pack/Ship)
│   ├── wms_sales_order_line.py (inside wms_sales_order.py)
│   ├── wms_box_size.py      ← 28 THE BOX sizes, tape/bubble cost
│   ├── wms_box_analytics.py ← SQL view: 360° box usage analytics
│   ├── wms_product_box_analytics.py ← SQL view: product vs box
│   ├── wms_count_session.py ← cycle count session
│   ├── wms_count_task.py
│   ├── wms_count_entry.py
│   ├── wms_count_adjustment.py
│   ├── wms_count_snapshot.py
│   ├── wms_count_auto.py
│   ├── wms_courier.py
│   ├── wms_courier_batch.py
│   ├── wms_activity_log.py
│   ├── wms_worker_performance.py
│   ├── wms_kpi_target.py
│   ├── wms_sla_config.py
│   ├── wms_api_config.py
│   ├── wms_inventory_extra.py
│   ├── wms_zone.py / wms_rack.py / wms_pickface.py
│   ├── kob_wms_user.py      ← WMS Worker (PIN login, role)
│   ├── stock_picking.py     ← inherit stock.picking
│   ├── pos_config.py / pos_order.py
│   └── wms_zone.py
│
├── wizards/
│   ├── wms_scan_wizard.py
│   ├── wms_cancel_return_wizard.py
│   ├── wms_user_set_password.py
│   └── wms_box_recommender_wizard.py  ← NEW v2.11
│
├── views/          (31 XML files)
├── report/         (7 QWeb PDF templates)
├── data/           (master data + dashboard JSON)
├── security/
└── static/src/js/  (OWL fulfilment screens)
```

---

## 5. Key Features (ทั้งหมดที่สร้างแล้ว)

### 5.1 Fulfilment Workflow (fullscreen OWL screens)
| Screen | Hotkey | Action |
|--------|--------|--------|
| Pick | F1 | Scan SKU → ++ picked_qty |
| Pack | F2 | Scan SKU → ++ packed_qty |
| Outbound | F3 | Scan AWB → ship |
| Dispatch | F4 | Courier batch |
| Count | F5 | Guided cycle count |

**Flow:** Pending → Picking → Picked → Packing → Packed → Shipped

### 5.2 Stock Integration (critical)
```python
# wms_sales_order.py → _validate_picking()
# เรียกเมื่อ select_box_and_close() / close_box()
# Key fix (v2.11): 
#   ml.quantity = ml.quantity_product_uom  ← done = reserved (NOT move demand)
#   context: skip_immediate=True, skip_backorder=True
#   verify: check picking.state == 'done' after button_validate()
```

### 5.3 Box Sizing
- 28 sizes จาก THE BOX price list
- Tape formula: `(W+H)×2 × rounds + overlap_cm` → metres → ฿
- Bubble wrap: manual per size
- Total pack cost: box + tape + bubble
- **Auto-suggest**: `get_recommended_box()` → volume-based + item-count fallback
- **Box Recommender Wizard**: ป้อน SKU + qty → recommend smallest box

### 5.4 Box Analytics
- `wms.box.analytics` — 360° usage (SQL view)
- `wms.product.box.analytics` — product vs box fill % (SQL view)
- Excel export: `action_export_xlsx()` via xlsxwriter

### 5.5 Cycle Count
- Sessions → Tasks → Entries → Adjustments
- "Mark as Applied" (no direct stock write — use Odoo Apply All)
- QWeb PDF report: Count Session Summary
- Spreadsheet Dashboard: Count Adjustments

### 5.6 KPI Assessment (Phase D — complete as of v2.17)
- Seasons → Templates → Pillars → Criteria → Assessments
- 4-level approval workflow: `draft → self_review → supervisor → asst_manager → manager → director → done`
- Auto-assign approvers via `wms.kpi.approver.config` (per-position + per-user overrides)
- Auto-populate quantitative evidence from `wms.worker.performance` on `action_start_self_review()`
- Goals (per assessment) + IDP 70-20-10 (on-job/social/formal)
- Grade mapping A/B/C/D/E from final_score (0-5 scale)
- Rejection paths at every level → state=rejected with reject_reason
- Bulk-create assessments: `Season.action_bulk_create_assessments()` creates 1 per kob.wms.user + 1 per supervisor/manager/director Odoo user
- Security: `group_wms_director` with implied_ids chain (director → manager → supervisor → worker)
- Tests: `tests/test_wms_kpi_assessment.py` — 11 cases covering state machine, scoring, uniqueness, evidence auto-populate

### 5.7 SLA
- Per-platform SLA minutes (pick / pack / ship)
- Working hours config (net minutes calculation)
- SLA status: on_track / at_risk / breached / done

### 5.8 Security Groups (hierarchical via implied_ids)
```
kob_wms.group_wms_worker      → scan only
kob_wms.group_wms_supervisor  → analytics + count (implies worker)
kob_wms.group_wms_manager     → full access (implies supervisor)
kob_wms.group_wms_director    → KPI final approval (implies manager)
```

### 5.10 Inter-company CMN Packaging Transfer (v2.16)
- Flag `product.template.is_cmn_packaging` (boolean column + bulk Action menu)
- When KOB validates an incoming receipt → auto-creates a draft non-value
  receipt for CMN-WH for flagged products (price=0, origin links back to
  KOB receipt, partner=original vendor for cross-check)
- CMN manually validates after attaching transfer documents
- Implemented in `stock_picking._auto_create_cmn_packaging_receipt()`

### 5.11 Count Screen (v2.16 SAP Fiori)
- Fullscreen count screen redesigned in SAP Fiori Analytical Table style
- Odoo 19 teal palette (`#00A99D`) + SAP navy shell (`#1D2D3E`)
- 4 screens: Task List → Navigate → Count (Sidebar+Table) → Summary
- Lot picker as centered SAP Dialog
- Status dots: green=ok, red=variance, gray=pending

### 5.9 Platform Fee Accounts
```
405101 Shopee fee
405102 Lazada fee
405103 TikTok fee
405104 Odoo fee
405105 POS fee
405106 Manual fee
```

---

## 6. Important Model Fields

### wms.sales.order
```python
status         # pending→picking→picked→packing→packed→shipped→cancelled
picking_id     # Many2one stock.picking (delivery order)
sale_order_id  # Many2one sale.order
actual_box_id  # Many2one wms.box.size (resolved from box_barcode)
box_barcode    # code scanned/selected at pack
box_fill_pct   # computed
total_pack_cost # box + tape + bubble
all_packed     # Boolean computed
```

### wms.box.size
```python
code           # e.g. 'B', 'C', '2C', 'L'
volume_cm3     # computed: L×W×H
volume         # computed: in m³ (matches product.template.volume)
unit_cost      # box price ฿
tape_cost_est  # computed
bubble_cost_est # manual
total_material_cost # box+tape+bubble
```

### stock.move.line (Odoo 18 naming — important!)
```python
ml.quantity_product_uom  # reserved qty
ml.quantity              # done qty  ← set this before button_validate()
ml.picked                # Boolean → set True before validate
```

---

## 7. Known Fixes & Decisions

### Fix 1 — _validate_picking (v2.11)
```python
# WRONG (over-counts with multi-lot):
ml.quantity = ml.move_id.product_uom_qty

# CORRECT:
ml.quantity = ml.quantity_product_uom
# + context skip_immediate=True, skip_backorder=True
# + verify picking.state == 'done' after button_validate()
```

### Fix 2 — Report load order
- Never use `%(action_report_xxx)d` in views that load before reports/
- Use `binding_type=report` on ir.actions.report instead
- Report appears in Print dropdown automatically

### Fix 3 — Spreadsheet Dashboard binary cache
- Existing dashboard records don't reload binary on `-u`
- Always create NEW records with unique XML IDs for new dashboards

### Fix 4 — Count Adjustment buttons
- Removed "Apply to Odoo" (direct stock write) — too dangerous
- Replaced with "Mark as Applied" (supervisor manually runs Odoo Apply All)

---

## 8. Manifest Load Order (critical)

```
security/ → data/sequences → views/ → wizards/ → portal → data/static
→ reports/ → analytics views → dashboards → fulfilment list views
→ views/wms_menus.xml  ← MUST BE LAST (needs all action IDs)
```

---

## 9. JavaScript / OWL Assets

Fulfilment screens are OWL components registered as Odoo actions:
```javascript
registry.category("actions").add("kob_wms.pack_screen", WmsPackScreen);
```

Screens import shared components from `wms_pick_pos/wms_pick_screen.js`:
```javascript
import { WmsTopNav, WmsPickCard, MODE_ACTIONS, MODE_ACCENT, ... }
    from "../wms_pick_pos/wms_pick_screen";
```

Worker identity stored in `localStorage`:
```javascript
const worker = JSON.parse(localStorage.getItem("wms_worker") || "{}");
// { id: kob_wms_user_id, name: "...", role: "..." }
```

---

## 10. Setup New Machine (Step by Step)

### Step 1 — Restore Database
```
http://NEW-IP:8018/web/database/manager
→ Restore → upload odoo18_db_YYYYMMDD.zip → Restore
```

### Step 2 — Clone kob_wms
```bash
cd custom_addons/
git clone https://github.com/samuny2329/kob-wms.git kob_wms
```

### Step 3 — Install dependencies
```bash
# xlsxwriter for Excel export
venv/Scripts/pip install xlsxwriter
```

### Step 4 — Upgrade module
```bash
venv/Scripts/python odoo-bin -c config/odoo18_local.conf \
  -u kob_wms -d odoo18_db --stop-after-init
```

### Step 5 — Verify
- เปิด KOB WMS menu ขึ้นมาได้
- Pick/Pack/Outbound screens โหลดได้
- Box Analytics แสดงข้อมูล
- Pack order แล้ว stock ตัด (picking state = done)

---

## 11. When Asking Claude for Help

บอก Claude:
- "อ่าน CLAUDE.md แล้วช่วย..." 
- ระบุไฟล์ที่ต้องแก้ เช่น `models/wms_sales_order.py`
- ถ้าแก้ model ต้อง `-u kob_wms` ก่อน test

**อย่าลืม:**
- อ่านไฟล์ก่อน edit เสมอ
- Manifest load order มีผลต่อ XML ID references
- stock.move.line ใน Odoo 18: done qty = `quantity`, reserved = `quantity_product_uom`
- Wizard ต้องมี access rule ใน ir.model.access.csv ด้วย (รวม TransientModel)
