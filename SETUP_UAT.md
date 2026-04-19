# KOB WMS — Odoo 18 Full Setup Guide (3 Companies)

> **วัตถุประสงค์:** ใช้ไฟล์นี้ตั้งค่า Odoo บนเครื่องใหม่ให้เหมือน UAT ทุกอย่าง
> **Claude บนเครื่องใหม่:** อ่านไฟล์นี้ + CLAUDE.md แล้วช่วย setup ตามลำดับ Section

---

## ลำดับการ Setup (ต้องทำตามลำดับ!)

```
1. Restore DB backup          → แนะนำวิธีนี้ที่สุด ข้ามขั้นตอนอื่นได้หมด
2. ติดตั้ง kob_wms module     → git clone + upgrade
3. ตรวจ Companies             → 3 บริษัท
4. ตรวจ Warehouses            → 40 คลัง
5. ตรวจ Inventory             → Locations, Operation Types
6. ตรวจ Accounting            → Journals, Taxes
7. ตรวจ Sale                  → Teams
8. ตรวจ WMS                   → SLA, Box Sizes, Workers, API
9. ทดสอบ                      → Checklist
```

---

## 0. Environment

```
Odoo Version : 18.0 Community
Port         : 8018
DB           : odoo18_db
PostgreSQL   : 127.0.0.1:5433  (user: odoo / pass: odoo)
venv         : odoo-18.0/venv/Scripts/python
Config       : odoo-18.0/config/odoo18_local.conf
kob_wms      : custom_addons/kob_wms  v2.12.0
GitHub       : https://github.com/samuny2329/kob-wms-addon
```

### Start Odoo
```bash
cd odoo-18.0
venv/Scripts/python odoo-bin -c config/odoo18_local.conf
```

### Install / Upgrade kob_wms
```bash
# ครั้งแรก
venv/Scripts/python odoo-bin -c config/odoo18_local.conf -i kob_wms -d odoo18_db --stop-after-init

# Update
venv/Scripts/python odoo-bin -c config/odoo18_local.conf -u kob_wms -d odoo18_db --stop-after-init
```

---

## 1. Restore Database (วิธีง่ายสุด — แนะนำ!)

```
1. เปิด http://localhost:8018/web/database/manager
2. กด Backup บนเครื่องเก่า → ดาวน์โหลด .zip
3. บนเครื่องใหม่ → กด Restore → อัพโหลด .zip
4. รอ restore เสร็จ (~5-15 นาที)
5. ข้ามไป Section 8 (ทดสอบ) ได้เลย
```

> ถ้า restore สำเร็จ → ข้าม Section 2-7 ได้ทั้งหมด เพราะข้อมูลทุกอย่างอยู่ใน DB แล้ว

---

## 2. Companies (3 บริษัท)

**เมนู:** Settings → Companies → Manage Companies

| ID | ชื่อบริษัท | โทร | Email |
|----|-----------|-----|-------|
| 1 | บริษัท คิสออฟบิวตี้ จำกัด | 02-3821254-6 | admin |
| 2 | บริษัท บิวตี้วิลล์ จำกัด | — | account@kissofbeauty.co.th |
| 3 | บริษัท คอสโมเนชั่น จำกัด | — | — |

### สร้าง Company ใหม่ (ถ้าไม่ restore DB)
```
Settings → Companies → New
- ใส่ชื่อ, โทร, email ตามตาราง
- Currency: THB (฿)
- Country: Thailand
```

---

## 3. Warehouses (40 คลัง)

**เมนู:** Inventory → Configuration → Warehouses

### บริษัท คิสออฟบิวตี้ จำกัด (KOB) — Company ID: 1

