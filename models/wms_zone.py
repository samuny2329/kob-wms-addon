from odoo import models, fields, api


class WmsZone(models.Model):
    _name = 'wms.zone'
    _description = 'WMS Zone'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'code'

    name = fields.Char(string='Zone Name', required=True, tracking=True)
    code = fields.Char(string='Code', required=True, tracking=True,
                       help='Short code, e.g. A, B, C, FLG')
    color = fields.Integer(string='Color')
    color_hex = fields.Char(string='Color HEX', default='#3b82f6',
                            help='Display color for maps and dashboards')
    warehouse_id = fields.Many2one('stock.warehouse', string='Warehouse',
                                   required=True,
                                   default=lambda self: self.env['stock.warehouse'].search(
                                       [('company_id', '=', self.env.company.id)], limit=1))
    company_id = fields.Many2one('res.company', string='Company',
                                 related='warehouse_id.company_id', store=True)
    rack_ids = fields.One2many('wms.rack', 'zone_id', string='Racks')
    rack_count = fields.Integer(string='Rack Count', compute='_compute_rack_count')
    active = fields.Boolean(default=True)
    note = fields.Text(string='Note')

    _sql_constraints = [
        ('code_unique', 'unique(code, warehouse_id)',
         'Zone code must be unique per warehouse!'),
    ]

    @api.depends('rack_ids')
    def _compute_rack_count(self):
        for zone in self:
            zone.rack_count = len(zone.rack_ids)
