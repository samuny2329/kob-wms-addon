from datetime import date, timedelta

from odoo.tests.common import TransactionCase, tagged
from odoo.exceptions import UserError


@tagged('post_install', '-at_install', 'kob_wms_sprint2')
class TestWmsSprint2(TransactionCase):
    """Sprint 2 — Outgoing QC Checkpoint + KPI Alert Rule Engine."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Product = cls.env['product.product']
        cls.Check = cls.env['wms.quality.check']
        cls.Rule = cls.env['wms.kpi.alert.rule']

        cls.product = cls.Product.create({
            'name': 'Sprint2 QC Product',
            'default_code': 'SP2-QC-%d' % cls.env.uid,
            'type': 'consu',
        })
        cls.product.product_tmpl_id.qc_required_outgoing = True

    # ── QC Check ─────────────────────────────────────────────────────────
    def test_01_qc_check_pass_workflow(self):
        # Create a minimal wms.sales.order
        WmsOrder = self.env['wms.sales.order']
        order = WmsOrder.create({
            'ref': 'SP2-ORD-01-%d' % self.env.uid,
            'customer': 'Test Customer',
        })
        check = self.Check.create({
            'wms_order_id': order.id,
            'product_id': self.product.id,
            'expected_qty': 5,
        })
        self.assertEqual(check.state, 'pending')
        check.action_pass()
        self.assertEqual(check.state, 'passed')
        self.assertTrue(check.checked_at)
        self.assertEqual(check.checked_by_id, self.env.user)

    def test_02_qc_check_fail_creates_defect(self):
        WmsOrder = self.env['wms.sales.order']
        order = WmsOrder.create({
            'ref': 'SP2-ORD-02-%d' % self.env.uid,
            'customer': 'Test Customer',
        })
        check = self.Check.create({
            'wms_order_id': order.id,
            'product_id': self.product.id,
            'expected_qty': 3,
        })
        check.action_fail()
        self.assertEqual(check.state, 'failed')
        self.assertTrue(check.defect_id)
        self.assertEqual(check.defect_id.product_id, self.product)
        self.assertEqual(check.defect_id.severity, 'high')

    def test_03_qc_check_cannot_pass_twice(self):
        WmsOrder = self.env['wms.sales.order']
        order = WmsOrder.create({
            'ref': 'SP2-ORD-03-%d' % self.env.uid,
            'customer': 'Test Customer',
        })
        check = self.Check.create({
            'wms_order_id': order.id,
            'product_id': self.product.id,
            'expected_qty': 1,
        })
        check.action_pass()
        with self.assertRaises(UserError):
            check.action_pass()

    # ── QC hook on wms.sales.order.pack flow ─────────────────────────────
    def test_04_qc_count_computes(self):
        WmsOrder = self.env['wms.sales.order']
        order = WmsOrder.create({
            'ref': 'SP2-ORD-04-%d' % self.env.uid,
            'customer': 'Test Customer',
        })
        # No checks yet
        self.assertEqual(order.quality_check_count, 0)
        self.assertEqual(order.quality_check_pending, 0)

        # Create pending + passed checks
        self.Check.create({
            'wms_order_id': order.id,
            'product_id': self.product.id,
            'expected_qty': 1,
            'state': 'pending',
        })
        c2 = self.Check.create({
            'wms_order_id': order.id,
            'product_id': self.product.id,
            'expected_qty': 1,
        })
        c2.action_pass()
        order.invalidate_recordset()
        self.assertEqual(order.quality_check_count, 2)
        self.assertEqual(order.quality_check_pending, 1)

    # ── KPI Alert Rule ───────────────────────────────────────────────────
    def test_05_rule_triggers_when_threshold_breached(self):
        # Seed a daily report with low SLA pick %
        today = date.today()
        self.env['wms.daily.report'].search([
            ('report_date', '=', today - timedelta(days=1))
        ]).unlink()
        report = self.env['wms.daily.report'].create({
            'report_date': today - timedelta(days=1),
            'sla_pick_pct': 80.0,
            'total_orders': 50,
            'shipped_orders': 40,
        })
        rule = self.Rule.create({
            'name': 'Test SLA Pick < 90',
            'metric_code': 'sla_pick_pct',
            'operator': 'lt',
            'threshold': 90,
            'frequency': 'daily',
            'active': True,
        })
        fired = rule._evaluate_one(today - timedelta(days=1), force=True)
        self.assertTrue(fired)
        self.assertTrue(rule.last_triggered_at)
        self.assertEqual(rule.trigger_count, 1)
        self.assertAlmostEqual(rule.last_value, 80.0, places=1)

    def test_06_rule_does_not_trigger_when_healthy(self):
        today = date.today()
        self.env['wms.daily.report'].search([
            ('report_date', '=', today - timedelta(days=2))
        ]).unlink()
        self.env['wms.daily.report'].create({
            'report_date': today - timedelta(days=2),
            'sla_pick_pct': 98.0,
            'total_orders': 50,
            'shipped_orders': 49,
        })
        rule = self.Rule.create({
            'name': 'Test SLA Pick < 90 (healthy)',
            'metric_code': 'sla_pick_pct',
            'operator': 'lt',
            'threshold': 90,
            'frequency': 'daily',
            'active': True,
        })
        fired = rule._evaluate_one(today - timedelta(days=2), force=True)
        self.assertFalse(fired)
        self.assertEqual(rule.trigger_count, 0)

    def test_07_operators_apply_correctly(self):
        from odoo.addons.kob_wms.models.wms_kpi_alert_rule import _apply
        self.assertTrue(_apply('lt', 10, 20))
        self.assertFalse(_apply('lt', 20, 10))
        self.assertTrue(_apply('gte', 20, 20))
        self.assertTrue(_apply('eq', 5.0001, 5.0))
        self.assertFalse(_apply('lt', None, 5))

    def test_08_cron_evaluate_all_does_not_crash(self):
        # With a few active rules, cron should run without error
        self.Rule.create({
            'name': 'Cron Test 1',
            'metric_code': 'total_orders',
            'operator': 'gt',
            'threshold': 1000000,
            'frequency': 'daily',
            'active': True,
        })
        result = self.Rule.cron_evaluate_all()
        self.assertIn('evaluated', result)
        self.assertIn('fired', result)

    def test_09_weekly_rule_only_fires_monday(self):
        """Weekly rule should only fire when as_of_date is a Monday."""
        rule = self.Rule.create({
            'name': 'Weekly test',
            'metric_code': 'total_orders',
            'operator': 'gt',
            'threshold': 0,
            'frequency': 'weekly',
            'active': True,
        })
        # Pick a known Monday and non-Monday
        monday = date(2026, 4, 20)   # check calendar — doesn't matter, use weekday
        while monday.weekday() != 0:
            monday = monday + timedelta(days=1)
        non_monday = monday + timedelta(days=3)
        self.assertTrue(rule._should_fire_today(monday))
        self.assertFalse(rule._should_fire_today(non_monday))

    def test_10_monthly_rule_fires_1st(self):
        rule = self.Rule.create({
            'name': 'Monthly test',
            'metric_code': 'total_orders',
            'operator': 'gt',
            'threshold': 0,
            'frequency': 'monthly',
            'active': True,
        })
        self.assertTrue(rule._should_fire_today(date(2026, 6, 1)))
        self.assertFalse(rule._should_fire_today(date(2026, 6, 15)))
