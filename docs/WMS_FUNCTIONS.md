# KOB WMS Pro — Function Reference

> **Module:** `kob_wms` | **Version:** 2.11.0 | **Odoo:** 18.0

---

## 1. wms.sales.order

### Computed Fields

| Method | Trigger Fields | Returns |
|--------|---------------|---------|
| `_compute_actual_box` | `box_barcode` | `actual_box_id` — หา wms.box.size จาก code |
| `_compute_order_dims` | `line_ids.picked_qty`, `product.volume/weight` | `order_vol_m3`, `order_weight_kg` |
| `_compute_box_analytics` | `actual_box_id`, `order_vol_m3` | `box_fill_pct`, `box_cost_est`, `tape_cost_est`, `bubble_cost_est`, `total_pack_cost`, `box_suggestion_hit` |
| `_compute_totals` | `line_ids.expected/picked/packed_qty` | `expected_total`, `picked_total`, `packed_total`, `all_picked`, `all_packed` |
| `_compute_sla` | `create_date`, timestamps, `platform` | `sla_pick/pack/ship_deadline`, `sla_status` |
| `_compute_durations` | timestamps | `wait_pick_min`, `pick_duration_min`, `wait_pack_min`, `pack_duration_min`, `total_duration_min` |
| `_compute_difficulty` | `line_ids.expected_qty` | `items_count`, `sku_count` |

### Action Methods

| Method | เรียกเมื่อ | ทำอะไร |
|--------|----------|--------|
| `action_print_picklist()` | Admin กด Print Pick List | Set `sla_start_at` ครั้งแรก → return QWeb report action |
| `create(vals_list)` | สร้าง record ใหม่ | Auto-generate sequence `WMS/2026/XXXXX` |

### Stock Integration Methods

| Method | Parameters | Returns | หมายเหตุ |
|--------|-----------|---------|----------|
| `_ensure_picking_reserved()` | — | `None` หรือ error string | Confirm + assign picking ถ้ายังไม่ reserved |
| `_validate_picking()` | — | `None` หรือ error string | ตั้ง `ml.quantity = ml.quantity_product_uom` → `button_validate(skip_immediate=True)` → ตรวจ state='done' |
| `select_box_and_close(box_barcode)` | box_barcode: str | dict หรือ raise | เรียก `_validate_picking()` → ตัดสต็อค → status='packed' |
| `close_box(box_barcode)` | box_barcode: str | dict | เหมือน `select_box_and_close` (alias) |

### Critical Fix (v2.11)

```python
# _validate_picking() — ตัดสต็อคให้ถูกต้อง
for ml in order.picking_id.move_line_ids:
    reserved = ml.quantity_product_uom or 0   # ← done qty = reserved qty
    if reserved > 0:
        ml.quantity = reserved                 # ← ไม่ใช่ ml.move_id.product_uom_qty
    if hasattr(ml, 'picked'):
        ml.picked = True

result = picking.with_context(
    skip_immediate=True,
    skip_backorder=True
).button_validate()

# ตรวจว่า done จริง
if picking.state != 'done':
    errors.append(f'{picking.name} ยังไม่ done')
```

---

## 2. wms.box.size

### Computed Fields

| Method | Trigger | Returns |
|--------|---------|---------|
| `_compute_volume` | `length`, `width`, `height` | `volume_cm3` (L×W×H), `volume` (÷1,000,000 → m³) |
| `_compute_tape` | `width`, `height`, `tape_rounds`, `tape_overlap_cm`, `tape_cost_per_m` | `tape_length_m`, `tape_cost_est` |
| `_compute_total_cost` | `unit_cost`, `tape_cost_est`, `bubble_cost_est` | `total_material_cost` |

### Tape Formula

```
girth_cm      = (width + height) × 2
tape_cm       = girth_cm × tape_rounds + tape_overlap_cm
tape_length_m = tape_cm ÷ 100
tape_cost_est = tape_length_m × tape_cost_per_m
```

### Key Methods

| Method | Returns | หมายเหตุ |
|--------|---------|----------|
| `get_recommended_box(vol_m3, item_count)` | `wms.box.size` record | หากล่องเล็กสุดที่จุได้ + fallback by item count |

---

## 3. wms.box.analytics (SQL View)

> Read-only — no writes. Refresh on `-u kob_wms`.

| Field | ความหมาย |
|-------|---------|
| `actual_box_id` | กล่องที่ใช้จริง |
| `platform` | Shopee / Lazada / TikTok ฯลฯ |
| `order_count` | จำนวน orders ที่ใช้กล่องนี้ |
| `avg_fill_pct` | Fill % เฉลี่ย |
| `total_pack_cost` | ต้นทุน packaging รวม |
| `avg_pack_cost` | ต้นทุนเฉลี่ยต่อ order |

