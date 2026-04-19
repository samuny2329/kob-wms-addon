from odoo import models, fields, api, _
from odoo.exceptions import UserError


class SaleOrderType(models.Model):
    """Sale Order Type — matches UAT's sale_order_type module."""
    _name = 'sale.order.type'
    _description = 'Sale Order Type'
    _order = 'name'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        """Block validation if any move touches a location being counted."""
        for picking in self:
            for move in picking.move_ids:
                for loc in (move.location_id, move.location_dest_id):
                    if loc.counting_task_id:
                        raise UserError(_(
                            '🔒 Location "%s" is currently being counted '
                            '(Task: %s).\n'
                            'Please wait until counting is complete before '
                            'validating this transfer.'
                        ) % (loc.display_name, loc.counting_task_id.name))
        return super().button_validate()

    sale_order_type_id = fields.Many2one(
        'sale.order.type', string='Order Type',
        related='sale_id.sale_order_type_id', store=True, readonly=True)
    sale_order_type_name = fields.Char(
        related='sale_order_type_id.name', store=True)

    wms_sales_order_ids = fields.One2many(
        'wms.sales.order', 'picking_id', string='WMS Orders')
    wms_sales_order_count = fields.Integer(
        compute='_compute_wms_counts', string='WMS Orders')

    @api.depends('wms_sales_order_ids')
    def _compute_wms_counts(self):
        for picking in self:
            picking.wms_sales_order_count = len(picking.wms_sales_order_ids)

    def action_create_wms_order(self):
        self.ensure_one()
        wms_order = self.env['wms.sales.order'].create({
            'picking_id': self.id,
            'ref': self.name,
            'partner_id': self.partner_id.id if self.partner_id else False,
            'customer': self.partner_id.name if self.partner_id else '',
        })
        wms_order.action_import_from_sale_order()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'wms.sales.order',
            'res_id': wms_order.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_wms_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('WMS Orders'),
            'res_model': 'wms.sales.order',
            'view_mode': 'list,form',
            'domain': [('picking_id', '=', self.id)],
        }


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    sale_order_type_id = fields.Many2one(
        'sale.order.type', string='Order Type', tracking=True)
    sale_order_type_name = fields.Char(
        related='sale_order_type_id.name', store=True)

    wms_sales_order_ids = fields.One2many(
        'wms.sales.order', 'sale_order_id', string='WMS Orders')
    wms_sales_order_count = fields.Integer(
        compute='_compute_wms_counts', string='WMS Orders')

    @api.depends('wms_sales_order_ids')
    def _compute_wms_counts(self):
        for so in self:
            so.wms_sales_order_count = len(so.wms_sales_order_ids)

    def action_create_wms_order(self):
        self.ensure_one()
        wms_order = self.env['wms.sales.order'].create({
            'sale_order_id': self.id,
            'ref': self.name,
            'partner_id': self.partner_id.id,
            'customer': self.partner_id.name,
        })
        wms_order.action_import_from_sale_order()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'wms.sales.order',
            'res_id': wms_order.id,
            'view_mode': 'form',
            'target': 'current',
        }
