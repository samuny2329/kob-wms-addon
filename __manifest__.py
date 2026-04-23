{
    'name': 'KOB WMS Pro',
    'version': '18.0.2.22.0',
    'category': 'Inventory/Warehouse',
    'summary': 'Enterprise Warehouse Management System (Kiss of Beauty)',
    'description': """
KOB WMS Pro — Enterprise Warehouse Management
==============================================
Native Odoo 18 port of the KOB React WMS SPA.

Features
--------
* Pick / Pack / Scan / Dispatch fulfilment workflows (fullscreen POS-style)
* Sales Orders with line items, SKU scanning, barcode-driven fulfilment
* Courier master + Courier Batch (with signature capture)
* Scanned-items registry (outbound scan log)
* Activity Log (KPI + audit)
* Platform API configuration (Odoo / Shopee / Lazada / TikTok)
* Zones / Racks / Pickfaces / Guided Cycle Count
* Box sizing (28 THE BOX sizes, tape formula, bubble-wrap, fill %)
* Box Recommender — enter SKUs → get smallest fitting box + cost breakdown
* Box Analytics 360° + Product vs Box SQL view + Excel export
* SLA configuration & monitor
* Worker Performance KPI Assessment
* Integration with stock.picking and sale.order
* Security groups (Worker / Supervisor / Manager)
    """,
    'author': 'KOB',
    'website': 'https://github.com/samuny2329/kob-wms',
    'depends': [
        'base',
        'stock',
        'product',
        'mail',
        'sale_management',
        'point_of_sale',
        'spreadsheet_dashboard',
        'product_expiry',
    ],
    'data': [
        # ── Security (always first) ──────────────────────────────────────────
        'security/wms_security.xml',
        'security/ir.model.access.csv',

        # ── Sequences & base data ────────────────────────────────────────────
        'data/wms_sequence.xml',

        # ── Warehouse structure ──────────────────────────────────────────────
        'views/wms_zone_views.xml',
        'views/wms_rack_views.xml',
        'views/wms_pickface_views.xml',

        # ── Cycle Count ──────────────────────────────────────────────────────
        'views/wms_count_adjustment_views.xml',
        'views/wms_count_session_views.xml',
        'views/wms_count_task_views.xml',

        # ── Fulfilment ───────────────────────────────────────────────────────
        'views/wms_courier_views.xml',
        'views/wms_sales_order_views.xml',
        'views/wms_courier_batch_views.xml',

        # ── Analytics & Reporting views ──────────────────────────────────────
        'views/wms_activity_log_views.xml',
        'views/wms_worker_performance_views.xml',
        'views/wms_kpi_target_views.xml',
        'views/wms_automation_audit_views.xml',
        'views/wms_sprint1_views.xml',
        'views/wms_sla_config_views.xml',

        # ── Configuration ────────────────────────────────────────────────────
        'views/wms_api_config_views.xml',
        'views/wms_dashboard_views.xml',

        # ── Odoo stock / POS extensions ──────────────────────────────────────
        'views/stock_picking_inherit_views.xml',
        'views/pos_order_inherit_views.xml',

        # ── Screen / action launchers ────────────────────────────────────────
        'views/wms_scan_screen_action.xml',
        'views/wms_count_screen_action.xml',
        'views/wms_pos_launcher_actions.xml',
        'views/wms_wizard_launcher_actions.xml',

        # ── Wizards ──────────────────────────────────────────────────────────
        'wizards/wms_scan_wizard_views.xml',
        'wizards/wms_cancel_return_wizard_views.xml',
        'wizards/wms_box_recommender_wizard_views.xml',

        # ── Portal & user management ─────────────────────────────────────────
        'views/kob_portal_templates.xml',
        'views/kob_wms_user_views.xml',

        # ── Static master data ───────────────────────────────────────────────
        'data/kob_wms_user_data.xml',
        'data/wms_count_cron.xml',
        'data/wms_automation_audit_cron.xml',
        'data/wms_platform_sync_cron.xml',
        'data/wms_sprint1_crons.xml',
        'data/wms_sale_order_types.xml',
        'data/wms_kpi_templates.xml',
        'data/wms_kpi_iso_sustainability.xml',  # P9: ISO, GMP & Sustainability pillar
        'data/wms_box_size_data.xml',
        'data/wms_pin_init.xml',

        # ── Reports (QWeb PDF — must load after actions are registered) ───────
        'report/wms_reports.xml',
        'report/wms_kpi_assessment_template.xml',
        'report/wms_count_session_report_template.xml',
        'report/wms_pick_list_template.xml',
        'report/wms_box_label_template.xml',
        'report/wms_awb_label_template.xml',
        'report/wms_awb_label_100x150_template.xml',
        'report/wms_qc_monthly_report_template.xml',

        # ── Inventory & Box Analytics ────────────────────────────────────────
        'views/wms_inventory_views.xml',
        'views/wms_box_analytics_views.xml',
        'views/wms_product_box_analytics_views.xml',

        # ── Spreadsheet Dashboards ───────────────────────────────────────────
        'data/wms_dashboard_data.xml',

        # ── Fulfilment queue list views ──────────────────────────────────────
        'views/wms_pick_list_view.xml',
        'views/wms_pack_list_view.xml',
        'views/wms_outbound_list_view.xml',
        'views/wms_dispatch_list_view.xml',

        # ── Menus (last — all action XML IDs must be registered above) ────────
        'views/wms_menus.xml',
    ],
    'demo': [
        'data/wms_demo_data.xml',
    ],
    'assets': {
        'web.assets_backend': [
            # ── Shared fulfilment design system ──────────────────────────────
            'kob_wms/static/src/js/wms_fulfilment/wms_fulfilment.scss',
            # ── Worker login screen ───────────────────────────────────────────
            'kob_wms/static/src/js/wms_login/wms_login_screen.js',
            'kob_wms/static/src/js/wms_login/wms_login_screen.xml',
            # ── Legacy scan screen ────────────────────────────────────────────
            'kob_wms/static/src/js/wms_scan_screen/wms_scan_screen.js',
            'kob_wms/static/src/js/wms_scan_screen/wms_scan_screen.xml',
            # ── WMS List View (queue screens with scan bar) ───────────────────
            'kob_wms/static/src/js/wms_list/wms_list_view.js',
            # ── WMS Scan Bar widget (in-form barcode input) ───────────────────
            'kob_wms/static/src/js/wms_scan_bar/wms_scan_bar.js',
            'kob_wms/static/src/js/wms_scan_bar/wms_scan_bar.xml',
            # ── WMS Count Screen (mobile / handheld guided count) ─────────────
            'kob_wms/static/src/scss/wms_count_screen.scss',
            'kob_wms/static/src/js/wms_count_screen/wms_count_screen.js',
            'kob_wms/static/src/js/wms_count_screen/wms_count_screen.xml',
            # ── WMS Systray (worker identity + logout) ────────────────────────
            'kob_wms/static/src/js/wms_systray/wms_systray.js',
            'kob_wms/static/src/js/wms_systray/wms_systray.xml',
            # ── Fulfilment screens ────────────────────────────────────────────
            'kob_wms/static/src/js/wms_pick_pos/wms_pick_screen.js',
            'kob_wms/static/src/js/wms_pick_pos/wms_pick_screen.xml',
            'kob_wms/static/src/js/wms_pack_pos/wms_pack_screen.js',
            'kob_wms/static/src/js/wms_pack_pos/wms_pack_screen.xml',
            'kob_wms/static/src/js/wms_outbound/wms_outbound_screen.js',
            'kob_wms/static/src/js/wms_outbound/wms_outbound_screen.xml',
            'kob_wms/static/src/js/wms_dispatch/wms_dispatch_screen.js',
            'kob_wms/static/src/js/wms_dispatch/wms_dispatch_screen.xml',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
