"""Command Center — Reorder Point Monitor (Supply Chain audit).

SQL view over stock.warehouse.orderpoint comparing current on-hand
to min/max and flagging below-min SKUs. Replaces manual spreadsheet
checks. Daily cron posts alerts for critical shortages.
"""
from odoo import models, fields, tools, api, _


class WmsCcReorderMonitor(models.Model):
    _name = 'wms.cc.reorder.monitor'
    _description = 'CC — Reorder Point Monitor'
    _auto = False
    _order = 'shortage_qty desc, product_id'

    orderpoint_id = fields.Many2one('stock.warehouse.orderpoint', readonly=True)
    product_id = fields.Many2one('product.product', readonly=True)
    product_code = fields.Char(readonly=True)
    warehouse_id = fields.Many2one('stock.warehouse', readonly=True)
    location_id = fields.Many2one('stock.location', readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    product_min_qty = fields.Float(digits=(14, 2), readonly=True,
                                   string='Min Qty')
    product_max_qty = fields.Float(digits=(14, 2), readonly=True,
                                   string='Max Qty')
    current_qty = fields.Float(digits=(14, 2), readonly=True,
                               string='On Hand')
    shortage_qty = fields.Float(digits=(14, 2), readonly=True,
                                string='Shortage (min - onhand)')
    need_reorder = fields.Boolean(readonly=True, string='Needs Reorder')
    severity = fields.Selection([
        ('ok',        '✅ OK'),
        ('watch',     '🟡 Watch (80% of min)'),
        ('shortage',  '🟠 Below Min'),
        ('critical',  '🔴 Zero / Very Low'),
    ], readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                WITH on_hand AS (
                    SELECT
                        q.product_id,
                        q.location_id,
                        q.company_id,
                        SUM(q.quantity) AS qty
                    FROM stock_quant q
                    JOIN stock_location sl ON sl.id = q.location_id
                    WHERE sl.usage = 'internal'
                    GROUP BY q.product_id, q.location_id, q.company_id
                )
                SELECT
                    op.id                           AS id,
                    op.id                           AS orderpoint_id,
                    op.product_id                   AS product_id,
                    pt.default_code                 AS product_code,
                    op.warehouse_id                 AS warehouse_id,
                    op.location_id                  AS location_id,
                    op.company_id                   AS company_id,
                    op.product_min_qty              AS product_min_qty,
                    op.product_max_qty              AS product_max_qty,
                    COALESCE(oh.qty, 0)             AS current_qty,
                    GREATEST(op.product_min_qty - COALESCE(oh.qty, 0), 0)
                        AS shortage_qty,
                    (COALESCE(oh.qty, 0) < op.product_min_qty) AS need_reorder,
                    CASE
                        WHEN COALESCE(oh.qty, 0) <= 0 THEN 'critical'
                        WHEN COALESCE(oh.qty, 0) < op.product_min_qty * 0.5 THEN 'critical'
                        WHEN COALESCE(oh.qty, 0) < op.product_min_qty THEN 'shortage'
                        WHEN COALESCE(oh.qty, 0) < op.product_min_qty * 1.2 THEN 'watch'
                        ELSE 'ok'
                    END AS severity
                FROM stock_warehouse_orderpoint op
                JOIN product_product pp ON pp.id = op.product_id
                JOIN product_template pt ON pt.id = pp.product_tmpl_id
                LEFT JOIN on_hand oh
                       ON oh.product_id = op.product_id
                      AND oh.location_id = op.location_id
                WHERE op.active = true
            )
        """ % self._table)

    # Cron: post alert for critical shortages
    @api.model
    def cron_check_critical(self):
        """Daily scan — post chatter message listing any product at
        'critical' severity on its warehouse."""
        criticals = self.sudo().search([('severity', '=', 'critical')])
        if not criticals:
            return {'critical_count': 0}
        # Group by warehouse
        by_wh = {}
        for rec in criticals:
            by_wh.setdefault(rec.warehouse_id, []).append(rec)
        # Post to supervisors
        group = self.env.ref('kob_wms.group_wms_supervisor',
                             raise_if_not_found=False)
        recipient_ids = []
        if group:
            for u in group.users:
                if u.partner_id:
                    recipient_ids.append(u.partner_id.id)
        # Post as system message on the main company
        company = self.env.company
        body_lines = [_('🚨 <b>Reorder Alert — Critical Shortage</b>')]
        for wh, recs in by_wh.items():
            body_lines.append('<br/><b>%s</b> (%d SKUs)' % (
                wh.display_name if wh else '—', len(recs)))
            for r in recs[:10]:
                body_lines.append('<br/> • %s — on hand %.0f / min %.0f' % (
                    r.product_id.display_name,
                    r.current_qty, r.product_min_qty))
        body = '\n'.join(body_lines)
        if recipient_ids:
            # Post as mail thread message via sudo mail.message
            self.env['mail.mail'].sudo().create({
                'subject': _('Reorder Alert — %d critical SKUs') % len(criticals),
                'body_html': body,
                'recipient_ids': [(6, 0, recipient_ids)],
                'auto_delete': True,
            }).send()
        return {'critical_count': len(criticals)}
