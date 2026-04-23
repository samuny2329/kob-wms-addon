"""Command Center — Supplier Lead Time Audit (Supply Chain).

SQL view joining purchase.order + stock.picking (incoming) to compute
avg lead time per supplier: (first receipt date_done - po date_order).

Supports KPI: Supplier Lead Time (K-OKR3) per Notion Org Chart
(Keaw, Aof, Mind, Benz). Replaces "ไม่มีระบบ / Excel" audit.
"""
from odoo import models, fields, tools


class WmsCcSupplierLeadtime(models.Model):
    _name = 'wms.cc.supplier.leadtime'
    _description = 'CC — Supplier Lead Time'
    _auto = False
    _order = 'avg_leadtime_days desc, partner_id'

    partner_id = fields.Many2one('res.partner', readonly=True,
                                 string='Supplier')
    partner_name = fields.Char(readonly=True)
    po_count = fields.Integer(readonly=True, string='# POs (90d)')
    avg_leadtime_days = fields.Float(digits=(10, 2), readonly=True,
                                     string='Avg Lead Time (days)')
    min_leadtime_days = fields.Float(digits=(10, 2), readonly=True,
                                     string='Min')
    max_leadtime_days = fields.Float(digits=(10, 2), readonly=True,
                                     string='Max')
    last_po_date = fields.Datetime(readonly=True, string='Last PO')
    on_time_count = fields.Integer(readonly=True, string='# On-Time')
    on_time_pct = fields.Float(digits=(5, 2), readonly=True,
                               string='On-Time %')

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                WITH po_receipts AS (
                    SELECT
                        po.id                    AS po_id,
                        po.partner_id            AS partner_id,
                        po.date_order            AS date_order,
                        po.date_planned          AS date_planned,
                        MIN(sp.date_done)        AS first_receipt_date
                    FROM purchase_order po
                    JOIN purchase_order_line pol ON pol.order_id = po.id
                    JOIN stock_move sm ON sm.purchase_line_id = pol.id
                    JOIN stock_picking sp ON sp.id = sm.picking_id
                    WHERE po.state IN ('purchase', 'done')
                      AND sp.state = 'done'
                      AND po.date_order >= NOW() - INTERVAL '90 days'
                    GROUP BY po.id, po.partner_id, po.date_order, po.date_planned
                ),
                stats AS (
                    SELECT
                        partner_id,
                        COUNT(*) AS po_count,
                        AVG(EXTRACT(EPOCH FROM (first_receipt_date - date_order))
                            / 86400.0) AS avg_days,
                        MIN(EXTRACT(EPOCH FROM (first_receipt_date - date_order))
                            / 86400.0) AS min_days,
                        MAX(EXTRACT(EPOCH FROM (first_receipt_date - date_order))
                            / 86400.0) AS max_days,
                        MAX(date_order) AS last_po_date,
                        SUM(CASE
                            WHEN first_receipt_date <= date_planned THEN 1
                            ELSE 0
                        END) AS on_time_count
                    FROM po_receipts
                    WHERE first_receipt_date IS NOT NULL
                    GROUP BY partner_id
                )
                SELECT
                    ROW_NUMBER() OVER (ORDER BY avg_days DESC NULLS LAST) AS id,
                    s.partner_id,
                    p.name        AS partner_name,
                    s.po_count,
                    ROUND(s.avg_days::numeric, 2)  AS avg_leadtime_days,
                    ROUND(s.min_days::numeric, 2)  AS min_leadtime_days,
                    ROUND(s.max_days::numeric, 2)  AS max_leadtime_days,
                    s.last_po_date,
                    s.on_time_count,
                    CASE WHEN s.po_count > 0 THEN
                        ROUND((s.on_time_count::numeric / s.po_count * 100), 2)
                    ELSE 0 END AS on_time_pct
                FROM stats s
                JOIN res_partner p ON p.id = s.partner_id
            )
        """ % self._table)
