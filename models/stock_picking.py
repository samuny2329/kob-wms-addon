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
        res = super().button_validate()
        for picking in self:
            picking._auto_create_cmn_packaging_receipt()
        return res

    def _auto_create_cmn_packaging_receipt(self):
        """After KOB validates an incoming receipt, auto-create a draft
        non-value receipt for CMN-WH for products flagged is_cmn_packaging."""
        if self.state != 'done':
            return
        if self.picking_type_code != 'incoming':
            return

        # Only trigger from KOB company receipts
        cmn_wh = self.env['stock.warehouse'].sudo().search(
            [('code', '=', 'CMNW')], limit=1)
        if not cmn_wh or self.company_id == cmn_wh.company_id:
            return  # skip if already CMN or CMN not found

        # Collect packaging move lines (done qty > 0)
        cmn_lines = self.move_line_ids.filtered(
            lambda l: l.product_id.is_cmn_packaging and l.quantity > 0
        )
        if not cmn_lines:
            return

        cmn_company = cmn_wh.company_id
        cmn_picking_type = self.env['stock.picking.type'].sudo().search([
            ('warehouse_id', '=', cmn_wh.id),
            ('code', '=', 'incoming'),
        ], limit=1)
        if not cmn_picking_type:
            return

        supplier_loc = self.env.ref('stock.stock_location_suppliers', raise_if_not_found=False)
        if not supplier_loc:
            supplier_loc = self.env['stock.location'].sudo().search(
                [('usage', '=', 'supplier')], limit=1)

        # Group by product+uom
        product_qtys = {}
        for line in cmn_lines:
            key = (line.product_id.id, line.product_uom_id.id)
            product_qtys[key] = product_qtys.get(key, 0) + line.quantity

        move_vals = [(0, 0, {
            'name': self.env['product.product'].browse(pid).display_name,
            'product_id': pid,
            'product_uom': uom_id,
            'product_uom_qty': qty,
            'price_unit': 0.0,
            'company_id': cmn_company.id,
            'location_id': supplier_loc.id,
            'location_dest_id': cmn_wh.lot_stock_id.id,
        }) for (pid, uom_id), qty in product_qtys.items()]

        cmn_receipt = self.env['stock.picking'].sudo().with_company(cmn_company).create({
            'picking_type_id': cmn_picking_type.id,
            'company_id': cmn_company.id,
            'partner_id': self.partner_id.id if self.partner_id else False,
            'location_id': supplier_loc.id,
            'location_dest_id': cmn_wh.lot_stock_id.id,
            'origin': _('Auto-transfer from KOB: %s') % self.name,
            'note': _('Non-value transfer from KOB. Please attach transfer document before validating.'),
            'move_ids': move_vals,
        })
        cmn_receipt.action_confirm()

        self.message_post(body=_(
            '📦 สร้าง CMN receipt อัตโนมัติ (non-value): <b>%s</b><br/>'
            'กรุณาให้ CMN แนบเอกสารแล้ว validate'
        ) % cmn_receipt.name)

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
