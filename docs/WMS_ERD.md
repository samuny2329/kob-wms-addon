# KOB WMS Pro — Entity Relationship Diagram

> **Version:** 2.11.0 | **Odoo:** 18.0 | **Module:** `kob_wms`

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                     KOB WMS Pro (Odoo Addon)                        │
│                                                                      │
│  OWL Screens (Pick / Pack / Outbound / Dispatch / Count)            │
│       ↕  JSON-RPC via Odoo controller                               │
│  Python Models (wms.* / kob.wms.*)                                  │
│       ↕  ORM                                                        │
│  PostgreSQL 16 (port 5433) — odoo18_db                              │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Full ERD (Mermaid)

```mermaid
erDiagram

    %% ══════════════════════════════════════
    %% CORE FULFILMENT
    %% ══════════════════════════════════════

    wms_sales_order {
        int     id                  PK
        char    name                "WMS/2026/00001"
        char    ref                 "Platform order ref"
        char    customer
        int     partner_id          FK
        sel     platform            "odoo|shopee|lazada|tiktok|pos|manual"
        int     courier_id          FK
        char    awb                 "Tracking number"
        char    box_barcode         "Scanned box code"
        sel     status              "pending→picking→picked→packing→packed→shipped"
        int     sale_order_id       FK "sale.order"
        int     picking_id          FK "stock.picking"
        int     actual_box_id       FK "wms.box.size"
        int     suggested_box_id    FK "wms.box.size"
        int     kob_picker_id       FK "kob.wms.user"
        int     kob_packer_id       FK "kob.wms.user"
        float   order_vol_m3
        float   order_weight_kg
        float   box_fill_pct
        float   total_pack_cost
        sel     sla_status          "on_track|at_risk|breached|done"
        datetime sla_pick_deadline
        datetime sla_pack_deadline
        datetime sla_ship_deadline
        datetime sla_start_at
        datetime pick_start_at
        datetime picked_at
        datetime pack_start_at
        datetime packed_at
        datetime shipped_at
    }

    wms_sales_order_line {
        int     id              PK
        int     order_id        FK "wms.sales.order"
        int     product_id      FK "product.product"
        char    product_name
        char    sku
        float   expected_qty
        float   picked_qty
        float   packed_qty
        char    barcode
    }

    %% ══════════════════════════════════════
    %% BOX MANAGEMENT
    %% ══════════════════════════════════════

    wms_box_size {
        int     id                  PK
        char    code                "B, C, 2C, L, XL..."
        char    label               "Display name"
        float   length
        float   width
        float   height
        float   volume_cm3          "Computed: L×W×H"
        float   volume              "Computed: m³"
        float   weight_limit
        float   unit_cost           "Box price ฿"
        int     tape_rounds
        float   tape_overlap_cm
        float   tape_cost_per_m
        float   tape_length_m       "Computed"
        float   tape_cost_est       "Computed ฿"
        float   bubble_cost_est
        float   total_material_cost "Computed: box+tape+bubble"
        int     current_stock
        int     restock_qty
        int     restock_lead_days
    }

    wms_box_analytics {
        int     id                  PK
        "SQL VIEW — no writes"      ""
        int     actual_box_id       FK
        int     platform            ""
        float   avg_fill_pct
        int     order_count
        float   total_pack_cost
        float   avg_pack_cost
    }

    wms_product_box_analytics {
        int     id                  PK
        "SQL VIEW — no writes"      ""
        int     product_id          FK
        int     box_id              FK
        int     times_used
        float   avg_fill_pct
    }

    %% ══════════════════════════════════════
    %% CYCLE / FULL COUNT
    %% ══════════════════════════════════════

    wms_count_session {
        int     id                  PK
        char    name                "CNT/2026/001"
        sel     session_type        "full|cycle"
        sel     state               "draft|in_progress|reconciling|done|cancelled"
        int     warehouse_id        FK
        int     responsible_id      FK "res.users"
        datetime date_start
        datetime date_end
        float   variance_threshold_pct  "Default 5%"
        int     assigned_count      "Computed"
        int     counting_count      "Computed"
        int     submitted_count     "Computed"
        int     done_count          "Computed"
        float   progress_pct        "Computed"
    }

    wms_count_task {
        int     id                  PK
        int     session_id          FK "wms.count.session"
        int     location_id         FK "stock.location"
        int     product_id          FK "product.product"
        int     assigned_to         FK "kob.wms.user"
        float   system_qty
        sel     state               "assigned|counting|submitted|done"
    }

    wms_count_entry {
        int     id                  PK
        int     task_id             FK "wms.count.task"
        int     session_id          FK "wms.count.session"
        int     product_id          FK "product.product"
        int     location_id         FK "stock.location"
        float   counted_qty
        float   system_qty
        float   variance
        float   variance_pct
        sel     count_status        "matched|variance_approved|needs_recount"
    }

    wms_count_adjustment {
        int     id                  PK
        int     session_id          FK "wms.count.session"
        int     product_id          FK "product.product"
        int     location_id         FK "stock.location"
        float   qty_before
        float   qty_after
        float   variance
        boolean applied
        datetime applied_at
    }

    wms_count_snapshot {
        int     id                  PK
        int     session_id          FK
        int     product_id          FK
        int     location_id         FK
        float   qty_on_hand
        datetime snapshot_at
    }

    %% ══════════════════════════════════════
    %% WORKERS & USERS
    %% ══════════════════════════════════════

    kob_wms_user {
        int     id              PK
        char    name
        char    position
        char    username        UNIQUE
        char    password_hash
        char    pin
        int     res_user_id     FK "res.users (optional)"
        sel     role            "admin|supervisor|picker|packer|outbound|coordinator|viewer"
        boolean is_active
        char    token
        datetime token_expiry
        datetime last_login
        int     login_count
        int     failed_login_count
        datetime locked_until
    }

    %% ══════════════════════════════════════
    %% WAREHOUSE STRUCTURE
    %% ══════════════════════════════════════

    wms_zone {
        int     id          PK
        char    name        "Zone A, Zone B..."
        char    code
        int     warehouse_id FK
        boolean active
    }

    wms_rack {
        int     id          PK
        char    name        "Rack A-01"
        int     zone_id     FK "wms.zone"
        int     shelves
        boolean active
    }

    wms_pickface {
        int     id              PK
        char    code            "A-01-01"
        int     rack_id         FK "wms.rack"
        int     product_id      FK "product.product"
        int     location_id     FK "stock.location"
        float   min_qty
        float   max_qty
        boolean active
    }

    %% ══════════════════════════════════════
    %% COURIER & DISPATCH
    %% ══════════════════════════════════════

    wms_courier {
        int     id          PK
        char    name        "Flash Express"
        char    code        "FLASH"
        char    prefix      "FLTH"
        boolean active
    }

    wms_courier_batch {
        int     id              PK
        char    name
        int     courier_id      FK "wms.courier"
        sel     state           "draft|sealed|dispatched"
        datetime dispatch_at
        int     order_count     "Computed"
    }

    %% ══════════════════════════════════════
    %% CONFIGURATION
    %% ══════════════════════════════════════

    wms_sla_config {
        int     id                  PK
        sel     platform            "default|shopee|lazada|tiktok|pos|manual"
        int     pick_sla_minutes
        int     pack_sla_minutes
        int     ship_sla_minutes
        char    work_start          "09:00"
        char    work_end            "18:00"
        boolean include_weekend
    }

    wms_api_config {
        int     id              PK
        char    name
        sel     platform        "shopee|lazada|tiktok|flash|kerry|jt|thaipost"
        char    api_key
        char    api_secret
        char    shop_id
        boolean active
    }

    wms_kpi_target {
        int     id          PK
        int     user_id     FK "kob.wms.user"
        sel     metric      "pick_rate|pack_rate|accuracy|sla_pct"
        float   target
        date    date_from
        date    date_to
    }

    wms_worker_performance {
        int     id          PK
        int     user_id     FK "kob.wms.user"
        date    date
        int     orders_picked
        int     orders_packed
        int     pick_errors
        int     pack_errors
        float   avg_pick_min
        float   avg_pack_min
    }

    wms_activity_log {
        int     id          PK
        int     user_id     FK "kob.wms.user"
        char    action
        char    ref
        datetime timestamp
    }

    %% ══════════════════════════════════════
    %% ODOO STANDARD (referenced by kob_wms)
    %% ══════════════════════════════════════

    sale_order {
        int     id          PK
        char    name        "S00001"
        int     team_id     FK "platform"
    }

    stock_picking {
        int     id          PK
        char    name        "WH/OUT/00001"
        sel     state       "draft|assigned|done|cancel"
    }

    product_product {
        int     id              PK
        char    default_code    "SKU"
        char    barcode
        float   volume
        float   weight
    }

    stock_location {
        int     id              PK
        char    complete_name   "WH/Stock/PICKFACE"
    }

    %% ══════════════════════════════════════
    %% RELATIONSHIPS
    %% ══════════════════════════════════════

    wms_sales_order ||--o{ wms_sales_order_line : "line_ids"
    wms_sales_order }o--|| wms_box_size : "actual_box_id"
    wms_sales_order }o--o| wms_box_size : "suggested_box_id"
    wms_sales_order }o--|| wms_courier : "courier_id"
    wms_sales_order }o--o| kob_wms_user : "kob_picker_id"
    wms_sales_order }o--o| kob_wms_user : "kob_packer_id"
    wms_sales_order }o--o| sale_order : "sale_order_id"
    wms_sales_order }o--o| stock_picking : "picking_id"

    wms_sales_order_line }o--|| product_product : "product_id"

    wms_count_session ||--o{ wms_count_task : "task_ids"
    wms_count_session ||--o{ wms_count_entry : "entry_ids"
    wms_count_session ||--o{ wms_count_adjustment : "adjustment_ids"
    wms_count_session ||--o{ wms_count_snapshot : "snapshot_ids"

    wms_count_task }o--|| kob_wms_user : "assigned_to"
    wms_count_task }o--|| product_product : "product_id"
    wms_count_task }o--|| stock_location : "location_id"

    wms_count_entry }o--|| product_product : "product_id"
    wms_count_entry }o--|| stock_location : "location_id"

    wms_zone ||--o{ wms_rack : "rack_ids"
    wms_rack ||--o{ wms_pickface : "pickface_ids"
    wms_pickface }o--|| product_product : "product_id"

    wms_courier ||--o{ wms_courier_batch : "batch_ids"

    kob_wms_user ||--o{ wms_kpi_target : "kpi_ids"
    kob_wms_user ||--o{ wms_worker_performance : "performance_ids"
    kob_wms_user ||--o{ wms_activity_log : "log_ids"

    wms_box_analytics }o--|| wms_box_size : "actual_box_id"
    wms_product_box_analytics }o--|| product_product : "product_id"
    wms_product_box_analytics }o--|| wms_box_size : "box_id"
```

