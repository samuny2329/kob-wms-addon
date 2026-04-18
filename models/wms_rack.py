from odoo import models, fields, api


class WmsRack(models.Model):
    _name = 'wms.rack'
    _description = 'WMS Bulk Storage Rack'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'code'

    name = fields.Char(string='Rack Name', required=True, tracking=True)
    code = fields.Char(string='Code', required=True, tracking=True)
    zone_id = fields.Many2one('wms.zone', string='Zone', required=True,
                              ondelete='restrict', tracking=True)
    location_id = fields.Many2one('stock.location', string='Stock Location',
                                  help='Linked Odoo stock location')
    company_id = fields.Many2one('res.company', related='zone_id.company_id',
                                 store=True)
    frozen = fields.Boolean(string='Frozen', default=False, tracking=True,
                            help='If frozen, transfers are blocked on this rack.')
    frozen_reason = fields.Char(string='Freeze Reason')
    capacity = fields.Integer(string='Capacity (boxes)', default=0)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('code_zone_unique', 'unique(code, zone_id)',
         'Rack code must be unique per zone!'),
    ]

    def action_toggle_freeze(self):
        for rack in self:
            rack.frozen = not rack.frozen
            if not rack.frozen:
                rack.frozen_reason = False