| ID | ชื่อ | Code | Reception | Delivery | ประเภท |
|----|------|------|-----------|----------|--------|
| 1 | KOB-WH2 (Online) | K-On | one_step | one_step | Online fulfilment หลัก |
| 2 | KOB-WH1 (Offline) | K-Off | two_steps | one_step | Offline / หน้าร้าน |
| 3 | KOB-SHOPEE | K-SPE | one_step | one_step | Shopee warehouse |
| 4 | KOB-BOXME | K-BOX | one_step | one_step | Boxme 3PL |
| 5 | KOB Consignment | KCON | one_step | one_step | ฝากขาย |
| 6 | KOB Not Available | KNOT | one_step | one_step | สินค้าไม่พร้อมขาย |
| 31 | End Year Sale 2025 | K-POS | one_step | one_step | POS Event |

**Consignment Locations (KC-):**

| ID | ร้าน | Code |
|----|------|------|
| 7 | Watson | KC-WS |
| 8 | Eve and Boy | KC-EB |
| 9 | Beautrium | KC-BT |
| 10 | Boots | KC-BO |
| 14 | Konvy | KC-KV |
| 15 | OR Health & Wellness | KC-OR |
| 19 | Better Way | KC-BW |
| 20 | Beautycool | KC-BC |
| 22 | Multy Beauty | KC-MB |
| 25 | S.C.Infinite | KC-SC |
| 27 | SCommerce | KC-SM |
| 28 | Soonthareeya | KC-SY |

---

### บริษัท บิวตี้วิลล์ จำกัด (BTV) — Company ID: 2

| ID | ชื่อ | Code | Reception | Delivery | ประเภท |
|----|------|------|-----------|----------|--------|
| 11 | BTV-WH1 (Offline) | B-Off | three_steps | one_step | Offline / หน้าร้าน (QC+Storage) |
| 18 | BTV-WH2 (Online) | B-On | one_step | one_step | Online fulfilment หลัก |
| 21 | BTV-SHOPEE | B-SPE | one_step | one_step | Shopee warehouse |
| 23 | BTV-BOXME | B-BOX | one_step | one_step | Boxme 3PL |
| 24 | BTV Consignment | BCON | one_step | one_step | ฝากขาย |
| 26 | BTV Not Available | BNOT | one_step | one_step | สินค้าไม่พร้อมขาย |
| 16 | OR Health & Wellness | BC-OR | one_step | one_step | Consignment |

**Consignment Locations (BC-):**

| ID | ร้าน | Code |
|----|------|------|
| 29 | Watson | BC-WS |
| 30 | Eve and Boy | BC-EB |
| 32 | Beautrium | BC-BT |
| 33 | Boots | BC-BO |
| 34 | Konvy | BC-KV |
| 35 | Better Way | BC-BW |
| 36 | Beautycool | BC-BC |
| 37 | Multy Beauty | BC-MB |
| 38 | S.C.Infinite | BC-SC |
| 39 | SCommerce | BC-SM |
| 40 | Soonthareeya | BC-SY |

---

### บริษัท คอสโมเนชั่น จำกัด (CMN) — Company ID: 3

| ID | ชื่อ | Code | Reception | Delivery | ประเภท |
|----|------|------|-----------|----------|--------|
| 12 | CMN-WH | CMNW | three_steps | one_step | Main warehouse (QC+Storage) |
| 13 | CMN Not Available | CMNNO | one_step | one_step | สินค้าไม่พร้อมขาย |
| 17 | CMN-WH KK#1 | CMN-K | one_step | one_step | สาขาขอนแก่น #1 |

---

## 4. Inventory Configuration

**เมนู:** Inventory → Configuration

### 4.1 Routes
ไม่มี custom routes นอกจาก default ของ Odoo (Buy, Manufacture, Resupply)

### 4.2 Operation Types (หลัก)