---

## Custom Model Summary

| Model | Table | Type | Records |
|-------|-------|------|---------|
| `wms.sales.order` | `wms_sales_order` | Model | ~หลักพัน/เดือน |
| `wms.sales.order.line` | `wms_sales_order_line` | Model | ~หลายหมื่น |
| `wms.box.size` | `wms_box_size` | Master | 28 sizes |
| `wms.box.analytics` | `wms_box_analytics` | SQL View | read-only |
| `wms.product.box.analytics` | `wms_product_box_analytics` | SQL View | read-only |
| `wms.count.session` | `wms_count_session` | Model | per session |
| `wms.count.task` | `wms_count_task` | Model | per location |
| `wms.count.entry` | `wms_count_entry` | Model | per scan |
| `wms.count.adjustment` | `wms_count_adjustment` | Model | per variance |
| `wms.count.snapshot` | `wms_count_snapshot` | Model | per session |
| `kob.wms.user` | `kob_wms_user` | Model | ~20 workers |
| `wms.zone` | `wms_zone` | Master | ~5 zones |
| `wms.rack` | `wms_rack` | Master | ~30 racks |
| `wms.pickface` | `wms_pickface` | Master | ~200 slots |
| `wms.courier` | `wms_courier` | Master | 7 couriers |
| `wms.courier.batch` | `wms_courier_batch` | Model | daily |
| `wms.sla.config` | `wms_sla_config` | Config | per platform |
| `wms.api.config` | `wms_api_config` | Config | per platform |
| `wms.kpi.target` | `wms_kpi_target` | Config | per worker |
| `wms.worker.performance` | `wms_worker_performance` | Analytics | daily |
| `wms.activity.log` | `wms_activity_log` | Log | per action |
