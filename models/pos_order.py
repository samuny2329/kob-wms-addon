from odoo import models, fields, api, _


class PosOrder(models.Model):
    _inherit = 'pos.order'

    wms_sales_order_ids = fields.One2many(
        'wms.sales.order', compute='_compute_wms_sales_order_ids',
        string='WMS Orders',
    )
    wms_sales_order_count = fields.Integer(
        compute='_compute_wms_sales_order_ids', string='WMS Orders',
    )

    def _compute_wms_sales_order_ids(self):
        WmsOrder = self.env['wms.sales.order']
        for order in self:
            linked = WmsOrder.search([('ref', '=', order.name)])
            order.wms_sales_order_ids = linked
            order.wms_sales_order_count = len(linked)

    # ------------------------------------------------------------------
    # Auto-create wms.sales.order from POS order
    # ------------------------------------------------------------------
    def _kob_wms_create_order(self):
        WmsOrder = self.env['wms.sales.order']
        WmsLine = self.env['wms.sales.order.line']

        for order in self:
            if order.state not in ('paid', 'done', 'invoiced'):
                continue

            mode = order.config_id.wms_fulfillment_mode if order.config_id else 'immediate'
            if mode == 'disabled':
                continue

            # Idempotent — skip if already linked
            if WmsOrder.search_count([('ref', '=', order.name)]):
                continue

            picking = order.picking_ids[:1] if order.picking_ids else False

            # Decide initial status based on fulfillment mode
            if mode == 'pick_pack':
                # Send to pick queue — worker must pick+pack+ship
                initial_status = 'pending'
                picked_init = 0
                packed_init = 0
            else:
                # Immediate — POS already released stock, just dispatch
                initial_status = 'packed'
                picked_init = None  # will be set per-line
                packed_init = None

            courier_id = False
            if order.config_id and order.config_id.wms_default_courier_id:
                courier_id = order.config_id.wms_default_courier_id.id

            wms_order_vals = {
                'ref': order.name,
                'customer': (order.partner_id and order.partner_id.name)
                            or _('POS Walk-in'),
                'partner_id': order.partner_id.id if order.partner_id else False,
                'platform': 'pos',
                'picking_id': picking.id if picking else False,
                'status': initial_status,
                'courier_id': courier_id,
            }
            if initial_status == 'packed':
                wms_order_vals['box_barcode'] = order.name

            wms_order = WmsOrder.create(wms_order_vals)

            for pol in order.lines:
                if not pol.product_id:
                    continue
                qty = int(pol.qty or 0)
                if qty <= 0:
                    continue
                # For pick_pack mode leave qty=0, for immediate pre-fill
                p_qty = picked_init if picked_init is not None else qty
                k_qty = packed_init if packed_init is not None else qty
                WmsLine.create({
                    'order_id': wms_order.id,
                    'product_id': pol.product_id.id,
                    'product_name': pol.product_id.display_name,
                    'sku': pol.product_id.default_code or pol.product_id.barcode or '',
                    'expected_qty': qty,
                    'picked_qty': p_qty,
                    'packed_qty': k_qty,
                })

            if mode == 'pick_pack':
                wms_order.message_post(
                    body=_('POS order %s queued for WMS pick → pack → ship.')
                    % order.name
                )
            else:
                wms_order.message_post(
                    body=_('POS order %s auto-packed (immediate mode).')
                    % order.name
                )

    def action_pos_order_paid(self):
        res = super().action_pos_order_paid()
        try:
            self._kob_wms_create_order()
        except Exception as exc:
            self.env['ir.logging'].sudo().create({
                'name': 'kob_wms.pos_sync',
                'type': 'server',
                'level': 'WARNING',
                'dbname': self.env.cr.dbname,
                'message': 'WMS sync failed for POS %s: %s' % (self.name, exc),
                'path': 'kob_wms/pos_order.py',
                'func': 'action_pos_order_paid',
                'line': '0',
            })
        return res

    # ------------------------------------------------------------------
    # Smart button + manual actions on pos.order form
    # ------------------------------------------------------------------
    def action_view_wms_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('WMS Orders'),
            'res_model': 'wms.sales.order',
            'view_mode': 'list,form',
            'domain': [('ref', '=', self.name)],
        }

    def action_force_create_wms_order(self):
        """Manually push a POS order into the WMS pick queue even if the
        config says 'disabled' or 'immediate'. Used when cashier wants to
        hand off an existing order to the warehouse."""
        self.ensure_one()
        WmsOrder = self.env['wms.sales.order']
        existing = WmsOrder.search([('ref', '=', self.name)], limit=1)
        if existing:
            return existing.get_formview_action()

        courier_id = False
        if self.config_id and self.config_id.wms_default_courier_id:
            courier_id = self.config_id.wms_default_courier_id.id

        wms_order = WmsOrder.create({
            'ref': self.name,
            'customer': (self.partner_id and self.partner_id.name)
                        or _('POS Walk-in'),
            'partner_id': self.partner_id.id if self.partner_id else False,
            'platform': 'pos',
            'picking_id': self.picking_ids[:1].id if self.picking_ids else False,
            'status': 'pending',
            'courier_id': courier_id,
        })
        for pol in self.lines:
            if not pol.product_id:
                continue
            qty = int(pol.qty or 0)
            if qty <= 0:
                continue
            self.env['wms.sales.order.line'].create({
                'order_id': wms_order.id,
                'product_id': pol.product_id.id,
                'product_name': pol.product_id.display_name,
                'sku': pol.product_id.default_code or pol.product_id.barcode or '',
                'expected_qty': qty,
            })
        wms_order.message_post(
            body=_('Manually pushed to WMS pick queue from POS %s.') % self.name
        )
        return wms_order.get_formview_action()

    def action_open_wms_scanner(self):
        """Open the WMS scan wizard in pick mode for this POS order."""
        self.ensure_one()
        wms_order = self.env['wms.sales.order'].search(
            [('ref', '=', self.name)], limit=1,
        )
        if not wms_order:
            wms_order = self._create_wms_order_on_demand()
        return self.env['wms.scan.wizard'].action_open_from_order(
            wms_order.id, 'pick',
        )

    def _create_wms_order_on_demand(self):
        """Helper for action_open_wms_scanner — ensures a wms.sales.order
        exists before the wizard opens."""
        self.ensure_one()
        return self.env['wms.sales.order'].create({
            'ref': self.name,
            'customer': (self.partner_id and self.partner_id.name)
                        or _('POS Walk-in'),
            'partner_id': self.partner_id.id if self.partner_id else False,
            'platform': 'pos',
            'picking_id': self.picking_ids[:1].id if self.picking_ids else False,
            'status': 'pending',
        })
