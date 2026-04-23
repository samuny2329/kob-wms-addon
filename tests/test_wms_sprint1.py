from datetime import date, datetime, timedelta

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'kob_wms_sprint1')
class TestWmsSprint1(TransactionCase):
    """Sprint 1 Quick Wins — Expiry / Defect / Daily / QC Monthly."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Alert = cls.env['wms.expiry.alert']
        cls.Defect = cls.env['wms.quality.defect']
        cls.Daily = cls.env['wms.daily.report']
        cls.QcMonth = cls.env['wms.qc.monthly.report']
        cls.Product = cls.env['product.product']

        cls.product = cls.Product.create({
            'name': 'Sprint1 Test Product',
            'default_code': 'SP1-TEST-%d' % cls.env.uid,
            'type': 'consu',
        })

    # ── wms.expiry.alert ───────────────────────────────────────────────
    def test_01_expiry_alert_severity_expired(self):
        # Create a lot with past expiration
        Lot = self.env['stock.lot']
        lot = Lot.create({
            'name': 'TEST-EXP-%d' % self.env.uid,
            'product_id': self.product.id,
            'expiration_date': datetime.now() - timedelta(days=5),
        })
        alert = self.Alert.create({
            'lot_id': lot.id,
            'alert_date': date.today() + timedelta(days=200),
        })
        self.assertEqual(alert.severity, 'expired')

    def test_02_expiry_alert_severity_urgent(self):
        Lot = self.env['stock.lot']
        lot = Lot.create({
            'name': 'TEST-URG-%d' % self.env.uid,
            'product_id': self.product.id,
            'expiration_date': datetime.now() + timedelta(days=20),
        })
        alert = self.Alert.create({
            'lot_id': lot.id,
            'alert_date': date.today() + timedelta(days=201),
        })
        self.assertEqual(alert.severity, 'urgent')

    def test_03_expiry_cron_does_not_crash(self):
        result = self.Alert.cron_scan_expiry()
        self.assertIn('created', result)
        self.assertIn('scanned', result)

    # ── wms.quality.defect ─────────────────────────────────────────────
    def test_04_defect_create_and_workflow(self):
        d = self.Defect.create({
            'product_id': self.product.id,
            'defect_qty': 5,
            'defect_type': 'damage',
            'severity': 'high',
            'description': 'Test damage',
        })
        self.assertEqual(d.state, 'draft')
        d.action_submit()
        self.assertEqual(d.state, 'submitted')
        d.action_start_review()
        self.assertEqual(d.state, 'reviewed')
        d.action_close()
        self.assertEqual(d.state, 'closed')
        self.assertTrue(d.resolved_at)
        self.assertTrue(d.resolved_by_id)

    def test_05_defect_name_computes(self):
        d = self.Defect.create({
            'product_id': self.product.id,
            'defect_qty': 1,
            'defect_type': 'expired',
            'severity': 'critical',
            'description': 'Test',
        })
        self.assertIn('SP1-TEST', d.name)
        self.assertIn('Expired', d.name)

    # ── wms.daily.report ───────────────────────────────────────────────
    def test_06_daily_report_cron_creates_record(self):
        # Wipe any existing for yesterday
        yesterday = date.today() - timedelta(days=1)
        self.Daily.search([('report_date', '=', yesterday)]).unlink()
        report = self.Daily.cron_generate_daily_report()
        self.assertTrue(report.id)
        self.assertEqual(report.report_date, yesterday)
        self.assertTrue(report.body_html)

    def test_07_daily_report_idempotent(self):
        yesterday = date.today() - timedelta(days=1)
        self.Daily.search([('report_date', '=', yesterday)]).unlink()
        r1 = self.Daily.cron_generate_daily_report()
        r2 = self.Daily.cron_generate_daily_report()
        # Second run should return the existing, not create duplicate
        self.assertEqual(r1.id, r2.id)

    def test_08_daily_report_regenerate(self):
        rep = self.Daily.create({
            'report_date': date.today() - timedelta(days=50),
        })
        rep.action_regenerate()
        self.assertTrue(rep.body_html)

    # ── wms.qc.monthly.report ──────────────────────────────────────────
    def test_09_qc_monthly_compute_metrics(self):
        # Create a defect in a specific period
        report_date = date.today() - timedelta(days=400)
        d = self.Defect.create({
            'product_id': self.product.id,
            'defect_qty': 2,
            'defect_type': 'damage',
            'severity': 'critical',
            'description': 'Sprint1 QC test defect',
            'report_date': report_date,
        })
        period_start = report_date.replace(day=1)
        # End of that month
        if report_date.month == 12:
            period_end = date(report_date.year, 12, 31)
        else:
            next_m = date(report_date.year, report_date.month + 1, 1)
            period_end = next_m - timedelta(days=1)
        period_month = report_date.strftime('%Y-%m')

        # Delete any pre-existing report for that period
        self.QcMonth.search([('period_month', '=', period_month)]).unlink()
        r = self.QcMonth.create({
            'period_month': period_month,
            'period_start': period_start,
            'period_end': period_end,
        })
        r._compute_metrics()
        self.assertGreaterEqual(r.total_defects, 1)
        self.assertGreaterEqual(r.critical_defects, 1)
        self.assertTrue(r.top_product_name)

    def test_10_qc_monthly_cron_creates_for_last_month(self):
        result = self.QcMonth.cron_generate_monthly()
        self.assertTrue(result)
        # period_month should be YYYY-MM format
        self.assertRegex(result.period_month, r'\d{4}-\d{2}')
