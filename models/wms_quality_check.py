"""WMS Quality Check — Outgoing QC Checkpoint (P1 Critical from Audit).

Automates "ตรวจสินค้าก่อนส่งออก (Outgoing QC)" process. Replaces
"สุ่มตัวอย่างตรวจก่อนแพ็ค" manual sampling.

Workflow:
  1. When a wms.sales.order enters packing, if any line's product has
     `qc_required=True`, create wms.quality.check records (one per line).
  2. QC checker must Pass or Fail each check before pack validation.
  3. If all checks Pass → pack proceeds normally.
  4. If any check Fails → pack is blocked, an auto-linked
     wms.quality.defect record is created, supervisor notified.
"""
from odoo import models, fields, api, _
from odoo.exceptions import UserError


STATE_SEL = [
    ('pending', '⏳ Pending'),
    ('passed',  '✅ Passed'),
    ('failed',  '❌ Failed'),
    ('skipped', '⊘ Skipped'),
]


class WmsQualityCheck(models.Model):
    _name = 'wms.quality.check'
    _description = 'WMS Outgoing QC Checkpoint'
    _inherit = ['mail.thread']
    _order = 'create_date desc'
    _rec_name = 'display_name'

    # ── Source ──────────────────────────────────────────────────────────
    wms_order_id = fields.Many2one('wms.sales.order', string='WMS Order',
                                   required=True, ondelete='cascade',
                                   index=True)
    wms_line_id = fields.Many2one('wms.sales.order.line',
                                  string='Order Line',
                                  ondelete='cascade')
    product_id = fields.Many2one('product.product', required=True,
                                 string='Product')
    lot_id = fields.Many2one('stock.lot',
                             domain="[('product_id','=',product_id)]")
    expected_qty = fields.Float(string='Expected Qty', default=1,
                                digits=(12, 2))

    # ── Check data ──────────────────────────────────────────────────────
    state = fields.Selection(STATE_SEL, default='pending', required=True,
                             tracking=True)
    checked_by_id = fields.Many2one('res.users', readonly=True)
    checked_at = fields.Datetime(readonly=True)
    check_notes = fields.Text(string='QC Notes')

    # ── If failed → link to defect ──────────────────────────────────────
    defect_id = fields.Many2one('wms.quality.defect', string='Defect Record',
                                readonly=True, ondelete='set null')

    company_id = fields.Many2one('res.company',
                                 related='wms_order_id.company_id',
                                 store=True)

    display_name = fields.Char(compute='_compute_display_name',
                               store=True)

    @api.depends('wms_order_id.ref', 'product_id')
    def _compute_display_name(self):
        for rec in self:
            ref = rec.wms_order_id.ref or rec.wms_order_id.display_name or '—'
            prod = rec.product_id.default_code or (
                rec.product_id.name if rec.product_id else '—')
            rec.display_name = '[%s] %s' % (ref, prod)

    # ────────────────────────────────────────────────────────────────────
    # Actions
    # ────────────────────────────────────────────────────────────────────
    def action_pass(self):
        for rec in self:
            if rec.state not in ('pending',):
                raise UserError(_(
                    'Only pending checks can be passed. Current state: %s'
                ) % rec.state)
            rec.write({
                'state': 'passed',
                'checked_by_id': self.env.uid,
                'checked_at': fields.Datetime.now(),
            })
            rec.message_post(body=_('✅ QC passed by %s') % self.env.user.name)

    def action_fail(self):
        for rec in self:
            if rec.state not in ('pending',):
                raise UserError(_(
                    'Only pending checks can be failed. Current state: %s'
                ) % rec.state)
            defect = self.env['wms.quality.defect'].create({
                'product_id': rec.product_id.id,
                'lot_id': rec.lot_id.id if rec.lot_id else False,
                'defect_qty': rec.expected_qty,
                'defect_type': 'damage',
                'severity': 'high',
                'description': _(
                    'Auto-generated from failed outgoing QC checkpoint on %s'
                ) % rec.display_name,
                'picking_id': rec.wms_order_id.picking_id.id
                              if rec.wms_order_id.picking_id else False,
            })
            rec.write({
                'state': 'failed',
                'checked_by_id': self.env.uid,
                'checked_at': fields.Datetime.now(),
                'defect_id': defect.id,
            })
            rec.message_post(body=_(
                '❌ QC failed by %s · Defect: <b>%s</b>'
            ) % (self.env.user.name, defect.display_name))
            defect.action_submit()

    def action_skip(self):
        """Supervisor can skip (e.g. sample check only)."""
        for rec in self:
            rec.write({
                'state': 'skipped',
                'checked_by_id': self.env.uid,
                'checked_at': fields.Datetime.now(),
            })

    # ────────────────────────────────────────────────────────────────────
    # Classmethod: auto-create checks for an order (called by wms.sales.order)
    # ────────────────────────────────────────────────────────────────────
    @api.model
    def register_for_order(self, wms_order):
        """Create pending QC records for every line whose product requires
        outgoing QC (product_tmpl.qc_required_outgoing). Idempotent — only
        creates missing checks."""
        created = 0
        existing_line_ids = wms_order.quality_check_ids.mapped('wms_line_id').ids
        for line in wms_order.line_ids:
            if line.id in existing_line_ids:
                continue
            tmpl = line.product_id.product_tmpl_id
            if not getattr(tmpl, 'qc_required_outgoing', False):
                continue
            self.sudo().create({
                'wms_order_id': wms_order.id,
                'wms_line_id': line.id,
                'product_id': line.product_id.id,
                'lot_id': line.lot_id.id if line.lot_id else False,
                'expected_qty': line.expected_qty,
            })
            created += 1
        return created