| Warehouse | Type | Code |
|-----------|------|------|
| KOB-WH2 (Online) | Receipts | incoming |
| KOB-WH2 (Online) | **PICK Order** | outgoing (special) |
| KOB-WH2 (Online) | Internal Transfers | internal |
| KOB-WH2 (Online) | Delivery Orders | outgoing |
| KOB-WH1 (Offline) | Receipts | incoming |
| KOB-WH1 (Offline) | Internal Transfers | internal |
| KOB-WH1 (Offline) | **Storage** | internal (2-step) |
| KOB-WH1 (Offline) | Delivery Orders | outgoing |
| BTV-WH1 (Offline) | Receipts | incoming |
| BTV-WH1 (Offline) | **Quality Control** | internal (3-step) |
| BTV-WH1 (Offline) | **Storage** | internal (3-step) |
| BTV-WH1 (Offline) | Delivery Orders | outgoing |
| CMN-WH | Receipts | incoming |
| CMN-WH | **Quality Control** | internal (3-step) |
| CMN-WH | **Storage** | internal (3-step) |
| CMN-WH | Delivery Orders | outgoing |
| (all others) | Receipts, Internal, Delivery | standard |

> **หมายเหตุ:** ทุก Warehouse มี Receipts + Internal Transfers + Delivery Orders เป็น default
> K-Off มี Reception 2-step (Storage) | BTV-WH1, CMN-WH มี 3-step (QC → Storage)

### 4.3 Internal Locations (หลัก — ตัวอย่าง)

**K-Off (KOB Offline) — Bin System:**
- Pattern B2: `K-Off/Stock/B2-[A-D][01-04]-[01-14]` (barcode: B2-A01-01 ...)
- Pattern K1: `K-Off/Stock/K1-[A-H][01-04]-[01-24]` (barcode: K1-A01-01 ...)
- Special: `K-Off/Stock/FLFG`, `K-Off/Stock/FLFG-B2`, `K-Off/Stock/RETURN-BIN`, `K-Off/Stock/TESTER`
- **รวม ~600+ bin locations**

**K-On (KOB Online):**
- `K-On/Stock` (barcode: K-ONSTOCK)

**B-Off (BTV Offline) — ใช้ bins เดียวกับ K-Off:**
- `B-Off/Stock/K1-[A-H][01-04]-[01-24]`
- `B-Off/Stock/PK` (pick face locations)
- Special: `B-Off/Stock/RETURN-BIN`, `B-Off/Stock/TESTER`
- **รวม ~1,100+ bin locations**

**B-On (BTV Online):**
- `B-On/Stock` (barcode: B-ONSTOCK)
- `B-On/Stock/PICKFACE`, `B-On/Stock/R1` ถึง `B-On/Stock/R10`

**CMN-K (KK Branch):**
- `CMN-K/Stock/K-E[A-F]-[1-4]-[01-02]` (barcode: K-EA-1-01 ...)

**Consignment (KC-/BC-):**
- `KC-WS/Stock`, `KC-EB/Stock`, `KC-BT/Stock` ... (barcodes: KC-WSSTOCK ...)
- `BC-WS/Stock`, `BC-EB/Stock`, `BC-BT/Stock` ... (barcodes: BC-WSSTOCK ...)

**KNOT/BNOT (Not Available):**
```
KNOT/Stock/Damaged Goods, Returns, Scrap, Event, RESERVE, ASSEMBLY ...
BNOT/Stock/Damaged Goods, Returns/Return-CL/Return-FG, Scrap, RESERVE, RESERVE-APP, DMRTONLINE ...
```

### 4.4 Putaway Rules
ไม่มี putaway rules ที่ตั้งค่าพิเศษ (ใช้ default)

### 4.5 Reorder Rules
ไม่มี reorder rules (0 rows)

### 4.6 Product Categories
(ใช้ default Odoo — `property_stock_location_id` column ไม่มีใน Odoo 18)

---

## 5. Accounting Configuration

**เมนู:** Accounting → Configuration

### 5.1 account_account Schema (Odoo 18)
> **หมายเหตุ:** Odoo 18 เปลี่ยน schema — ไม่มี `code` column ตรงๆ และไม่มี `company_id` บน account
```
Columns: id, currency_id, account_type, name (jsonb), code_store (jsonb),
         note, deprecated, reconcile, non_trade, create_date, write_date
```