**Export:** `action_export_xlsx()` → ดาวน์โหลด .xlsx ด้วย xlsxwriter

---

## 4. wms.count.session

### State Machine

```
draft → in_progress → reconciling → done
                    ↘ cancelled
```

### Key Methods

| Method | ทำอะไร |
|--------|--------|
| `action_start()` | state: draft → in_progress, สร้าง snapshot ของ stock.quant ปัจจุบัน |
| `action_reconcile()` | state → reconciling, คำนวณ variance ทุก entry |
| `action_done()` | state → done, set `date_end` |
| `action_cancel()` | state → cancelled |
| `action_create_tasks()` | สร้าง wms.count.task ต่อ location/product |
| `_compute_task_state_counts` | นับ assigned/counting/submitted/done → `progress_pct` |

---

## 5. wms.count.adjustment

### Key Methods

| Method | ทำอะไร |
|--------|--------|
| `action_mark_applied()` | Set `applied=True`, `applied_at=now()` — Supervisor กดหลัง Apply All ใน Odoo |

> ⚠️ ไม่มี direct stock write — ใช้ Odoo Physical Inventory (Apply All) แทน

---

## 6. kob.wms.user

### Authentication Methods

| Method | Parameters | Returns |
|--------|-----------|---------|
| `authenticate(username, password)` | str, str | `kob.wms.user` หรือ raise |
| `authenticate_pin(username, pin)` | str, str | `kob.wms.user` หรือ raise |
| `generate_token()` | — | token string (TTL 8 ชม.) |
| `validate_token(token)` | str | `kob.wms.user` หรือ False |
| `set_password(new_password)` | str | — |

### Security

```python
# Lock after 5 failed attempts
if user.failed_login_count >= 5:
    user.locked_until = now + timedelta(minutes=15)

# Password stored as SHA-256 hash
password_hash = hashlib.sha256(password.encode()).hexdigest()
```

---

## 7. wms.sla.config

### Key Methods

| Method | Parameters | Returns |
|--------|-----------|---------|
| `get_for_platform(platform)` | str | `wms.sla.config` record (fallback = 'default') |
| `net_working_minutes(start, end)` | datetime, datetime | float — นาทีในเวลางาน (ตัด OT, วันหยุด) |

---

## 8. Wizards

### wms.box.recommender.wizard

| Method | ทำอะไร |
|--------|--------|
| `action_compute()` | คำนวณ total vol + buffer → หา 3 กล่องเล็กสุดที่จุได้ → set `recommended_box_id`, `alt1_box_id`, `alt2_box_id` |
| `action_reset()` | ล้าง results → state='draft' |

**Input:** Lines (product_id + qty) + `fill_buffer_pct` (default 15%)
**Output:** recommended_box + 2 alternatives + fill %, cost breakdown

### wms.scan.wizard

| Method | ทำอะไร |
|--------|--------|
| `action_scan(barcode)` | Route barcode → product scan / AWB scan / box scan |

### wms.cancel.return.wizard

| Method | ทำอะไร |
|--------|--------|
| `action_cancel()` | ยกเลิก order → status='cancelled', reverse picking ถ้ามี |
| `action_return()` | สร้าง return picking → คืนสต็อค |

---

## 9. Controllers (HTTP)

> `controllers/main.py` — WMS Worker Portal

| Route | Method | Auth | ทำอะไร |
|-------|--------|------|--------|
| `/kob/login` | POST | public | Authenticate kob.wms.user → return token |
| `/kob/orders` | GET | token | ดึง orders ตาม role/status |
| `/kob/scan` | POST | token | Process barcode scan (pick / pack / outbound) |
| `/kob/worker/status` | GET | token | Worker dashboard data |

---

## 10. Odoo stock.move.line Fields (v18 — critical!)

```python
ml.quantity_product_uom   # ← Reserved qty (demand per line)
ml.quantity               # ← Done qty (SET THIS before button_validate)
ml.picked                 # ← Boolean flag (SET True before button_validate)
```

> **อย่าใช้** `ml.move_id.product_uom_qty` — เป็น total demand ของ move ทั้งก้อน จะ overcount ถ้ามีหลาย lots

---

## 11. Manifest Load Order

```
security/ir.model.access.csv
data/sequences + config
views/ (forms, lists, kanban)
wizards/*.xml
data/static (master data: box sizes, couriers, SLA)
report/ (QWeb templates)
data/analytics views + dashboards
views/wms_menus.xml   ← MUST BE LAST
```
