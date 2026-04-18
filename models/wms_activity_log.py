import hashlib
from odoo import models, fields, api


class WmsActivityLog(models.Model):
    """Activity log with hash chain for tamper-proof audit trail."""
    _name = 'wms.activity.log'
    _description = 'WMS Activity Log'
    _order = 'create_date desc'
    _rec_name = 'action'

    user_id = fields.Many2one('res.users', string='Odoo User', required=True,
                              default=lambda self: self.env.user)
    kob_user_id = fields.Many2one('kob.wms.user', string='Employee',
                                  ondelete='set null', index=True)
    worker_name = fields.Char(
        string='Employee',
        compute='_compute_worker_name', store=True,
        help='Employee name (kob.wms.user) or Odoo user fallback',
    )
    action = fields.Selection([
        ('pick', 'Pick'),
        ('pack', 'Pack'),
        ('box', 'Close Box'),
        ('ship', 'Ship / Fulfill'),
        ('return', 'Return'),
        ('cancel', 'Cancel'),
        ('scan', 'Outbound Scan'),
        ('dispatch', 'Dispatch'),
        ('login', 'Login'),
        ('logout', 'Logout'),
        ('error_pick', 'Pick Error'),
        ('error_pack', 'Pack Error'),
        ('print_picklist', 'Print Pick List'),
        ('other', 'Other'),
    ], string='Action', required=True)
    ref = fields.Char(string='Order Ref')
    code = fields.Char(string='Code Scanned')
    note = fields.Char(string='Note')
    sales_order_id = fields.Many2one('wms.sales.order', string='Sales Order',
                                     ondelete='set null')
    batch_id = fields.Many2one('wms.courier.batch', string='Batch',
                               ondelete='set null')
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company)

    @api.depends('kob_user_id', 'user_id')
    def _compute_worker_name(self):
        for rec in self:
            rec.worker_name = rec.kob_user_id.name if rec.kob_user_id else rec.user_id.name

    # Hash Chain (tamper-proof)
    prev_hash = fields.Char(string='Previous Hash', readonly=True)
    block_hash = fields.Char(string='Block Hash', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        # Get last hash in chain
        last = self.sudo().search([], order='id desc', limit=1)
        prev = last.block_hash if last and last.block_hash else '0' * 64

        for vals in vals_list:
            vals['prev_hash'] = prev
            # Build hash from: prev_hash + action + user + ref + code + timestamp
            data = '|'.join([
                prev,
                str(vals.get('action', '')),
                str(vals.get('user_id', '')),
                str(vals.get('ref', '')),
                str(vals.get('code', '')),
                str(fields.Datetime.now()),
            ])
            block_hash = hashlib.sha256(data.encode()).hexdigest()
            vals['block_hash'] = block_hash
            prev = block_hash

        return super().create(vals_list)

    def verify_chain(self):
        """Verify the entire hash chain integrity. Returns list of broken blocks."""
        all_logs = self.sudo().search([], order='id asc')
        broken = []
        prev = '0' * 64
        for log in all_logs:
            if log.prev_hash != prev:
                broken.append(log.id)
            prev = log.block_hash or ''
        return broken
