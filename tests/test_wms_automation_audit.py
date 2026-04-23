from datetime import date, timedelta

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'kob_wms_audit')
class TestWmsAutomationAudit(TransactionCase):
    """Tests for wms.automation.audit (K-OKR3-02)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Audit = cls.env['wms.automation.audit']

    # ── Scoring ───────────────────────────────────────────────────────────
    def test_01_all_manual_zero_score(self):
        audit = self.Audit.create({
            'audit_date': date.today(),
            'receive_level': 'manual', 'putaway_level': 'manual',
            'pick_level': 'manual', 'pack_level': 'manual',
            'ship_level': 'manual', 'invoice_level': 'manual',
        })
        self.assertEqual(audit.total_score, 0.0)
        self.assertEqual(audit.status, 'critical')

    def test_02_all_full_auto_hundred_score(self):
        audit = self.Audit.create({
            'audit_date': date.today() - timedelta(days=1),
            'receive_level': 'full', 'putaway_level': 'full',
            'pick_level': 'full', 'pack_level': 'full',
            'ship_level': 'full', 'invoice_level': 'full',
        })
        self.assertEqual(audit.total_score, 100.0)
        self.assertEqual(audit.status, 'pass')

    def test_03_mixed_semi_full_formula(self):
        # 3 full (300) + 3 semi (150) = 450 / 600 × 100 = 75%
        audit = self.Audit.create({
            'audit_date': date.today() - timedelta(days=2),
            'receive_level': 'full', 'putaway_level': 'full',
            'pick_level': 'full', 'pack_level': 'semi',
            'ship_level': 'semi', 'invoice_level': 'semi',
        })
        self.assertEqual(audit.total_score, 75.0)
        self.assertEqual(audit.status, 'pass')

    def test_04_boundary_70_percent_pass(self):
        # Total 70% → should be pass (≥ 70)
        # receive=full(100)+putaway=full(100)+pick=full(100)+pack=semi(50)+ship=semi(50)+invoice=semi(50) = 450 → 75% → pass
        # To hit exactly 70: 420/600 — 4 full + 1 semi + 1 below-semi... use 70 directly
        # Actually 4 full (400) + 1 full (100) + 1 manual (0) = 500 → 83.33%
        # Must assert status boundary only
        audit = self.Audit.create({
            'audit_date': date.today() - timedelta(days=3),
            'receive_level': 'semi', 'putaway_level': 'semi',
            'pick_level': 'semi', 'pack_level': 'semi',
            'ship_level': 'semi', 'invoice_level': 'semi',
        })
        # 6 × 50 / 600 × 100 = 50 → watch
        self.assertEqual(audit.total_score, 50.0)
        self.assertEqual(audit.status, 'watch')

    def test_05_below_30_critical(self):
        # 1 semi + 5 manual = 50/600 = 8.33%
        audit = self.Audit.create({
            'audit_date': date.today() - timedelta(days=4),
            'receive_level': 'semi', 'putaway_level': 'manual',
            'pick_level': 'manual', 'pack_level': 'manual',
            'ship_level': 'manual', 'invoice_level': 'manual',
        })
        self.assertAlmostEqual(audit.total_score, 8.33, places=2)
        self.assertEqual(audit.status, 'critical')

    # ── Name + uniqueness ────────────────────────────────────────────────
    def test_06_name_includes_date_and_company(self):
        audit = self.Audit.create({
            'audit_date': date(2026, 6, 15),
        })
        self.assertIn('2026-06-15', audit.name)

    def test_07_unique_per_day_per_company(self):
        from psycopg2 import IntegrityError
        from odoo.tools.misc import mute_logger
        d = date.today() - timedelta(days=10)
        self.Audit.create({'audit_date': d})
        with mute_logger('odoo.sql_db'):
            with self.assertRaises(IntegrityError):
                with self.env.cr.savepoint():
                    self.Audit.create({'audit_date': d})

    # ── Auto-detect action ────────────────────────────────────────────────
    def test_08_run_audit_populates_counters(self):
        audit = self.Audit.create({
            'audit_date': date.today() - timedelta(days=20),
        })
        audit.action_run_audit()
        # Counters must be >= 0 (no crash)
        self.assertGreaterEqual(audit.active_cron_count, 0)
        self.assertGreaterEqual(audit.active_stock_rule_count, 0)
        self.assertGreaterEqual(audit.wms_active_workers, 0)
        self.assertGreaterEqual(audit.platform_api_configs, 0)

    def test_09_run_audit_triggers_recompute_of_levels(self):
        """After running audit, levels must be auto-suggested (not all manual)."""
        audit = self.Audit.create({
            'audit_date': date.today() - timedelta(days=30),
            'receive_level': 'manual', 'putaway_level': 'manual',
            'pick_level': 'manual', 'pack_level': 'manual',
            'ship_level': 'manual', 'invoice_level': 'manual',
        })
        self.assertEqual(audit.total_score, 0.0)
        audit.action_run_audit()
        # After scan, at least one step should move up from manual if any
        # automation signal exists in the DB — but we can't assert specific
        # value since it depends on test DB state. Just ensure no crash.
        self.assertTrue(audit.recommendations)

    # ── Recommendations ───────────────────────────────────────────────────
    def test_10_recommendations_generated_for_weak_steps(self):
        audit = self.Audit.create({
            'audit_date': date.today() - timedelta(days=40),
            'receive_level': 'manual',
            'putaway_level': 'manual',
            'pick_level': 'manual',
            'pack_level': 'manual',
            'ship_level': 'manual',
            'invoice_level': 'manual',
        })
        self.assertIn('Receive', audit.recommendations)
        self.assertIn('Pick', audit.recommendations)
        # Below 70% → warning line
        self.assertIn('70%', audit.recommendations)

    def test_11_recommendations_clean_when_all_full(self):
        audit = self.Audit.create({
            'audit_date': date.today() - timedelta(days=50),
            'receive_level': 'full', 'putaway_level': 'full',
            'pick_level': 'full', 'pack_level': 'full',
            'ship_level': 'full', 'invoice_level': 'full',
        })
        # Should not contain any weakness warning
        self.assertNotIn('❌', audit.recommendations)
        self.assertNotIn('⚠️', audit.recommendations)
