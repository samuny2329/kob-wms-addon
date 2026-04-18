from odoo import models, fields, api


class WmsCountEntry(models.Model):
    _name = 'wms.count.entry'
    _description = 'WMS Count Entry (individual scan)'
    _order = 'create_date desc'

    task_id = fields.Many2one('wms.count.task', string='Task',
                              required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product',
                                 required=True)
    lot_id = fields.Many2one('stock.lot', string='Lot/Serial')
    scan_type = fields.Selection([
        ('box', 'Box'),
        ('piece', 'Piece'),
    ], string='Type', default='box', required=True)
    qty = fields.Float(string='Quantity', default=1.0)
    barcode = fields.Char(string='Barcode Scanned')
    user_id = fields.Many2one('res.users', string='Scanned By',
                              default=lambda self: self.env.user)
    scan_time = fields.Datetime(string='Scan Time',
                                default=fields.Datetime.now)
    company_id = fields.Many2one('res.company', related='task_id.company_id',
                                 store=True)
