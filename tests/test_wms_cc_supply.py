from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'kob_wms_cc_supply')
class TestWmsCcSupply(TransactionCase):
    """Command Center Sprint CC-1 — Supply Chain Audit."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Reorder = cls.env['wms.cc.reorder.monitor']
        cls.Demand = cls.env['wms.cc.demand.forecast']
        cls.Leadtime = cls.env['wms.cc.supplier.leadtime']
        cls.PoRem = cls.env['wms.cc.po.reminder']

    # ── Reorder Monitor ─────────────────────────────────────────────────
    def test_01_reorder_view_queryable(self):
        rows = self.Reorder.search([], limit=5)
        for r in rows:
            self.assertIn(r.severity, ('ok', 'watch', 'shortage', 'critical'))
            self.assertTrue(r.product_id)

    def test_02_reorder_shortage_non_negative(self):
        rows = self.Reorder.search([], limit=20)
        for r in rows:
            self.assertGreaterEqual(r.shortage_qty, 0)

    def test_03_reorder_severity_matches_qty(self):
        rows = self.Reorder.search([], limit=20)
        for r in rows:
            if r.severity == 'critical':
                self.assertTrue(
                    r.current_qty <= 0
                    or r.current_qty < r.product_min_qty * 0.5)
            elif r.severity == 'ok':
                self.assertTrue(r.current_qty >= r.product_min_qty * 1.2)

    def test_04_reorder_cron_returns_count(self):
        result = self.Reorder.cron_check_critical()
        self.assertIn('critical_count', result)
        self.assertGreaterEqual(result['critical_count'], 0)

    # ── Demand Forecast ─────────────────────────────────────────────────
    def test_05_demand_view_queryable(self):
        rows = self.Demand.search([], limit=5)
        for r in rows:
            self.assertGreater(r.qty_30d, 0)
            self.assertTrue(r.product_id)

    def test_06_demand_forecast_calculation(self):
        """forecast_7d should be ~ qty_30d × 7/30."""
        rows = self.Demand.search([], limit=10)
        for r in rows:
            expected = r.qty_30d * 7.0 / 30.0
            self.assertAlmostEqual(r.forecast_7d, expected, places=1)

    def test_07_demand_days_of_stock_non_negative(self):
        rows = self.Demand.search([], limit=20)
        for r in rows:
            self.assertGreaterEqual(r.days_of_stock, 0)

    # ── Supplier Lead Time ──────────────────────────────────────────────
    def test_08_leadtime_view_queryable(self):
        rows = self.Leadtime.search([], limit=5)
        for r in rows:
            self.assertGreater(r.po_count, 0)
            self.assertTrue(r.partner_id)
            # on_time_pct in 0..100
            self.assertGreaterEqual(r.on_time_pct, 0)
            self.assertLessEqual(r.on_time_pct, 100)

    # ── PO Reminder ─────────────────────────────────────────────────────
    def test_09_po_reminder_cron_does_not_crash(self):
        result = self.PoRem.cron_scan_overdue_pos(grace_days=3)
        self.assertIn('overdue_count', result)
        self.assertIn('reminders_created', result)

    def test_10_po_reminder_acknowledge(self):
        # Find any confirmed PO with pending picking
        POs = self.env['purchase.order'].sudo()
        po = POs.search([('state', '=', 'purchase')], limit=1)
        if not po:
            # Skip if no PO exists in the test DB
            return
        reminder = self.PoRem.create({
            'purchase_order_id': po.id,
            'overdue_days': 5,
        })
        self.assertFalse(reminder.acknowledged)
        reminder.action_acknowledge()
        self.assertTrue(reminder.acknowledged)
