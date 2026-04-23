from datetime import date

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'kob_wms_cc_ops')
class TestWmsCcOps(TransactionCase):
    """CC Sprints — Accounting + Logistics + HR audit views."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.AcctHub = cls.env['wms.cc.accounting.hub']
        cls.OpEx = cls.env['wms.cc.opex.tracker']
        cls.PlatformFee = cls.env['wms.cc.platform.fee.audit']
        cls.Otif = cls.env['wms.cc.otif.monitor']
        cls.Otd = cls.env['wms.cc.otd.rate']
        cls.Turnover = cls.env['wms.cc.hr.turnover']
        cls.Training = cls.env['wms.cc.training.log']

    # ── Accounting views ────────────────────────────────────────────────
    def test_01_acct_hub_queryable(self):
        rows = self.AcctHub.search([], limit=5)
        for r in rows:
            self.assertIn(r.account_type,
                          ('revenue', 'customer_fee_405',
                           'vendor_fee_603', 'other'))

    def test_02_opex_queryable(self):
        rows = self.OpEx.search([], limit=5)
        for r in rows:
            # period_month is YYYY-MM format
            if r.period_month:
                self.assertRegex(r.period_month, r'\d{4}-\d{2}')

    def test_03_platform_fee_labels(self):
        rows = self.PlatformFee.search([], limit=10)
        for r in rows:
            self.assertTrue(r.platform_label)

    # ── Logistics views ─────────────────────────────────────────────────
    def test_04_otif_invariant_otif_implies_on_time_and_in_full(self):
        rows = self.Otif.search([('is_otif', '=', True)], limit=10)
        for r in rows:
            self.assertTrue(r.is_on_time)
            self.assertTrue(r.is_in_full)

    def test_05_otd_percentages_in_range(self):
        rows = self.Otd.search([], limit=10)
        for r in rows:
            self.assertGreaterEqual(r.otd_pct, 0)
            self.assertLessEqual(r.otd_pct, 100)
            self.assertGreaterEqual(r.otif_pct, 0)
            self.assertLessEqual(r.otif_pct, 100)
            # OTIF is subset of OTD
            self.assertLessEqual(r.otif_count, r.on_time_count)

    # ── HR views ────────────────────────────────────────────────────────
    def test_06_turnover_percentage_in_range(self):
        rows = self.Turnover.search([], limit=10)
        for r in rows:
            self.assertGreaterEqual(r.turnover_pct, 0)
            self.assertLessEqual(r.turnover_pct, 100)
            self.assertEqual(r.active_count + r.inactive_count,
                             r.total_count)

    def test_07_training_log_crud(self):
        # Need an employee
        emp = self.env['hr.employee'].search([('active', '=', True)], limit=1)
        if not emp:
            emp = self.env['hr.employee'].create({
                'name': 'Test Employee CC-OPS',
            })
        t = self.Training.create({
            'name': 'Test Safety Training',
            'employee_id': emp.id,
            'hours': 2.5,
            'training_type': 'ojt',
            'training_date': date.today(),
        })
        self.assertEqual(t.department_id, emp.department_id)
        self.assertEqual(t.hours, 2.5)
