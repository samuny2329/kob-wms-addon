# KOB WMS — System Configuration & UAT Data Record

> สำหรับ Claude บนเครื่องใหม่: อ่านไฟล์นี้ + CLAUDE.md ก่อนเริ่มงาน
> ไฟล์นี้บันทึก config ที่ดึงมาจาก UAT และตั้งค่าไว้แล้วในระบบปัจจุบัน

---

## 1. สถานะปัจจุบัน (18 เม.ย. 2026)

ระบบที่รันอยู่ = **Odoo 18 Community** + **kob_wms v2.11.0**
ข้อมูลทั้งหมดดึงมาจาก UAT แล้ว รวม:
- Products, Variants, BOMs
- Customers / Vendors
- Stock locations + Warehouses
- Existing delivery orders (stock.picking)
- Sale Orders history
- Platform fee accounts (chart of accounts)

---

## 2. Platform API Credentials

ตั้งค่าที่: **KOB WMS → Configuration → API Configurations**

| Platform | Fields ที่ต้องกรอก |
|----------|-----------------|
| Shopee   | API Key, API Secret, Shop ID, Endpoint URL |
| Lazada   | API Key, API Secret, Shop ID, Endpoint URL |
| TikTok   | API Key, API Secret, Shop ID, Endpoint URL |
| Odoo ERP | Endpoint URL (URL ของ Odoo), API Key |

> **หมายเหตุ:** Credential จริงอยู่ใน DB ที่ backup ไว้
> ถ้าตั้งใหม่ หา key ได้จาก:
> - Shopee: Shopee Open Platform → My Apps
> - Lazada: Lazada Open Platform → App Console
> - TikTok: TikTok Shop Partner Center → My Apps

**Model:** `wms.api.config`
```python
platform    # shopee / lazada / tiktok / odoo
enabled     # Boolean
api_key     # Char
api_secret  # Char
shop_id     # Char
endpoint_url # Char
```

---

## 3. Warehouse Configuration (pulled from UAT)

### Warehouses
ดูที่: Inventory → Configuration → Warehouses

| Field | Value |
|-------|-------|
| Name | Kiss of Beauty (หรือชื่อที่ตั้งใน UAT) |
| Short Name | K-On |
| Company | บริษัท คิสออฟบิวตี้ จำกัด |

### Stock Locations ที่ใช้ใน WMS
```
K-On/Stock/PICKFACE   ← location หลักที่ worker scan ของ
Partners/Customers    ← ปลายทาง delivery
Virtual Locations/Inventory adjustment ← cycle count adjustment
```

### Picking Types
```
K-On: Delivery Orders (OUT)  ← linked ใน wms.sales.order.picking_id
```

---

## 4. SLA Configuration

ตั้งค่าที่: **KOB WMS → Configuration → SLA Thresholds**

**Model:** `wms.sla.config`

Default configuration ที่ควรมี:

| Platform | Pick SLA | Pack SLA | Ship SLA | Working Hours |
|----------|----------|----------|----------|---------------|
| default  | 120 min  | 60 min   | 240 min  | 08:00-17:00   |
| shopee   | 90 min   | 45 min   | 180 min  | 08:00-17:00   |
| lazada   | 90 min   | 45 min   | 180 min  | 08:00-17:00   |
| tiktok   | 90 min   | 45 min   | 180 min  | 08:00-17:00   |
| odoo     | 120 min  | 60 min   | 480 min  | 08:00-17:00   |

Break periods (deducted from SLA calculation):
```
Morning break : 10:00 - 10:10
Lunch         : 12:00 - 13:00
Afternoon     : 15:00 - 15:10
```

---

## 5. Box Sizes (Auto-seeded)

28 ขนาดจาก THE BOX — ถูก seed อัตโนมัติจาก `data/wms_box_size_data.xml`
ไม่ต้องตั้งค่าใหม่ เมื่อ `-i kob_wms`

| Code | Size (cm) | Cost (฿) |
|------|-----------|---------|
| 00 | 14×9.75×6 | 3.00 |
| 0 | 11×17×6 | 3.00 |
| A | 20×14×9 | 4.50 |
| B | 24×17×11 | 6.00 |
| C | 30×20×11 | 8.50 |
| D | 35×22×14 | 12.00 |
| ... | ... | ... |
| JUMBO | 60×40×40 | 75.00 |

Tape cost: ฿0.30/m (OPP 48mm × 100m roll @ ฿30)
Bubble wrap: ฿0.30–฿15.00 ขึ้นกับขนาด

---

## 6. Chart of Accounts — Platform Fee Accounts

ตั้งค่าที่: Accounting → Configuration → Chart of Accounts

| Code | Account Name |
|------|-------------|
| 405101 | ค่าธรรมเนียม Shopee |
| 405102 | ค่าธรรมเนียม Lazada |
| 405103 | ค่าธรรมเนียม TikTok |
| 405104 | ค่าธรรมเนียม Odoo |
| 405105 | ค่าธรรมเนียม POS |
| 405106 | ค่าธรรมเนียม Manual |

ใช้ใน: auto-invoice fee lines per platform

---

## 7. WMS Workers (kob.wms.user)

ตั้งค่าที่: **KOB WMS → Employees → Employees**

**Model:** `kob.wms.user`