### 5.2 Platform Fee Accounts (ทราบแล้ว)

| Code | Account Name |
|------|-------------|
| 405101 | ค่าธรรมเนียม Shopee |
| 405102 | ค่าธรรมเนียม Lazada |
| 405103 | ค่าธรรมเนียม TikTok |
| 405104 | ค่าธรรมเนียม Odoo |
| 405105 | ค่าธรรมเนียม POS |
| 405106 | ค่าธรรมเนียม Manual |

### 5.3 Journals — คิสออฟบิวตี้ (Company 1)

| ID | ชื่อ | Type | Code |
|----|------|------|------|
| 1 | Customer Invoices | sale | INV |
| 2 | Vendor Bills | purchase | BILL |
| 3 | Miscellaneous Operations | general | MISC |
| 4 | Exchange Difference | general | EXCH |
| 5 | Cash Basis Taxes | general | CABA |
| 6 | Bank | bank | BNK1 |
| 7 | Cash | cash | CSH1 |
| 8 | Inventory Valuation | general | STJ |
| 9 | Point of Sale | general | POSS |
| 10 | Cash Furn. Shop | cash | CSH2 |

> BTV และ CMN ต้องสร้าง journals แยกหลัง restore (Odoo สร้างให้อัตโนมัติเมื่อ setup company ใหม่)

### 5.4 Payment Terms (Global — ทุก Company)

| ID | ชื่อ |
|----|------|
| 1 | Immediate Payment |
| 2 | 15 Days |
| 3 | 21 Days |
| 4 | 30 Days |
| 5 | 45 Days |
| 6 | End of Following Month |
| 7 | 10 Days after End of Next Month |
| 8 | 30% Now, Balance 60 Days |
| 9 | 2/7 Net 30 |
| 10 | 90 days, on the 10th |

### 5.5 Taxes — คิสออฟบิวตี้ (Company 1)

| ID | ชื่อ | ใช้กับ | อัตรา | ประเภท |
|----|------|--------|-------|--------|
| 1 | 15% | sale | 15% | percent |
| 2 | 15% | purchase | 15% | percent |

> **หมายเหตุ:** ระบบใช้ภาษี 15% (ไม่ใช่ VAT 7%) เป็นค่า default

---

## 6. Sale Configuration

**เมนู:** Sales → Configuration

### 6.1 Sales Teams (Global)

| ID | ชื่อ |
|----|------|
| 1 | Sales |
| 2 | Website |
| 3 | Point of Sale |

### 6.2 Pricelists
ไม่มี pricelists ที่ active (0 rows)

### 6.3 System Settings (ir.config_parameter)

| Key | Value |
|-----|-------|
| account_payment.enable_portal_payment | True |
| sale.async_emails | False |
| sale.default_confirmation_template | 16 |
| sale.default_invoice_email_template | 7 |
| stock.barcode_separator | , |

---

## 7. Purchase Configuration

**เมนู:** Purchase → Configuration

### 7.1 Top Vendors (ซัพพลายเออร์หลัก)

| ชื่อ | โทร/Email | Rank |
|------|-----------|------|
| บริษัท ช้อปปี้ (ประเทศไทย) จำกัด | — | 1289 |
| บริษัท ติ๊กต๊อก ช็อป (ประเทศไทย) จำกัด | — | 809 |
| ONE TIME | — | 688 |
| บริษัท เซ็นทรัล วัตสัน จำกัด | +66 2 665 2000 | 650 |
| บริษัท เฟรท ลิ้งค์ส เอ๊กซ์เพรส (ประเทศไทย) จำกัด | — | 620 |
| บริษัท ลาซาด้า จำกัด | — | 540 |
| บริษัท เซ็นทรัล ฟู้ด รีเทล จำกัด | 02 831 7300 | 467 |
| กรมสรรพากร | — | 428 |
| Meta Platforms Ireland Limited | — | 416 |
| บริษัท ซี.เจ. เอ็กซ์เพรส กรุ๊ป จำกัด | 02-235-3146-9 | 415 |

