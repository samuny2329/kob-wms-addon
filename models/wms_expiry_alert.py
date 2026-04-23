"""WMS Expiry Alert — automate Track Expiry Date (P1 Critical from Audit).

Replaces the "บันทึกใน Excel / ไม่มี alert" manual process.

Uses `stock.lot.expiration_date` (Odoo native via product_expiry dep) and
the computed `expiry_days` field already on stock.lot (see
wms_inventory_extra.StockLotExpiry).

Cron runs daily 06:00 and:
  1. Finds lots with expiry_days <= threshold (default 180 days)
  2. Posts chatter on the product.template
  3. Schedules activity (reminder) for the QC Manager
  4. Creates one wms.expiry.alert record per (lot, severity) — idempotent per day
"""
from odoo import models, fields, api, _


SEVERITY_SEL = [
    ('expired',  '🔴 Expired'),
    ('urgent',   '🟠 ≤ 30 days'),
    ('warning',  '🟡 ≤ 90 days'),
    ('watch',    '🟢 ≤ 180 days'),
]


class WmsExpiryAlert(models.Model):
    _name = 'wms.expiry.alert'
    _description = 'Stock Lot Expiry Alert'
    _order = 'expiry_days, id'
    _rec_name = 'lot_id'

    alert_date = fields.Date(string='Alert Date',
                             default=fields.Date.context_today,
                             required=True, index=True)
    lot_id = fields.Many2one('stock.lot', required=True, ondelete='cascade',
                             string='Lot / Serial')
    product_id = fields.Many2one(related='lot_id.product_id',
                                 store=True, readonly=True)
    expiration_date = fields.Datetime(related='lot_id.expiration_date',
                                      store=True)
    expiry_days = fields.Integer(related='lot_id.expiry_days',
                                 store=True, readonly=True)
    product_qty = fields.Float(compute='_compute_product_qty', store=False)
    severity = fields.Selection(SEVERITY_SEL, compute='_compute_severity',
                                store=True, index=True)
    acknowledged = fields.Boolean(default=False,
                                  help='QC acknowledged the alert')

    _sql_constraints = [
        ('lot_date_unique',
         'unique(lot_id, alert_date)',
         'One alert per lot per day.'),
    ]

    @api.depends('expiry_days')
    def _compute_severity(self):
        for rec in self:
            d = rec.expiry_days or 0
            if d < 0:
                rec.severity = 'expired'
            elif d <= 30:
                rec.severity = 'urgent'
            elif d <= 90:
                rec.severity = 'warning'
            else:
                rec.severity = 'watch'

    def _compute_product_qty(self):
        Quant = self.env['stock.quant'].sudo()
        for rec in self:
            quants = Quant.search([
                ('lot_id', '=', rec.lot_id.id),
                ('location_id.usage', '=', 'internal'),
            ])
            rec.product_qty = sum(quants.mapped('quantity'))

    # ────────────────────────────────────────────────────────────────────
    # Cron entry
    # ────────────────────────────────────────────────────────────────────
    @api.model
    def cron_scan_expiry(self, threshold_days=180):
        """Scan stock.lot and create alerts for expiry_days <= threshold.

        Idempotent per day: the unique(lot_id, alert_date) constraint means
        running the cron twice in one day will not create duplicates.
        """
        Lot = self.env['stock.lot'].sudo()
        today = fields.Date.context_today(self)
        lots = Lot.search([
            ('expiration_date', '!=', False),
            ('expiry_days', '<=', threshold_days),
        ])
        created = 0
        for lot in lots:
            # Skip lots that have zero internal stock
            qty = sum(lot.quant_ids.filtered(
                lambda q: q.location_id.usage == 'internal'
            ).mapped('quantity'))
            if qty <= 0:
                continue
            existing = self.sudo().search([
                ('lot_id', '=', lot.id),
                ('alert_date', '=', today),
            ], limit=1)
            if existing:
                continue
            alert = self.sudo().create({
                'lot_id': lot.id,
                'alert_date': today,
            })
            created += 1
            # Post chatter on the product template
            if lot.product_id and lot.product_id.product_tmpl_id:
                lot.product_id.product_tmpl_id.message_post(body=_(
                    '⏰ Expiry alert: Lot <b>%s</b> expires in '
                    '<b>%d days</b> (%s) · On hand: %.2f'
                ) % (lot.name, lot.expiry_days or 0,
                     lot.expiration_date, qty))
        return {'created': created, 'scanned': len(lots)}
