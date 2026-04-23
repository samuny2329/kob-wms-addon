"""Command Center — Multi-Warehouse Stock Comparison (non-WMS audit).

Aggregates internal stock.quant across companies/warehouses for the
same product so Ops Director / Accounting can see:
  - Total qty per product across all companies
  - How it's distributed across warehouses
  - Reserved vs available
  - Flags SKUs that live in only one company (candidates for transfer)

Uses an SQL view for performance. Refreshes on the fly.
"""
from odoo import models, fields, tools


class WmsCcMultiWhStock(models.Model):
    _name = 'wms.cc.multiwh.stock'
    _description = 'CC — Multi-Warehouse Stock Comparison'
    _auto = False
    _order = 'product_id, company_id'

    product_id = fields.Many2one('product.product', readonly=True)
    product_code = fields.Char(readonly=True)
    product_name = fields.Char(related='product_id.display_name',
                               string='Product', readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    warehouse_id = fields.Many2one('stock.warehouse', readonly=True)

    total_qty = fields.Float(digits=(14, 2), readonly=True,
                             string='Total On Hand')
    reserved_qty = fields.Float(digits=(14, 2), readonly=True,
                                string='Reserved')
    available_qty = fields.Float(digits=(14, 2), readonly=True,
                                 string='Available')
    quant_count = fields.Integer(readonly=True, string='# Quants')
    location_count = fields.Integer(readonly=True, string='# Locations')

    # Cross-company "others_qty" = sum of same product in other companies
    others_qty = fields.Float(digits=(14, 2), readonly=True,
                              string='Qty in Other Companies',
                              help='Sum of on-hand for the same product '
                                   'in OTHER companies')
    single_company_flag = fields.Boolean(
        readonly=True, string='Only in 1 Company',
        help='True when this SKU exists only in this company — '
             'may indicate a missing inter-company transfer')

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                WITH base AS (
                    SELECT
                        q.product_id,
                        q.company_id,
                        sw.id AS warehouse_id,
                        SUM(q.quantity)          AS total_qty,
                        SUM(q.reserved_quantity) AS reserved_qty,
                        SUM(q.quantity - q.reserved_quantity) AS available_qty,
                        COUNT(q.id)              AS quant_count,
                        COUNT(DISTINCT q.location_id) AS location_count
                    FROM stock_quant q
                    JOIN stock_location sl ON sl.id = q.location_id
                    LEFT JOIN stock_warehouse sw
                           ON sw.lot_stock_id = sl.id
                           OR sw.view_location_id = sl.location_id
                    WHERE sl.usage = 'internal'
                      AND q.quantity <> 0
                    GROUP BY q.product_id, q.company_id, sw.id
                ),
                company_count AS (
                    SELECT product_id, COUNT(DISTINCT company_id) AS n_companies
                    FROM base
                    GROUP BY product_id
                ),
                other_qty AS (
                    SELECT
                        b.product_id,
                        b.company_id,
                        COALESCE((
                            SELECT SUM(b2.total_qty)
                            FROM base b2
                            WHERE b2.product_id = b.product_id
                              AND b2.company_id <> b.company_id
                        ), 0) AS others_qty
                    FROM base b
                )
                SELECT
                    ROW_NUMBER() OVER (
                      ORDER BY b.product_id, b.company_id, COALESCE(b.warehouse_id, 0)
                    )                 AS id,
                    b.product_id,
                    pt.default_code   AS product_code,
                    pt.name::text     AS product_name,
                    b.company_id,
                    b.warehouse_id,
                    b.total_qty,
                    b.reserved_qty,
                    b.available_qty,
                    b.quant_count,
                    b.location_count,
                    oq.others_qty,
                    (cc.n_companies = 1) AS single_company_flag
                FROM base b
                JOIN other_qty oq
                  ON oq.product_id = b.product_id
                 AND oq.company_id = b.company_id
                JOIN company_count cc
                  ON cc.product_id = b.product_id
                JOIN product_product pp ON pp.id = b.product_id
                JOIN product_template pt ON pt.id = pp.product_tmpl_id
            )""" % self._table)