> ซัพพลายเออร์ทั้งหมด ~50+ รายจะอยู่ใน DB หลัง restore

---

## 8. WMS Configuration

### 8.1 SLA Config

**เมนู:** KOB WMS → Configuration → SLA Thresholds

| ID | Platform | Pick | Pack | Ship |
|----|----------|------|------|------|
| 1 | default | 120 min | 60 min | 240 min |
| 2 | shopee | 60 min | 30 min | 180 min |
| 3 | lazada | 60 min | 30 min | 180 min |
| 4 | tiktok | 45 min | 30 min | 120 min |
| 5 | pos | 15 min | 10 min | 60 min |

Working hours & breaks:
```
Working hours: 08:00 - 17:00
Morning break : 10:00 - 10:10
Lunch         : 12:00 - 13:00
Afternoon     : 15:00 - 15:10
Soft SLA avg  : 90 min (for analytics)
```

### 8.2 Box Sizes (34 sizes — auto-seeded)

**เมนู:** KOB WMS → Configuration → Box Sizes
> ถูก seed อัตโนมัติจาก `data/wms_box_size_data.xml` ไม่ต้องตั้งใหม่

| Code | ชื่อ | L×W×H (cm) | Vol (cm³) | Box (฿) | Total (฿) |
|------|------|-----------|-----------|---------|----------|
| 00 | 00 | 14×9.75×6 | 819 | 3.00 | 3.64 |
| 0 | 0 | 11×17×6 | 1,122 | 4.00 | 4.97 |
| AA | AA | 13×17×7 | 1,547 | 5.00 | 6.24 |
| A | A | 14×20×6 | 1,680 | 5.00 | 6.28 |
| 0+4 | 0+4 | 11×17×10 | 1,870 | 5.00 | 6.30 |
| AB | AB | 14×20×8 | 2,240 | 6.00 | 7.56 |
| ENV | Envelope | 28×36×3 | 3,024 | 2.00 | 2.26 |
| CD | CD | 15×15×15 | 3,375 | 7.00 | 8.60 |
| B | B | 17×25×9 | 3,825 | 7.00 | 8.92 |
| BH | BH | 17×25×13 | 5,525 | 8.00 | 10.24 |
| BAG | Poly Bag | 40×30×5 | 6,000 | 3.00 | 3.74 |
| 2A | 2A | 13×40×12 | 6,240 | 8.00 | 10.25 |
| C | C | 20×30×11 | 6,600 | 10.00 | 12.30 |
| 2B | 2B | 17×25×18 | 7,650 | 10.00 | 12.83 |
| C+8 | C+8 | 20×30×19 | 11,400 | 12.00 | 14.94 |
| 2C | 2C | 20×30×22 | 13,200 | 13.00 | 16.50 |
| F-S | F เล็ก | 31×36×13 | 14,508 | 18.00 | 21.44 |
| E | E | 24×40×17 | 16,320 | 15.00 | 18.59 |
| D+11 | D+11 | 22×35×25 | 19,250 | 17.00 | 21.14 |
| 2D | 2D | 22×35×28 | 21,560 | 18.00 | 22.69 |
| M | M | 27×43×20 | 23,220 | 20.00 | 24.19 |
| P1 | P1 | 24×58×17 | 23,664 | 30.00 | 34.41 |
| G | G | 31×36×26 | 29,016 | 22.00 | 26.68 |
| a(มม) | a มม | 30×45×22 | 29,700 | 22.00 | 26.77 |
| M+ | M+ | 35×45×25 | 39,375 | 25.00 | 30.32 |
| P2 | P2 | 33×58×24 | 45,936 | 40.00 | 45.54 |
| F-L | F ใหญ่ | 32×48×30 | 46,080 | 28.00 | 33.96 |
| I | I | 30×50×32 | 48,000 | 33.00 | 39.54 |
| L | L | 40×50×30 | 60,000 | 35.00 | 41.50 |
| P4 | P4 | 30×100×20 | 60,000 | 50.00 | 57.72 |
| H | H | 40×45×35 | 63,000 | 40.00 | 46.50 |
| P3 | P3 | 40×80×20 | 64,000 | 45.00 | 51.86 |
| i(มม) | i มม | 45×55×40 | 99,000 | 50.00 | 57.77 |
| BIG | BIG BOX | 52×92×48 | 229,632 | 80.00 | 90.58 |

