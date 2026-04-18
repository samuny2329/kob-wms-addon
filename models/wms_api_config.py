from odoo import models, fields


class WmsApiConfig(models.Model):
    """React `apiConfigs` — per-platform API credentials and enable flags."""
    _name = 'wms.api.config'
    _description = 'WMS Platform API Configuration'
    _rec_name = 'platform'

    platform = fields.Selection([
        ('odoo', 'Odoo ERP'),
        ('shopee', 'Shopee'),
        ('lazada', 'Lazada'),
        ('tiktok', 'TikTok'),
    ], string='Platform', required=True)
    enabled = fields.Boolean(string='Enabled', default=False)
    api_key = fields.Char(string='API Key')
    api_secret = fields.Char(string='API Secret')
    endpoint_url = fields.Char(string='Endpoint URL')
    shop_id = fields.Char(string='Shop ID')
    note = fields.Text(string='Note')
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company)

    _sql_constraints = [
        ('platform_company_unique', 'unique(platform, company_id)',
         'One configuration per platform per company.'),
    ]
