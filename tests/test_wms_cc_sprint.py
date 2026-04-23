from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'kob_wms_cc')
class TestWmsCcSprint(TransactionCase):
    """Command Center Sprint CC-3 — Cross-Company Audit views."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Multi = cls.env['wms.cc.multiwh.stock']
        cls.Inter = cls.env['wms.cc.intercompany.transfer']

    def test_01_multiwh_view_queries_without_error(self):
        """SQL view must be queryable; empty result is acceptable."""
        rows = self.Multi.search([], limit=5)
        # Should not raise. Each row has a product_id + company_id.
        for r in rows:
            self.assertTrue(r.product_id or r.company_id)

    def test_02_intercompany_view_queries_without_error(self):
        rows = self.Inter.search([], limit=5)
        for r in rows:
            # src and dest must be different (that's the filter criteria)
            if r.src_company_id and r.dest_company_id:
                self.assertNotEqual(r.src_company_id, r.dest_company_id)

    def test_03_multiwh_single_company_flag_computed(self):
        """single_company_flag column must return boolean values."""
        rows = self.Multi.search([], limit=10)
        for r in rows:
            # Must be a boolean value (True/False), not None
            self.assertIn(r.single_company_flag, (True, False))

    def test_04_multiwh_sum_by_product_is_consistent(self):
        """Sum of total_qty for a product + others_qty should match total
        across all companies for that product."""
        rows = self.Multi.search([], limit=100)
        if not rows:
            return
        # Group by product: sum(total_qty) == row.total_qty + row.others_qty
        by_product = {}
        for r in rows:
            key = r.product_id.id
            by_product.setdefault(key, []).append(r)
        for pid, group in by_product.items():
            if len(group) < 2:
                continue
            # Each row's total + others should equal the grand total
            grand_total = sum(row.total_qty for row in group)
            # Allow float tolerance
            for row in group:
                self.assertAlmostEqual(
                    row.total_qty + row.others_qty, grand_total, places=2,
                    msg='Product %s row %s: total+others != grand_total' % (
                        pid, row.id))

    def test_05_intercompany_only_cross_company(self):
        """View must only contain rows where src != dest company."""
        rows = self.Inter.search([], limit=50)
        for r in rows:
            if r.src_company_id and r.dest_company_id:
                self.assertNotEqual(
                    r.src_company_id.id, r.dest_company_id.id,
                    msg='Row %s has same src/dest company' % r.id)