Tape: ฿0.30/m (คำนวณตามสูตรใน code)

### 8.3 WMS Workers

**เมนู:** KOB WMS → Employees

| ID | ชื่อ | Username | Role | Active | Position |
|----|------|----------|------|--------|----------|
| 1 | Admin KOB | admin | admin | ✓ | Senior Admin |
| 2 | Senior KOB | senior01 | supervisor | ✓ | — |
| 3 | Picker 01 | picker01 | picker | ✓ | — |
| 4 | Packer 01 | packer01 | packer | ✓ | — |
| 5 | Outbound 01 | outbound01 | outbound | ✓ | — |
| 6 | Coordinator KOB | coord01 | coordinator | ✓ | — |

| Role | สิทธิ์ |
|------|--------|
| admin | ทุกอย่าง |
| supervisor | Analytics + Count + Box Recommender |
| coordinator | สั่งงาน, ดู dashboard |
| picker | Pick screen (F1) |
| packer | Pack screen (F2) |
| outbound | Outbound + Dispatch (F3/F4) |

Login URL: `http://SERVER:8018/kob/login`

### 8.4 Platform API Config

**เมนู:** KOB WMS → Configuration → API Configurations

| ID | Platform | Enabled | หมายเหตุ |
|----|----------|---------|---------|
| 1 | odoo | ✓ | เปิดใช้งาน |
| 2 | shopee | ✗ | ยังไม่ผูก API |
| 3 | lazada | ✗ | ยังไม่ผูก API |
| 4 | tiktok | ✗ | ยังไม่ผูก API |

Fields: platform, api_key, api_secret, endpoint_url, shop_id, note, enabled

### 8.5 Delivery Carriers

| ID | ชื่อ | Type |
|----|------|------|
| 1 | Standard delivery | fixed |

### 8.6 Odoo User Groups

| Group | Level |
|-------|-------|
| kob_wms.group_wms_worker | Worker (scan only) |
| kob_wms.group_wms_supervisor | Supervisor |
| kob_wms.group_wms_manager | Manager (full) |

---

## 9. Community Addons

```ini
# addons_path ใน odoo18_local.conf
odoo-19.0/manufacture-18.0
odoo-19.0/stock-logistics-warehouse-18.0
odoo-19.0/stock-logistics-reporting-18.0
custom_addons
```

Python packages:
```bash
venv/Scripts/pip install xlsxwriter
```

---

## 10. Verification Checklist

หลัง setup เสร็จ ทดสอบตามนี้:

```
□ เข้า Odoo http://SERVER:8018 ได้
□ เห็น 3 บริษัทใน Settings → Companies
□ เห็น 40 Warehouses ใน Inventory → Warehouses
□ KOB WMS menu ขึ้น
□ Pick/Pack/Outbound screens โหลดได้ (F1/F2/F3)
□ Box Analytics แสดงข้อมูล
□ สร้าง test order → Pack → Stock ถูกตัด (picking state = done)
□ Invoice ถูกสร้างและ posted อัตโนมัติ
□ Box Recommender Wizard ทำงานได้
□ SLA timer เริ่มนับเมื่อ Print Pick List
□ Login /kob/login ด้วย picker01 ได้
```

---

## 11. Known Issues & Fixed Bugs

