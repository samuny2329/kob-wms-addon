from odoo import models, fields, api, _


class WmsPickface(models.Model):
    _name = 'wms.pickface'
    _description = 'WMS Pickface (Pick Bin)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'code'

    name = fields.Char(string='Pickface Name', required=True, tracking=True)
    code = fields.Char(string='Code', required=True, tracking=True)
    zone_id = fields.Many2one('wms.zone', string='Zone', required=True)
    product_id = fields.Many2one('product.product', string='Assigned Product',
                                 tracking=True)
    location_id = fields.Many2one('stock.location', string='Stock Location')
    min_qty = fields.Float(string='Min Level', default=0.0)
    max_qty = fields.Float(string='Max Level', default=0.0)
    current_qty = fields.Float(string='Current Qty',
                               compute='_compute_current_qty', store=True)
    restock_qty = fields.Float(string='Restock Qty',
                               compute='_compute_restock_qty')
    needs_restock = fields.Boolean(string='Needs Restock',
                                   compute='_compute_needs_restock', store=True)
    company_id = fields.Many2one('res.company', related='zone_id.company_id',
                                 store=True)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('code_unique', 'unique(code, zone_id)',
         'Pickface code must be unique per zone!'),
    ]

    @api.depends('product_id', 'location_id')
    def _compute_current_qty(self):
        for pf in self:
            if pf.product_id and pf.location_id:
                quants = self.env['stock.quant'].search([
                    ('product_id', '=', pf.product_id.id),
                    ('location_id', '=', pf.location_id.id),
                ])
                pf.current_qty = sum(q.quantity for q in quants)
            else:
                pf.current_qty = 0

    @api.depends('current_qty', 'max_qty')
    def _compute_restock_qty(self):
        for pf in self:
            pf.restock_qty = max(pf.max_qty - pf.current_qty, 0) if pf.max_qty else 0

    @api.depends('current_qty', 'min_qty')
    def _compute_needs_restock(self):
        for pf in self:
            pf.needs_restock = pf.min_qty > 0 and pf.current_qty <= pf.min_qty

    def action_create_restock_transfer(self):
        """Create internal transfer from Bulk → Pickface to restock."""
        self.ensure_one()
        if not self.product_id or not self.location_id:
            return

        # Find bulk storage location in same warehouse
        warehouse = self.location_id.warehouse_id
        if not warehouse:
            return

        bulk_loc = self.env['stock.location'].search([
            ('usage', '=', 'internal'),
            ('warehouse_id', '=', warehouse.id),
            ('name', 'ilike', 'Stock'),
            ('id', '!=', self.location_id.id),
        ], limit=1)
        if not bulk_loc:
            return

        # Find internal transfer picking type
        int_type = self.env['stock.picking.type'].search([
            ('code', '=', 'internal'),
            ('warehouse_id', '=', warehouse.id),
        ], limit=1)
        if not int_type:
            return

        qty = self.restock_qty
        if qty <= 0:
            return

        picking = self.env['stock.picking'].create({
            'picking_type_id': int_type.id,
            'location_id': bulk_loc.id,
            'location_dest_id': self.location_id.id,
            'origin': _('Restock %s') % self.code,
        })
        self.env['stock.move'].create({
            'name': _('Restock %s → %s') % (self.product_id.display_name, self.code),
            'picking_id': picking.id,
            'product_id': self.product_id.id,
            'product_uom_qty': qty,
            'product_uom': self.product_id.uom_id.id,
            'location_id': bulk_loc.id,
            'location_dest_id': self.location_id.id,
        })
        picking.action_confirm()
        picking.action_assign()

        self.message_post(body=_(
            'Restock transfer created: %s (%.0f units from %s)'
        ) % (picking.name, qty, bulk_loc.complete_name))

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'res_id': picking.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.model
    def _auto_register_product(self, product, location, qty):
        """Auto-create pickface record when product enters PICKFACE location."""
        if not product or not location:
            return
        existing = self.search([
            ('product_id', '=', product.id),
            ('location_id', '=', location.id),
        ], limit=1)
        if existing:
            return existing

        # Find zone from location's warehouse
        zone = False
        if location.warehouse_id:
            zone = self.env['wms.zone'].search([
                ('warehouse_id', '=', location.warehouse_id.id),
            ], limit=1)

        code = product.default_code or str(product.id)
        min_qty = max(int(qty * 0.2), 1)
        max_qty = max(int(qty * 1.5), 10)

        return self.create({
            'name': 'Pickface %s' % code,
            'code': 'PF-%s' % code,
            'zone_id': zone.id if zone else False,
            'product_id': product.id,
            'location_id': location.id,
            'min_qty': min_qty,
            'max_qty': max_qty,
        })

    def action_bulk_restock(self):
        """Create restock transfers for all pickfaces that need it."""
        to_restock = self.search([('needs_restock', '=', True)])
        created = 0
        for pf in to_restock:
            try:
                pf.action_create_restock_transfer()
                created += 1
            except Exception:
                pass
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Bulk Restock'),
                'message': _('Created %d restock transfers.') % created,
                'type': 'success',
            }
        }
