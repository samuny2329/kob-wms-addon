"""WMS Quality Defect / Damage Log — automate Defect/Damage tracking
(P2 High from Audit). Replaces "จดในสมุด / Excel ทีหลัง" manual process.

Workflow:
  draft → submitted (QC worker) → reviewed (QC Manager) → closed

Each defect links to:
  - stock.picking (receipt/delivery where defect found)
  - product_id + lot_id + qty
  - photo evidence (attachments via chatter)
  - resolution action (scrap / return / rework / accepted)
"""
from odoo import models, fields, api, _


DEFECT_TYPE_SEL = [
    ('damage',    'Physical Damage'),
    ('expired',   'Expired / Near-Expiry'),
    ('contaminated', 'Contamination'),
    ('wrong_item', 'Wrong Item / Mislabel'),
    ('short',     'Short Qty'),
    ('other',     'Other'),
]

SEVERITY_SEL = [
    ('low', '🟢 Low'),
    ('medium', '🟡 Medium'),
    ('high', '🟠 High'),
    ('critical', '🔴 Critical'),
]

RESOLUTION_SEL = [
    ('pending',  'Pending Decision'),
    ('scrap',    'Scrap'),
    ('return',   'Return to Supplier'),
    ('rework',   'Rework'),
    ('accepted', 'Accepted (with note)'),
]


class WmsQualityDefect(models.Model):
    _name = 'wms.quality.defect'
    _description = 'WMS Quality Defect / Damage Log'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'report_date desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    report_date = fields.Datetime(string='Reported At',
                                  default=fields.Datetime.now,
                                  required=True, tracking=True)
    reporter_id = fields.Many2one('res.users', string='Reporter',
                                  default=lambda self: self.env.user,
                                  tracking=True)
    kob_reporter_id = fields.Many2one('kob.wms.user', string='WMS Employee')

    # ── Link to operation ────────────────────────────────────────────────
    picking_id = fields.Many2one('stock.picking', string='Picking')
    picking_type = fields.Selection(related='picking_id.picking_type_code',
                                    store=True)
    partner_id = fields.Many2one(related='picking_id.partner_id',
                                 store=True, string='Partner')

    # ── Defect data ──────────────────────────────────────────────────────
    product_id = fields.Many2one('product.product', required=True,
                                 tracking=True)
    lot_id = fields.Many2one('stock.lot', domain="[('product_id','=',product_id)]")
    defect_qty = fields.Float(string='Defect Qty', required=True, default=1)
    uom_id = fields.Many2one(related='product_id.uom_id', store=True,
                             string='UoM')

    defect_type = fields.Selection(DEFECT_TYPE_SEL, required=True,
                                   default='damage', tracking=True)
    severity = fields.Selection(SEVERITY_SEL, required=True,
                                default='medium', tracking=True)
    description = fields.Text(string='Description', required=True)

    # ── Workflow ─────────────────────────────────────────────────────────
    state = fields.Selection([
        ('draft',     'Draft'),
        ('submitted', 'Submitted'),
        ('reviewed',  'Under Review'),
        ('closed',    'Closed'),
    ], default='draft', required=True, tracking=True)
    resolution = fields.Selection(RESOLUTION_SEL, default='pending',
                                  tracking=True)
    resolution_note = fields.Text()
    resolved_by_id = fields.Many2one('res.users', string='Resolved By',
                                     readonly=True)
    resolved_at = fields.Datetime(readonly=True)

    company_id = fields.Many2one('res.company',
                                 default=lambda self: self.env.company)

    @api.depends('product_id', 'defect_type', 'report_date')
    def _compute_name(self):
        for rec in self:
            prod = rec.product_id.default_code or (
                rec.product_id.name if rec.product_id else '—')
            dt = rec.defect_type and dict(
                rec._fields['defect_type'].selection).get(rec.defect_type)
            date_s = (rec.report_date and rec.report_date.strftime('%Y-%m-%d')
                      or '—')
            rec.name = '[%s] %s — %s' % (date_s, prod, dt or '')

    # ── State transitions ──────────────────────────────────────────────
    def action_submit(self):
        self.write({'state': 'submitted'})
        # Schedule activity for QC Manager
        qc_group = self.env.ref('kob_wms.group_wms_manager',
                                raise_if_not_found=False)
        if qc_group:
            for user in qc_group.users:
                for rec in self:
                    rec.activity_schedule(
                        'mail.mail_activity_data_todo',
                        user_id=user.id,
                        summary=_('Quality Defect Review'),
                        note=_('%s reported by %s — please review') % (
                            rec.display_name, rec.reporter_id.name),
                    )
                break  # one activity for first manager is enough

    def action_start_review(self):
        self.write({'state': 'reviewed'})

    def action_close(self):
        self.write({
            'state': 'closed',
            'resolved_by_id': self.env.user.id,
            'resolved_at': fields.Datetime.now(),
        })
        # Log resolution on picking chatter for traceability
        for rec in self:
            if rec.picking_id:
                rec.picking_id.message_post(body=_(
                    '🔴 Quality defect closed: <b>%s</b> · Resolution: %s'
                ) % (rec.display_name,
                     dict(rec._fields['resolution'].selection).get(
                         rec.resolution, '—')))

    def action_reset_draft(self):
        self.write({'state': 'draft'})
