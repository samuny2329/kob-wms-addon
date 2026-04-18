from odoo import models, fields, api, _
from odoo.exceptions import UserError


class WmsCountAdjustment(models.Model):
    """Bridge between WMS count verification and Odoo stock adjustment.

    Created when a Supervisor verifies a count task.  Stays in 'pending'
    until a Manager approves, then 'action_apply' pushes the counted qty
    into stock.quant via Odoo's native _apply_inventory() mechanism.
    """
    _name = 'wms.count.adjustment'
    _description = 'WMS Inventory Adjustment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(
        string='Reference', required=True, copy=False, readonly=True,
        default=lambda self: _('New'))
    session_id = fields.Many2one(
        'wms.count.session', string='Count Session',
        required=True, ondelete='cascade', index=True)
    task_id = fields.Many2one(
        'wms.count.task', string='Count Task',
        required=True, ondelete='cascade', index=True)
    product_id = fields.Many2one(
        'product.product', string='Product', required=True, index=True)
    location_id = fields.Many2one(
        'stock.location', string='Location', required=True)
    lot_id = fields.Many2one('stock.lot', string='Lot/Serial')

    # ── Quantities ─────────────────────────────────────────────
    system_qty = fields.Float(
        string='System Qty',
        help='stock.quant.quantity snapshot at verification time')
    counted_qty = fields.Float(
        string='Counted Qty',
        help='Aggregated qty from scan entries')
    variance_qty = fields.Float(
        string='Variance', compute='_compute_variance', store=True)
    variance_pct = fields.Float(
        string='Variance %', compute='_compute_variance', store=True)

    # ── State ──────────────────────────────────────────────────
    state = fields.Selection([
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('applied', 'Applied'),
        ('rejected', 'Rejected'),
    ], string='State', default='pending', tracking=True, index=True)

    # ── Audit trail ────────────────────────────────────────────
    verified_by = fields.Many2one('res.users', string='Verified By')
    verified_date = fields.Datetime(string='Verified Date')
    approved_by = fields.Many2one('res.users', string='Approved By')
    approved_date = fields.Datetime(string='Approved Date')
    applied_date = fields.Datetime(string='Applied Date')
    reject_reason = fields.Text(string='Reject Reason')

    # ── Odoo links ─────────────────────────────────────────────
    quant_id = fields.Many2one(
        'stock.quant', string='Stock Quant', ondelete='set null')
    move_id = fields.Many2one(
        'stock.move', string='Stock Move', ondelete='set null',
        help='The inventory adjustment move created by Odoo')

    company_id = fields.Many2one(
        'res.company', related='session_id.company_id', store=True)
    note = fields.Text(string='Note')

    @api.depends('counted_qty', 'system_qty')
    def _compute_variance(self):
        for adj in self:
            adj.variance_qty = adj.counted_qty - adj.system_qty
            if adj.system_qty:
                adj.variance_pct = round(
                    (adj.variance_qty / adj.system_qty) * 100, 1)
            else:
                adj.variance_pct = 100.0 if adj.counted_qty else 0.0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'wms.count.adjustment') or _('New')
        return super().create(vals_list)

    # ── Actions ────────────────────────────────────────────────

    def action_approve(self):
        """Approve and write counted qty into Odoo's native stock.quant.

        Sets inventory_quantity on the relevant stock.quant record so the
        item appears in Inventory → Inventory Adjustments ready for
        the manager to review and click 'Apply All' there.

        WMS does NOT call _apply_inventory() — stock adjustment is
        delegated entirely to the native Odoo button.
        """
        Quant = self.env['stock.quant']
        for adj in self:
            if adj.state != 'pending':
                raise UserError(_('Only pending adjustments can be approved.'))

        self.write({
            'state': 'approved',
            'approved_by': self.env.uid,
            'approved_date': fields.Datetime.now(),
        })

        # ── Write to stock.quant (stage for native Odoo approval) ───
        ctx = {'inventory_mode': True}
        for adj in self:
            quant = Quant._gather(
                adj.product_id, adj.location_id,
                lot_id=adj.lot_id, strict=True)

            if not quant:
                # Product not in this location yet — create quant entry
                new_quant = Quant.with_context(**ctx).create({
                    'product_id':    adj.product_id.id,
                    'location_id':   adj.location_id.id,
                    'lot_id':        adj.lot_id.id if adj.lot_id else False,
                    'inventory_quantity': adj.counted_qty,
                })
                adj.quant_id = new_quant
            else:
                q = quant[0]
                q.with_context(**ctx).write({
                    'inventory_quantity': adj.counted_qty,
                })
                adj.quant_id = q

            adj.message_post(body=_(
                'Approved by <b>%s</b>. Variance: %+.2f (%+.1f%%)<br/>'
                'Counted qty staged in Odoo Inventory Adjustments — '
                'go to <b>Inventory → Inventory Adjustments</b> and click '
                '<b>Apply All</b> to update stock.')
                % (self.env.user.name, adj.variance_qty, adj.variance_pct))

    def action_apply(self):
        """Finalise — call _apply_inventory() on the staged quant.

        action_approve() already wrote inventory_quantity to stock.quant.
        This step creates the inventory stock.move and updates on-hand qty.
        """
        ctx = {'inventory_mode': True}
        for adj in self:
            if adj.state != 'approved':
                raise UserError(_(
                    'Adjustment %s must be approved before applying.') % adj.name)

            quant = adj.quant_id
            if not quant:
                # Fallback: re-gather in case quant_id wasn't set
                quant = self.env['stock.quant']._gather(
                    adj.product_id, adj.location_id,
                    lot_id=adj.lot_id, strict=True)
                if quant:
                    quant = quant[0]
                    quant.with_context(**ctx).write({
                        'inventory_quantity': adj.counted_qty,
                    })
                else:
                    raise UserError(_(
                        'No stock quant found for %s @ %s.')
                        % (adj.product_id.display_name, adj.location_id.display_name))

            # Apply → creates is_inventory stock.move, resets inventory_quantity
            quant.with_context(**ctx)._apply_inventory()

            # Link the resulting move
            move = self.env['stock.move'].search([
                ('product_id', '=', adj.product_id.id),
                ('is_inventory', '=', True),
                ('state', '=', 'done'),
            ], order='create_date desc', limit=1)

            adj.write({
                'state': 'applied',
                'applied_date': fields.Datetime.now(),
                'move_id': move.id if move else False,
            })
            adj.message_post(body=_(
                'Applied ✅ Stock adjusted. Move: %s')
                % (move.name if move else 'N/A'))

    def action_reject(self):
        for adj in self:
            if adj.state not in ('pending', 'approved'):
                raise UserError(_('Cannot reject an already applied adjustment.'))
        self.write({'state': 'rejected'})
        for adj in self:
            adj.message_post(body=_('Rejected by %s.') % self.env.user.name)

    def action_mark_applied(self):
        """Mark as applied after using Odoo's native Inventory Adjustments → Apply All.

        WMS does NOT call _apply_inventory() — the manager uses the native
        Odoo button.  This just closes the WMS record and records the date.
        """
        for adj in self:
            if adj.state != 'approved':
                raise UserError(_('Only approved adjustments can be marked as applied.'))
        self.write({
            'state': 'applied',
            'applied_date': fields.Datetime.now(),
        })
        for adj in self:
            adj.message_post(body=_(
                'Marked as Applied ✅ — applied via Odoo Inventory Adjustments.'))

    # ── Factory ────────────────────────────────────────────────

    @api.model
    def _create_from_task(self, task):
        """Create adjustment lines from a verified count task.

        Groups entries by (product, lot) and snapshots current system qty.
        """
        Quant = self.env['stock.quant']
        vals_list = []

        # Aggregate entries by product + lot
        product_lot_map = {}  # (product_id, lot_id) → total_qty
        for entry in task.entry_ids:
            key = (entry.product_id.id, entry.lot_id.id if entry.lot_id else False)
            product_lot_map[key] = product_lot_map.get(key, 0) + entry.qty

        location = task.location_id
        if not location:
            return self.browse()

        for (product_id, lot_id), counted in product_lot_map.items():
            product = self.env['product.product'].browse(product_id)
            lot = self.env['stock.lot'].browse(lot_id) if lot_id else False

            # Snapshot system qty
            quant = Quant._gather(product, location, lot_id=lot, strict=True)
            system_qty = quant[0].quantity if quant else 0.0

            vals_list.append({
                'session_id': task.session_id.id,
                'task_id': task.id,
                'product_id': product_id,
                'location_id': location.id,
                'lot_id': lot_id or False,
                'system_qty': system_qty,
                'counted_qty': counted,
                'verified_by': self.env.uid,
                'verified_date': fields.Datetime.now(),
                'state': 'pending',
            })

        # Full count mode: detect products in system but NOT scanned
        if task.session_id.session_type == 'full':
            system_quants = Quant.search([
                ('location_id', '=', location.id),
                ('quantity', '>', 0),
            ])
            for sq in system_quants:
                key = (sq.product_id.id, sq.lot_id.id if sq.lot_id else False)
                if key not in product_lot_map:
                    # Product in system but not counted → variance = -system_qty
                    vals_list.append({
                        'session_id': task.session_id.id,
                        'task_id': task.id,
                        'product_id': sq.product_id.id,
                        'location_id': location.id,
                        'lot_id': sq.lot_id.id if sq.lot_id else False,
                        'system_qty': sq.quantity,
                        'counted_qty': 0.0,
                        'verified_by': self.env.uid,
                        'verified_date': fields.Datetime.now(),
                        'state': 'pending',
                    })

        return self.create(vals_list) if vals_list else self.browse()
