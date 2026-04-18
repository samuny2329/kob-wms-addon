from odoo import models, fields


class WmsCourier(models.Model):
    """Courier master — Thailand Post, Flash, J&T, Shopee Express, etc.
    Used to group outbound scans into batches."""
    _name = 'wms.courier'
    _description = 'WMS Courier'
    _order = 'sequence, name'

    name = fields.Char(string='Courier', required=True)
    code = fields.Char(string='Code')
    sequence = fields.Integer(default=10)
    color_hex = fields.Char(string='Color', default='#3b82f6')
    tracking_url_template = fields.Char(
        string='Tracking URL Template',
        help="e.g. https://track.thailandpost.co.th/?trackNumber={barcode}")
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company)

    _sql_constraints = [
        ('code_unique', 'unique(code, company_id)',
         'Courier code must be unique per company!'),
    ]
