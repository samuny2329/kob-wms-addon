from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class WmsCancelReturnWizard(models.TransientModel):
    """Ask for a reason, create a stock return picking (Customer → warehouse)."""
    _name = 'wms.cancel.return.wizard'
    _description = 'WMS Return Items'

    order_id = fields.Many2one('wms.sales.order', required=True, readonly=True,
                               string='Order')
    order_name = fields.Char(related='order_id.name', readonly=True)
    order_status = fields.Selection(related='order_id.status', readonly=True)

    reason = fields.Text(string='Return Reason',
                         placeholder='e.g. Customer cancelled, Wrong item, Damaged...')

    # Populated after confirming
    return_ref = fields.Char(string='Return Delivery', readonly=True)
    confirmed = fields.Boolean(default=False, readonly=True)

    def action_confirm(self):
        """Create Odoo return delivery (Customer → original warehouse location)."""
        self.ensure_one()
        if not self.reason or not self.reason.strip():
            raise UserError(_('Please enter a return reason.'))

        order = self.order_id
        return_ref = False

        # Create stock.picking return if delivery is validated
        if order.picking_id and order.picking_id.state == 'done':
            try:
                return_picking = self._create_return_picking(order, self.reason)
                if return_picking:
                    return_ref = return_picking.name
            except Exception as exc:
                _logger.warning('Could not create return picking for %s: %s',
                                order.name, exc)

        order._log_action('return', self.reason,
                          note=_('Return ref: %s') % (return_ref or _('—')))

        self.write({'return_ref': return_ref or '', 'confirmed': True})

        # Reopen wizard to show result
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    @api.model
    def _create_return_picking(self, order, reason):
        """Create a return picking (Customer → original warehouse location)."""
        picking = order.picking_id
        ctx = {'active_id': picking.id, 'active_model': 'stock.picking'}
        wizard = self.env['stock.return.picking'].with_context(ctx).create(
            {'picking_id': picking.id}
        )
        new_picking_id, _ = wizard._create_returns()
        new_picking = self.env['stock.picking'].browse(new_picking_id)
        new_picking.write({
            'origin': _('Return: %s') % order.name,
            'note': reason,
        })
        return new_picking
