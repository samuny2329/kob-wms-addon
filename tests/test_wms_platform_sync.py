import json

from odoo.tests.common import TransactionCase, tagged
from odoo.exceptions import UserError


@tagged('post_install', '-at_install', 'kob_wms_platform')
class TestWmsPlatformSync(TransactionCase):
    """Tests for Phase A — Platform Sync framework."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Config = cls.env['wms.api.config']
        cls.Order = cls.env['wms.platform.order']

    def _get_or_create_config(self, platform, **overrides):
        cfg = self.Config.search([
            ('platform', '=', platform),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        if cfg:
            cfg.write(overrides)
            return cfg
        return self.Config.create({'platform': platform, **overrides})

    # ── wms.api.config ───────────────────────────────────────────────────
    def test_01_sync_now_disabled_raises(self):
        cfg = self._get_or_create_config('shopee', enabled=False)
        with self.assertRaises(UserError):
            cfg.action_sync_now()

    def test_02_sync_now_stub_raises_not_implemented(self):
        """Shopee/Lazada/TikTok stubs should raise UserError wrapping
        NotImplementedError (until real adapter is wired).

        Note: the transaction is rolled back on UserError so last_sync_status
        won't persist — we only assert the raise itself.
        """
        cfg = self._get_or_create_config('shopee', enabled=True)
        with self.assertRaises(UserError) as ctx:
            cfg.action_sync_now()
        self.assertIn('not implemented', str(ctx.exception).lower())

    def test_03_sync_odoo_is_noop(self):
        cfg = self._get_or_create_config('odoo', enabled=True)
        cfg.action_sync_now()
        self.assertEqual(cfg.last_sync_status, 'ok')
        self.assertEqual(cfg.total_synced, 0)

    def test_04_next_sync_computed_only_when_auto_sync_on(self):
        cfg = self._get_or_create_config('lazada',
                                         enabled=True,
                                         auto_sync=False)
        cfg.last_sync_at = '2026-04-23 10:00:00'
        self.assertFalse(cfg.next_sync_at)
        cfg.auto_sync = True
        cfg.sync_interval_minutes = 15
        cfg.invalidate_recordset()
        self.assertTrue(cfg.next_sync_at)

    # ── wms.platform.order ───────────────────────────────────────────────
    def test_05_register_payload_creates_record(self):
        cfg = self._get_or_create_config('tiktok', enabled=True)
        payload = {
            'platform_order_no': 'TIKTOK-TEST-001',
            'platform_status': 'UNPAID',
            'buyer_name': 'Test Buyer',
            'total_amount': 1250.00,
            'currency_code': 'THB',
            'raw': {'xxx': 'yyy'},
        }
        order = self.Order.register_from_payload(cfg, payload)
        self.assertTrue(order.id)
        self.assertEqual(order.platform_order_no, 'TIKTOK-TEST-001')
        self.assertEqual(order.state, 'received')
        self.assertEqual(order.total_amount, 1250.00)
        # payload_json is stored as string
        parsed = json.loads(order.payload_json)
        self.assertEqual(parsed, {'xxx': 'yyy'})

    def test_06_register_payload_idempotent(self):
        """Calling register_from_payload twice with the same order_no
        should update existing record, not duplicate."""
        cfg = self._get_or_create_config('tiktok', enabled=True)
        p1 = {'platform_order_no': 'SAMEID', 'platform_status': 'UNPAID'}
        p2 = {'platform_order_no': 'SAMEID', 'platform_status': 'PAID'}
        o1 = self.Order.register_from_payload(cfg, p1)
        o2 = self.Order.register_from_payload(cfg, p2)
        self.assertEqual(o1.id, o2.id)
        self.assertEqual(o2.platform_status, 'PAID')

    def test_07_map_to_sale_order(self):
        cfg = self._get_or_create_config('lazada', enabled=True)
        order = self.Order.register_from_payload(cfg, {
            'platform_order_no': 'LAZ-MAP-001',
            'buyer_name': 'Map Test Buyer',
            'total_amount': 500,
        })
        order.action_map_to_sale_order()
        self.assertEqual(order.state, 'mapped')
        self.assertTrue(order.sale_order_id)
        self.assertEqual(order.sale_order_id.partner_id.name, 'Map Test Buyer')

    def test_08_map_without_buyer_sets_error(self):
        cfg = self._get_or_create_config('lazada', enabled=True)
        order = self.Order.register_from_payload(cfg, {
            'platform_order_no': 'LAZ-NOBUYER-001',
            'total_amount': 100,
        })
        order.action_map_to_sale_order()
        self.assertEqual(order.state, 'error')
        self.assertIn('buyer_name', order.error_message or '')

    def test_09_unique_per_platform_config(self):
        """Same order_no on DIFFERENT platforms should both be allowed."""
        shopee = self._get_or_create_config('shopee', enabled=True)
        lazada = self._get_or_create_config('lazada', enabled=True)
        p = {'platform_order_no': 'DUAL-PLATFORM-001'}
        o1 = self.Order.register_from_payload(shopee, p)
        o2 = self.Order.register_from_payload(lazada, p)
        self.assertNotEqual(o1.id, o2.id)

    # ── cron ────────────────────────────────────────────────────────────
    def test_10_cron_auto_sync_skips_disabled_and_errors_dont_crash(self):
        """Cron runs across all enabled+auto_sync configs; stubs raise
        NotImplementedError but cron should not crash."""
        # Ensure at least one enabled+auto config (shopee stub)
        cfg = self._get_or_create_config(
            'shopee', enabled=True, auto_sync=True,
            sync_interval_minutes=5, last_sync_at=False)
        results = self.Config.cron_auto_sync()
        # Each result is (platform, status_str)
        self.assertIsInstance(results, list)
        platforms = [r[0] for r in results]
        self.assertIn('shopee', platforms)
