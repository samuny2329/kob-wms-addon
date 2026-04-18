# KOB WMS Pro — คู่มือการใช้งาน

> **Version:** 2.11.0 | **บริษัท:** Kiss of Beauty / SKINOXY
> **URL:** http://[SERVER]:8018/web → เมนู KOB WMS

---

## สารบัญ

1. [ภาพรวมระบบ](#1-ภาพรวมระบบ)
2. [Login และ Role](#2-login-และ-role)
3. [หน้าจอ Pick (หยิบสินค้า)](#3-หน้าจอ-pick-หยิบสินค้า)
4. [หน้าจอ Pack (แพ็คสินค้า)](#4-หน้าจอ-pack-แพ็คสินค้า)
5. [หน้าจอ Outbound (สแกนขาออก)](#5-หน้าจอ-outbound-สแกนขาออก)
6. [หน้าจอ Dispatch (จัดส่ง)](#6-หน้าจอ-dispatch-จัดส่ง)
7. [Box Recommender Wizard](#7-box-recommender-wizard)
8. [Cycle Count (นับสต็อค)](#8-cycle-count-นับสต็อค)
9. [Box Analytics](#9-box-analytics)
10. [ตั้งค่าระบบ (Manager)](#10-ตั้งค่าระบบ-manager)
11. [Error & Troubleshooting](#11-error--troubleshooting)

---

## 1. ภาพรวมระบบ

```
Order เข้า (Shopee/Lazada/TikTok/Odoo)
         ↓
  [PENDING] รอหยิบ
         ↓
  [PICKING] กำลังหยิบ   ← Worker F1 Screen
         ↓
  [PICKED]  หยิบเสร็จ
         ↓
  [PACKING] กำลังแพ็ค   ← Worker F2 Screen
         ↓
  [PACKED]  แพ็คเสร็จ   ← ✅ ตัดสต็อค + ออก Invoice อัตโนมัติ
         ↓
  [SHIPPED] ส่งแล้ว
```

### Flow การตัดสต็อค
เกิดขึ้นอัตโนมัติตอน **Pack เสร็จ** (select box and close):
1. ระบบ set done qty = reserved qty บน stock.move.line
2. เรียก `button_validate()` บน stock.picking
3. Odoo ตัดสต็อคออกจาก WH/Stock
4. สร้าง Invoice ในสถานะ Posted อัตโนมัติ

---

## 2. Login และ Role

### เข้าสู่ระบบ
```
URL: http://[SERVER]:8018/web
Menu: KOB WMS → [หน้าจอที่ต้องการ]
```

หรือ Worker Login แบบ PIN:
```
URL: http://[SERVER]:8018/kob/login
Username + PIN (4-6 หลัก)
```

### Role และสิทธิ์

| Role | หน้าจอที่เข้าได้ | สิทธิ์พิเศษ |
|------|----------------|------------|
| **admin** | ทุกหน้า | ตั้งค่าทั้งหมด, ลบ record |
| **supervisor** | ทุกหน้า | Analytics, Count Session, Box Recommender |
| **picker** | Pick Screen | หยิบสินค้า, พิมพ์ Pick List |
| **packer** | Pack Screen | แพ็ค, เลือกกล่อง, ตัดสต็อค |
| **outbound** | Outbound, Dispatch | สแกน AWB, Manifest |
| **coordinator** | ดูทุกหน้า, แก้ไขบางส่วน | วางแผน wave |

### Security Groups (Odoo)
```
kob_wms.group_wms_worker      → scan screens only
kob_wms.group_wms_supervisor  → analytics + count + box recommender
kob_wms.group_wms_manager     → full access + settings
```

---

## 3. หน้าจอ Pick (หยิบสินค้า)

**เมนู:** KOB WMS → Operations → Pick  
**Hotkey:** F1

### ขั้นตอน

```
1. เลือก Order จากรายการ (status = pending)
2. กด "Start Pick" → status เปลี่ยนเป็น "picking"
3. หยิบสินค้าตาม Pick List:
   - สแกน Barcode สินค้า
   - ระบบตรวจ: ถูก SKU? ถูก Qty?
   - ✅ ถูก → เพิ่ม picked_qty
   - ❌ ผิด → แจ้งเตือน, สแกนใหม่
4. หยิบครบทุกรายการ → กด "Complete Pick"
5. status เปลี่ยนเป็น "picked"
```

### Print Pick List
- กด **"Print Pick List"** → พิมพ์ QWeb PDF
- การพิมพ์ครั้งแรกจะ **เริ่ม SLA timer** อัตโนมัติ
- Pick List แสดง: SKU, ชื่อสินค้า, ตำแหน่ง Pickface, จำนวน

### SLA Status

| สี | ความหมาย | เวลาเหลือ |
|----|---------|----------|
| 🟢 On Track | ปกติ | > 30 นาที |
| 🟡 At Risk | ใกล้หมดเวลา | 0-30 นาที |
| 🔴 Breached | เกิน SLA | ลบ |
| ✓ Done | เสร็จแล้ว | — |

---

## 4. หน้าจอ Pack (แพ็คสินค้า)

**เมนู:** KOB WMS → Operations → Pack  
**Hotkey:** F2

### ขั้นตอน

```
1. เลือก Order (status = picked)
2. กด "Start Pack" → status = "packing"
3. สแกน Barcode สินค้าแต่ละชิ้น (verify):
   - ตรงกับ Pick List ไหม?
   - ✅ ถูก → packed_qty++
   - ❌ ผิด → แจ้งเตือนแดง
4. เมื่อสแกนครบทุกชิ้น:
   - เลือก Box Size (สแกน Box Barcode หรือเลือก dropdown)
   - ระบบแสดง: Fill %, Box Cost, Tape Cost, Total Pack Cost
5. กด "Close Box / Select Box" → ยืนยัน
6. ระบบ:
   ✅ ตัดสต็อค (stock.picking → done)
   ✅ ออก Invoice (account.move → posted)
   ✅ status = "packed"
```

### Box Selection
- ระบบแสดง **AI Suggested Box** (จาก volume คำนวณ)
- Packer เลือกกล่องที่ใช้จริง → scan barcode กล่อง
- ถ้า packer เลือกตรงกับ AI → `box_suggestion_hit = True`

### ข้อมูลที่แสดงหลัง Pack
```
Box Used     : THE BOX 2C (20×15×12 cm)
Fill %       : 72.3%
Box Cost     : ฿8.50
Tape Cost    : ฿1.20
Bubble Wrap  : ฿2.00
Total Cost   : ฿11.70
```

---

## 5. หน้าจอ Outbound (สแกนขาออก)

**เมนู:** KOB WMS → Operations → Outbound  
**Hotkey:** F3

### ขั้นตอน

```
1. Orders ที่ status = "packed" จะปรากฏในรายการ
2. สแกน AWB barcode บนกล่อง
3. ระบบตรวจสอบ:
   - AWB ตรงกับ Order ไหม?
   - กล่องอยู่ใน bin ของ Courier ที่ถูกต้องไหม?
4. ✅ ถูก → status = "scanned", บันทึก timestamp
5. ❌ ผิด Courier bin → แจ้งเตือน "กรุณาย้ายไปถังขนส่ง [COURIER]"
```

### Error Handling
- **Duplicate scan** → แจ้ง "AWB นี้สแกนแล้ว"
- **AWB ไม่พบ** → แจ้ง "ไม่พบ Order สำหรับ AWB นี้"

---

## 6. หน้าจอ Dispatch (จัดส่ง)

**เมนู:** KOB WMS → Operations → Dispatch  
**Hotkey:** F4

### ขั้นตอน

```
1. เลือก Courier
2. ระบบแสดงรายการ Orders ทั้งหมดที่ status = "scanned" ของ Courier นั้น
3. ตรวจนับกล่อง (Physical vs System count)
4. กรอก: ชื่อคนขับ, เวลาออก
5. กด "Dispatch" → status ทุก order = "shipped"
6. พิมพ์ Manifest
```

### Manifest
- รวม orders ตาม Courier
- แสดง: เลข AWB, ชื่อลูกค้า, น้ำหนัก, จำนวนกล่อง
- พิมพ์ได้ทั้ง A4 และ Label

---

## 7. Box Recommender Wizard

**เมนู:** KOB WMS → Analytics → Box Recommender  
**สิทธิ์:** Supervisor / Manager

### วิธีใช้

```
1. เปิด Wizard → กด "Add Line"
2. ระบุสินค้าและจำนวน:
   Product: [SKN-SRM-030] SKINOXY Serum 30ml
   Qty:     3
   (เพิ่มได้หลาย SKU)
3. ตั้ง Fill Buffer %: 15% (default)
   (ป้องกัน product volume underestimate)
4. กด "🔍 Recommend Box"
5. ระบบคำนวณ:
   Total Vol = Σ (product.volume × qty) × (1 + buffer%)
   หา 3 กล่องเล็กสุดที่ volume_cm3 >= required_vol
6. ดูผลลัพธ์:
   🥇 Recommended: THE BOX 2C — Fill 68% — ฿11.70/box
   🥈 Alt 1:       THE BOX C  — Fill 82% — ฿9.50/box
   🥉 Alt 2:       THE BOX 3C — Fill 51% — ฿14.00/box
7. กด "↩ Try Again" เพื่อแก้ input
   กด "Close" เพื่อปิด
```

---

## 8. Cycle Count (นับสต็อค)

**เมนู:** KOB WMS → Inventory → Count Sessions

### สร้าง Session ใหม่

```
1. KOB WMS → Count Sessions → New
2. ระบุ:
   - Type: Full Count / Cycle Count
   - Warehouse: WH
   - Responsible: [ชื่อ supervisor]
   - Variance Threshold: 5% (default)
3. กด "Start" → state = in_progress
4. ระบบ snapshot stock ปัจจุบัน
```

### สร้าง Tasks

```
1. กด "Create Tasks"
2. ระบบสร้าง wms.count.task ต่อ Location × Product
3. Assign งานให้ Worker แต่ละคน
```

### นับสต็อค (Worker)

```
Worker เปิด Task ที่ได้รับมอบหมาย:
1. ไปที่ Location (e.g. Zone A, Rack A-01)
2. สแกน / กรอก counted_qty แต่ละ SKU
3. กด "Submit" → state = submitted

ระบบคำนวณอัตโนมัติ:
  variance = counted_qty - system_qty
  variance_pct = |variance| / system_qty × 100

  variance = 0         → ✅ matched
  variance_pct ≤ 5%    → ✅ variance_approved
  variance_pct > 5%    → ⚠️ needs_recount
```

### Reconcile และ Apply

```
1. Supervisor กด "Reconcile" → ดู Adjustments ทั้งหมด
2. ตรวจสอบ variance ทุกรายการ
3. ไปที่ Odoo Inventory → Physical Inventory
4. Apply All → Odoo ตัดสต็อคตาม counted_qty
5. กลับมา WMS → กด "Mark as Applied" ทีละ adjustment
6. กด "Done" → Session ปิด
```

> ⚠️ **ข้อสำคัญ:** WMS ไม่ write stock.quant โดยตรง — ต้องใช้ Odoo Physical Inventory Apply All

---

## 9. Box Analytics

**เมนู:** KOB WMS → Analytics

### 9.1 Box Usage Analytics

| หน้า | ข้อมูล |
|------|-------|
| Box Usage 360° | กล่องแต่ละ size ถูกใช้กี่ครั้ง, Fill % เฉลี่ย, ต้นทุน |
| Product vs Box | สินค้าแต่ละตัวถูกแพ็คใน box size ไหนบ้าง |
| Platform Breakdown | Shopee ใช้กล่องอะไรมากสุด, Lazada ใช้อะไร |

### 9.2 Export Excel

```
กด "Export Excel" → ดาวน์โหลด .xlsx
Sheet 1: Box Summary (by size)
Sheet 2: By Platform
Sheet 3: Product × Box matrix
```

---

## 10. ตั้งค่าระบบ (Manager)

### 10.1 ตั้งค่า Box Sizes

**เมนู:** KOB WMS → Configuration → Box Sizes

```
สามารถแก้ไข:
- Unit Cost (ราคากล่อง ฿)
- Tape rounds / overlap_cm / cost_per_m
- Bubble wrap cost
- Current Stock / Restock Level
```

### 10.2 ตั้งค่า SLA

**เมนู:** KOB WMS → Configuration → SLA Config

```
ตั้งต่อ Platform:
Platform      : Shopee
Pick SLA      : 120 นาที
Pack SLA      : 60 นาที
Ship SLA      : 240 นาที
Work Start    : 09:00
Work End      : 18:00
Include Weekend: ✗
```

### 10.3 จัดการ WMS Workers

**เมนู:** KOB WMS → Configuration → WMS Workers

```
สร้าง Worker:
Name     : สมชาย มีสุข
Username : somchai01
Role     : picker
PIN      : 1234

Worker login ที่ /kob/login ด้วย username + PIN
```

### 10.4 ตั้งค่า API (Platform)

**เมนู:** KOB WMS → Configuration → API Config

```
Platform : Shopee
API Key  : xxxxxxxxxx
Secret   : xxxxxxxxxx
Shop ID  : xxxxxxxxxx
Active   : ✓
```

---

## 11. Error & Troubleshooting

### สต็อคไม่ถูกตัด

```
อาการ: หลัง Pack เสร็จ stock.picking ยังเป็น "assigned" ไม่เป็น "done"

สาเหตุ:
1. ไม่มี Reserved Stock (picking ยัง confirmed ไม่ assigned)
2. มี Immediate Transfer wizard popup (ถูก handle โดย skip_immediate=True)

วิธีแก้:
- ไปที่ Inventory → Delivery Orders → เปิด Picking → ตรวจ Detailed Operations
- ตรวจว่า "Done Qty" มีค่าหรือไม่
- ถ้าไม่มี → Validate manually → ระบุ Immediate Transfer
- แก้ที่ต้นเหตุ: ตรวจ reserved qty ว่า action_assign() ทำงานครบ
```

### Invoice ไม่ถูกสร้าง

```
อาการ: Pack แล้วไม่มี Invoice ใน Accounting

สาเหตุ:
1. Sale Order ไม่ได้ confirm
2. Policy บน Product ไม่ใช่ "On Delivery"

วิธีแก้:
- ตรวจ Sale Order → ต้อง state = 'sale'
- Product → Invoicing Policy = "Based on Delivered Quantity"
```

### Box Fill % = 0

```
สาเหตุ: product.template.volume ยังเป็น 0

วิธีแก้:
Products → [ชื่อสินค้า] → Sales → Volume ใส่ค่าเป็น m³
(เช่น ขวด 30ml ≈ 0.0001 m³)
```

### SLA ไม่เริ่มนับ

```
สาเหตุ: ยังไม่ได้ Print Pick List ครั้งแรก
วิธีแก้: กด "Print Pick List" → SLA timer จะเริ่มนับ
```

### Worker ล็อกอินไม่ได้

```
สาเหตุ: failed_login_count >= 5 → locked 15 นาที

วิธีแก้ (Manager):
KOB WMS → Workers → [ชื่อ Worker] → แก้ไข:
  Failed Logins: 0
  Locked Until : (ลบค่า)
```

---

## ติดต่อ Dev

- **GitHub:** https://github.com/samuny2329/kob-wms-addon
- **Email:** sivaporn.t@kissofbeauty.co.th
- **Odoo Version:** 18.0 Community
- **Module:** kob_wms v2.11.0
