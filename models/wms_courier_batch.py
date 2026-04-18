from odoo import models, fields, api, _
from odoo.exceptions import UserError


class WmsCourierBatch(models.Model):
    """React `courierBatches` + `historyData` — one document per dispatch run.
    Items are scanned in and the batch is closed with a signature."""
    _name = 'wms.courier.batch'
    _description = 'WMS Courier Batch (Dispatch)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(string='Batch ID', required=True, copy=False,
                       readonly=True, default=lambda self: _('New'))
    courier_id = fields.Many2one('wms.courier', string='Courier',
                                 required=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('scanning', 'Scanning'),
        ('dispatched', 'Dispatched'),
        ('cancelled', 'Cancelled'),
    ], string='State', default='draft', tracking=True)
    work_date = fields.Date(string='Work Date',
                            default=fields.Date.context_today)
    scan_item_ids = fields.One2many('wms.scan.item', 'batch_id',
                                    string='Scanned Items')
    scanned_count = fields.Integer(compute='_compute_scanned_count',
                                   store=True)
    signature = fields.Binary(string='Receiver Signature')
    receiver_name = fields.Char(string='Receiver Name')
    dispatched_at = fields.Datetime(string='Dispatched At')
    dispatched_by = fields.Many2one('res.users', string='Dispatched By')
    note = fields.Text(string='Note')
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company)

    @api.depends('scan_item_ids')
    def _compute_scanned_count(self):
        for batch in self:
            batch.scanned_count = len(batch.scan_item_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'wms.courier.batch') or _('New')
        return super().create(vals_list)

    def action_start_scanning(self):
        self.write({'state': 'scanning'})

    def action_dispatch(self):
        for batch in self:
            if not batch.scan_item_ids:
                raise UserError(_('Cannot dispatch an empty batch.'))
            if not batch.signature:
                raise UserError(_('Please collect the receiver signature first.'))
            batch.state = 'dispatched'
            batch.dispatched_at = fields.Datetime.now()
            batch.dispatched_by = self.env.user
        return True

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_draft(self):
        self.write({'state': 'draft'})


class WmsScanItem(models.Model):
    """Individual scan inside a courier batch. Matches React `orderData`
    entries (barcode, courier, orderNumber, shopName, importDate)."""
    _name = 'wms.scan.item'
    _description = 'WMS Scan Item'
    _order = 'scanned_at desc'

    barcode = fields.Char(string='Barcode / AWB', required=True)
    courier_id = fields.Many2one('wms.courier', string='Courier',
                                 required=True)
    batch_id = fields.Many2one('wms.courier.batch', string='Batch',
                               ondelete='set null')
    order_ref = fields.Char(string='Order Ref')
    shop_name = fields.Char(string='Shop / Platform')
    expected_qty = fields.Integer(string='Expected', default=1)
    scanned_qty = fields.Integer(string='Scanned', default=0)
    import_date = fields.Date(string='Import Date',
                              default=fields.Date.context_today)
    scanned_at = fields.Datetime(string='Scanned At',
                                 default=fields.Datetime.now)
    scanned_by = fields.Many2one('res.users', string='Scanned By',
                                 default=lambda self: self.env.user)
    sales_order_id = fields.Many2one('wms.sales.order', string='Source SO',
                                     ondelete='set null')
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company)
