"""Command Center — Inter-Company Transfer Audit (non-WMS).

Tracks stock.picking moves that cross companies (e.g. KOB → BTV → CMN
internal transfers) and groups by period for management visibility.

Uses an SQL view that detects cross-company movement by comparing
move.location_id.company_id vs move.location_dest_id.company_id on
stock.picking.
"""
from odoo import models, fields, tools


class WmsCcIntercompanyTransfer(models.Model):
    _name = 'wms.cc.intercompany.transfer'
    _description = 'CC — Inter-Company Transfer Audit'
    _auto = False
    _order = 'date_done desc, id desc'

    picking_id = fields.Many2one('stock.picking', readonly=True)
    picking_name = fields.Char(readonly=True)
    src_company_id = fields.Many2one('res.company', readonly=True,
                                     string='Source Company')
    dest_company_id = fields.Many2one('res.company', readonly=True,
                                      string='Destination Company')
    product_id = fields.Many2one('product.product', readonly=True)
    product_tmpl_id = fields.Many2one('product.template', readonly=True,
                                      string='Template')
    qty = fields.Float(digits=(14, 2), readonly=True, string='Quantity')
    state = fields.Char(readonly=True)
    date_done = fields.Datetime(readonly=True)
    scheduled_date = fields.Datetime(readonly=True)
    origin = fields.Char(readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    ROW_NUMBER() OVER (ORDER BY sm.id) AS id,
                    sp.id           AS picking_id,
                    sp.name         AS picking_name,
                    src.company_id  AS src_company_id,
                    dst.company_id  AS dest_company_id,
                    sm.product_id   AS product_id,
                    pp.product_tmpl_id AS product_tmpl_id,
                    sm.product_uom_qty AS qty,
                    sp.state        AS state,
                    sp.date_done    AS date_done,
                    sp.scheduled_date AS scheduled_date,
                    sp.origin       AS origin
                FROM stock_move sm
                JOIN stock_picking sp  ON sp.id = sm.picking_id
                JOIN stock_location src ON src.id = sm.location_id
                JOIN stock_location dst ON dst.id = sm.location_dest_id
                JOIN product_product pp ON pp.id  = sm.product_id
                WHERE src.company_id IS NOT NULL
                  AND dst.company_id IS NOT NULL
                  AND src.company_id <> dst.company_id
            )
        """ % self._table)