| ปัญหา | สาเหตุ | สถานะ |
|-------|--------|--------|
| Stock ไม่ถูกตัด | `_validate_picking()` field ผิด | ✅ Fixed v2.11 |
| Dashboard ไม่โหลด | Binary cache | ✅ สร้าง XML ID ใหม่ |
| Report ไม่ขึ้น | Load order ผิด | ✅ ใช้ binding_type=report |
| SLA ไม่เริ่ม | ยังไม่ Print Pick List | ✅ กด Print Pick List ก่อน |
| account_account query ผิด | Odoo 18 ไม่มี company_id | ✅ ใช้ `code_store` แทน `code` |
| AWB label upgrade ผิด | `t-esc` attribute ซ้ำ | ✅ Fixed v2.12 |
| Count lock บล็อค Validate ช้าไป | lock check อยู่ใน close_box ไม่ใช่ scan_pick | ✅ Fixed v2.12 |
| Cycle count tasks โหลดทุก SKU | `wms.count.task` ไม่มี `product_id` | ✅ Fixed v2.12 |
| ABC สร้าง task ทุก product | ไม่มีการสุ่ม sample | ✅ Fixed v2.12 — weighted sample by yesterday OUT |
| Session cancel ไม่ล้าง location lock | `action_cancel()` ไม่ clear `counting_task_id` | ✅ Fixed v2.12 |
| Close Box ค้าง "still assigned" | `button_validate()` ไม่ complete ครั้งแรก | ✅ Fixed v2.12 — auto-retry built-in |
| Pick list report qty ผิด | `reserved_uom_qty` ไม่มีใน Odoo 18 | ✅ Fixed v2.12 → `quantity_product_uom` |
| `_domainForMode()` default โหลด order ทั้งหมด | `return []` ใน default case | ✅ Fixed v2.12 → `return [["id","=",0]]` |
| Warehouse default ไม่กรอง company | `search([], limit=1)` | ✅ Fixed v2.12 → filter by `env.company` |
| N+1 query ใน pickface | `search()` inside for loop | ✅ Fixed v2.12 — batch fetch |
| scan_bar dialog error ไม่ reset | catch ไม่ call `_scheduleReset()` | ✅ Fixed v2.12 |

---

## 12. Cycle Count — การทำงาน (v2.12+)

```
WMS → Count (F5) → Count Sessions → New → Run Auto Cycle Count

Logic:
  1. ดึงยอด OUT เมื่อวาน (packed_at::date = yesterday, status=packed/shipped)
  2. จัดอันดับ A/B/C จาก 30-day OUT volume
  3. สุ่ม weighted sample จากแต่ละ rank (น้ำหนัก = qty เมื่อวาน):
       Rank A → 30% of A-movers, max 5 tasks
       Rank B → 20% of B-movers, max 3 tasks
       Rank C → 10% of C-movers, max 2 tasks (full count เท่านั้น)
  4. สร้าง task 1 ต่อ SKU — นับเฉพาะ product นั้น (product_id locked)

ถ้า session ค้าง → Cancel session → ไม่มี ghost lock (auto-cleared)
ถ้า picking ค้าง → ไปที่ Inventory → Transfers → Validate โดยตรง
```

---

## 13. Claude Prompt สำหรับเครื่องใหม่

```
อ่าน CLAUDE.md และ SETUP_UAT.md ในโฟลเดอร์ kob_wms/ ก่อน
ระบบมี 3 บริษัท: คิสออฟบิวตี้ (KOB), บิวตี้วิลล์ (BTV), คอสโมเนชั่น (CMN)
Module version ปัจจุบัน: 18.0.2.12.0
ช่วยฉัน setup/แก้ปัญหา: [ระบุงาน]
```

---

> **ข้อมูลนี้ดึงจาก UAT DB เมื่อ 2026-04-19**
> วิธีที่ดีที่สุดคือ **Restore DB** จาก backup — ไม่ต้อง manual setup ทุกอย่าง