| Field | Description |
|-------|-------------|
| name | ชื่อพนักงาน |
| username | login username |
| pin | 4-6 digit PIN (quick login) |
| role | admin / supervisor / picker / packer / outbound / coordinator / viewer |
| res_user_id | optional: link ถึง Odoo user account |
| is_active | Boolean |

Roles → Screen Access:
```
picker    → Pick screen (F1)
packer    → Pack screen (F2)
outbound  → Outbound screen (F3)
supervisor → ทุกหน้า + Analytics + Count
admin     → ทุกอย่าง
```

Worker login: `http://SERVER:8018/kob/login`
Session เก็บใน `localStorage['wms_worker']` = `{id, name, role}`

---

## 8. Odoo User Groups

| Group XML ID | Level |
|-------------|-------|
| `kob_wms.group_wms_worker` | Worker (scan only) |
| `kob_wms.group_wms_supervisor` | Supervisor (analytics + count) |
| `kob_wms.group_wms_manager` | Manager (full + config) |

---

## 9. Community Addons (ที่ load เพิ่ม)

จาก `addons_path` ใน odoo18_local.conf:

```
odoo-19.0/manufacture-18.0           ← Manufacturing
odoo-19.0/stock-logistics-warehouse-18.0  ← Advanced warehouse
odoo-19.0/stock-logistics-reporting-18.0  ← Stock reporting
```

ทั้งหมดดึงมาจาก OCA (Odoo Community Association) compat 18.0

---

## 10. Development History — สิ่งที่สร้างในระบบนี้

### Phase 1 — Core WMS
- [x] Pick / Pack / Outbound / Dispatch fullscreen OWL screens
- [x] Worker login (PIN-based, no Odoo license)
- [x] Barcode scanning (hardware scanner + keyboard buffer)
- [x] SLA tracking per platform
- [x] Activity log
- [x] Courier batch + signature

### Phase 2 — Box & Packaging
- [x] 28 THE BOX sizes with tape formula + bubble wrap
- [x] Auto box-size recommendation (volume-based + item count fallback)
- [x] Box Analytics 360° (SQL view + charts)
- [x] Product vs Box analytics (SQL view + Excel export)
- [x] Box Recommender Wizard (v2.11) — ป้อน SKU+qty → recommend

### Phase 3 — Stock Integration Fix (v2.11)
- [x] `_validate_picking()` fix:
  - `ml.quantity = ml.quantity_product_uom` (done = reserved)
  - `skip_immediate=True` + `skip_backorder=True`
  - verify `picking.state == 'done'` after validate
- [x] `stock_warning` returned to Pack screen JS

### Phase 4 — Cycle Count
- [x] Count sessions → tasks → entries → adjustments
- [x] "Mark as Applied" (replaces dangerous direct stock write)
- [x] Count Session PDF report (QWeb)
- [x] Count Adjustments dashboard (Spreadsheet)

### Phase 5 — KPI & Analytics
- [x] Worker Performance KPI Assessment
- [x] KPI Templates / Pillars / Seasons
- [x] Approver setup
- [x] WMS Operations Dashboard (Spreadsheet)
- [x] WMS KPI Dashboard (Spreadsheet)

### Phase 6 — Repo Organization (v2.11)
- [x] .gitignore
- [x] Manifest organized with comments
- [x] Orphaned files added to manifest

---

## 11. Known Issues / Watch Points

### Stock not deducted (FIXED v2.11)
**Symptom:** Moves History แสดง "Available" หลัง pack เสร็จ
**Root cause:** `ml.quantity = ml.move_id.product_uom_qty` wrong field
**Fix:** ใน `_validate_picking()` — ดู CLAUDE.md section 7

### Dashboard binary not reloading
**Symptom:** dashboard ใหม่ไม่ขึ้นหลัง upgrade
**Fix:** สร้าง record ใหม่ด้วย XML ID ใหม่เสมอ (อย่า modify record เดิม)

### Report load order error
**Symptom:** `ValueError: External ID not found kob_wms.action_report_xxx`
**Fix:** ใช้ `binding_type=report` บน `ir.actions.report` แทนปุ่ม inline

---

## 12. Deploy บนเครื่องใหม่ (Quick Reference)

```bash
# 1. Restore DB backup
# http://NEW-IP:8018/web/database/manager → Restore zip

# 2. Clone addon
cd custom_addons/
git clone https://github.com/samuny2329/kob-wms.git kob_wms

# 3. Install xlsxwriter
venv/Scripts/pip install xlsxwriter

# 4. Upgrade
venv/Scripts/python odoo-bin -c config/odoo18_local.conf \
  -u kob_wms -d odoo18_db --stop-after-init

# 5. ตั้งค่า API credentials ที่
# KOB WMS → Configuration → API Configurations
```

---

## 13. Files ที่ต้องให้ Claude อ่านก่อนช่วยงาน

```
kob_wms/CLAUDE.md              ← tech context
kob_wms/SETUP_UAT.md           ← this file (config + history)
kob_wms/__manifest__.py        ← version + load order
kob_wms/models/wms_sales_order.py  ← core logic
kob_wms/models/wms_box_size.py     ← box fields
```

**Prompt สำหรับ Claude เครื่องใหม่:**
```
อ่าน CLAUDE.md และ SETUP_UAT.md ในโฟลเดอร์ kob_wms/ ก่อน
แล้วช่วยฉันต่อจากที่ทำไว้ — module version ปัจจุบันคือ 18.0.2.11.0
```
