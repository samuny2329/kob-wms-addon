from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import timedelta


class WmsSalesOrder(models.Model):
    """Matches React `salesOrders` state. One document per platform order that
    must be picked, packed, and handed off to a courier."""
    _name = 'wms.sales.order'
    _description = 'WMS Sales Order (Pick/Pack)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(string='Reference', required=True, copy=False,
                       readonly=True, default=lambda self: _('New'))
    ref = fields.Char(string='Platform Ref', tracking=True,
                      help='External reference from Shopee/Lazada/TikTok/Odoo')
    customer = fields.Char(string='Customer', tracking=True)
    partner_id = fields.Many2one('res.partner', string='Partner')
    platform = fields.Selection([
        ('odoo', 'Odoo'),
        ('shopee', 'Shopee'),
        ('lazada', 'Lazada'),
        ('tiktok', 'TikTok'),
        ('pos', 'Point of Sale'),
        ('manual', 'Manual'),
    ], string='Platform', default='manual', tracking=True)
    courier_id = fields.Many2one('wms.courier', string='Courier', tracking=True)
    awb = fields.Char(string='AWB / Tracking', tracking=True)
    box_barcode = fields.Char(string='Box Barcode', tracking=True)
    status = fields.Selection([
        ('pending', 'Pending'),
        ('picking', 'Picking'),
        ('picked', 'Picked'),
        ('packing', 'Packing'),
        ('packed', 'Packed'),
        ('shipped', 'Shipped'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='pending', tracking=True)
    line_ids = fields.One2many('wms.sales.order.line', 'order_id',
                               string='Items')
    quality_check_ids = fields.One2many('wms.quality.check', 'wms_order_id',
                                        string='Outgoing QC Checks')
    quality_check_count = fields.Integer(
        compute='_compute_qc_count', string='QC Checks')
    quality_check_pending = fields.Integer(
        compute='_compute_qc_count', string='Pending QC')
    picker_id = fields.Many2one('res.users', string='Picker (Odoo User)')
    packer_id = fields.Many2one('res.users', string='Packer (Odoo User)')
    shipper_id = fields.Many2one('res.users', string='Shipper (Odoo User)')
    # WMS portal worker — assigned from kob.wms.user login session
    kob_picker_id = fields.Many2one('kob.wms.user', string='Picker',
                                    index=True, ondelete='set null')
    kob_packer_id = fields.Many2one('kob.wms.user', string='Packer',
                                    index=True, ondelete='set null')

    # Smart Ring timestamps
    sla_start_at = fields.Datetime(string='SLA Start (Print Pick List)')
    pick_start_at = fields.Datetime(string='Pick Start')
    picked_at = fields.Datetime(string='Pick End')
    pack_start_at = fields.Datetime(string='Pack Start')
    packed_at = fields.Datetime(string='Pack End')
    shipped_at = fields.Datetime(string='Shipped At')

    # Smart Ring error counts
    pick_errors = fields.Integer(string='Pick Errors', default=0)
    pack_errors = fields.Integer(string='Pack Errors', default=0)

    # Smart Ring computed durations
    wait_pick_min = fields.Float(compute='_compute_durations', store=True,
                                  help='Wait: SLA start → Pick start')
    pick_duration_min = fields.Float(compute='_compute_durations', store=True,
                                      help='Pick: first scan → all picked')
    wait_pack_min = fields.Float(compute='_compute_durations', store=True,
                                  help='Wait: Pick end → Pack start')
    pack_duration_min = fields.Float(compute='_compute_durations', store=True,
                                      help='Pack: first scan → box closed')
    wait_ship_min = fields.Float(compute='_compute_durations', store=True,
                                  help='Wait: Pack end → Ship')
    ship_duration_min = fields.Float(compute='_compute_durations', store=True)
    total_duration_min = fields.Float(compute='_compute_durations', store=True,
                                      help='Total: SLA start → Shipped')

    # Difficulty metrics
    items_count = fields.Integer(compute='_compute_difficulty', store=True)
    sku_count = fields.Integer(compute='_compute_difficulty', store=True)
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company)

    # --- Core Odoo integration ---
    sale_order_id = fields.Many2one('sale.order', string='Sale Order',
                                    tracking=True, ondelete='set null')
    picking_id = fields.Many2one('stock.picking', string='Delivery Order',
                                 tracking=True, ondelete='set null')

    expected_total = fields.Integer(compute='_compute_totals', store=True)
    picked_total = fields.Integer(compute='_compute_totals', store=True)
    packed_total = fields.Integer(compute='_compute_totals', store=True)
    count_value = fields.Integer(
        string='Count Helper', default=1, readonly=True,
        help='Always 1, used as a pivot count measure in dashboards.')
    all_picked = fields.Boolean(compute='_compute_totals', store=True)
    all_packed = fields.Boolean(compute='_compute_totals', store=True)

    # --- SLA tracking ---
    sla_pick_deadline = fields.Datetime(
        compute='_compute_sla', store=True, string='Pick SLA Deadline')
    sla_pack_deadline = fields.Datetime(
        compute='_compute_sla', store=True, string='Pack SLA Deadline')
    sla_ship_deadline = fields.Datetime(
        compute='_compute_sla', store=True, string='Ship SLA Deadline')
    sla_status = fields.Selection([
        ('on_track', '✅ On Track'),
        ('at_risk', '⚠️ At Risk'),
        ('breached', '🔴 Breached'),
        ('done', '✓ Done'),
    ], string='SLA Status', compute='_compute_sla', store=True)

    # ── Box / Cartonization Analytics ────────────────────────────────────────
    actual_box_id = fields.Many2one(
        'wms.box.size', string='Box Used',
        compute='_compute_actual_box', store=True, index=True,
        help='Resolved from box_barcode → matches wms.box.size.code')
    suggested_box_id = fields.Many2one(
        'wms.box.size', string='AI Suggested Box',
        index=True, ondelete='set null',
        help='Box recommended by the AI cartonization algorithm')
    order_vol_m3 = fields.Float(
        string='Order Volume (m³)',
        compute='_compute_order_dims', store=True, digits=(12, 6),
        help='Sum of product.volume × picked_qty for all lines')
    order_weight_kg = fields.Float(
        string='Order Weight (kg)',
        compute='_compute_order_dims', store=True, digits=(10, 3),
        help='Sum of product.weight × picked_qty for all lines')
    box_fill_pct = fields.Float(
        string='Box Fill %',
        compute='_compute_box_analytics', store=True, digits=(5, 1),
        help='order_vol_m3 / actual box volume × 100')
    box_cost_est = fields.Float(
        string='Box Cost (฿)',
        compute='_compute_box_analytics', store=True, digits=(10, 2),
        help='Unit cost of the actual box used')
    tape_cost_est = fields.Float(
        string='Tape Cost (฿)',
        compute='_compute_box_analytics', store=True, digits=(10, 2),
        help='Estimated tape cost: [(W+H)×2 × rounds + overlap] ÷ 100 × ฿/m')
    bubble_cost_est = fields.Float(
        string='Bubble Wrap Cost (฿)',
        compute='_compute_box_analytics', store=True, digits=(10, 2),
        help='Bubble wrap material cost estimate for this box size')
    total_pack_cost = fields.Float(
        string='Total Pack Cost (฿)',
        compute='_compute_box_analytics', store=True, digits=(10, 2),
        help='Box + Tape + Bubble Wrap — total packaging material cost per order')
    box_suggestion_hit = fields.Boolean(
        string='AI Hit',
        compute='_compute_box_analytics', store=True,
        help='True when packer chose the AI-suggested box')

    @api.depends('quality_check_ids', 'quality_check_ids.state')
    def _compute_qc_count(self):
        for o in self:
            o.quality_check_count = len(o.quality_check_ids)
            o.quality_check_pending = len(o.quality_check_ids.filtered(
                lambda q: q.state == 'pending'))

    @api.depends('box_barcode')
    def _compute_actual_box(self):
        BoxSize = self.env['wms.box.size']
        for o in self:
            if o.box_barcode:
                box = BoxSize.search(
                    [('code', '=', o.box_barcode), ('active', '=', True)],
                    limit=1)
                o.actual_box_id = box
            else:
                o.actual_box_id = False

    @api.depends('line_ids.picked_qty', 'line_ids.product_id',
                 'line_ids.product_id.volume', 'line_ids.product_id.weight')
    def _compute_order_dims(self):
        for o in self:
            vol = 0.0
            wgt = 0.0
            for line in o.line_ids:
                qty = line.picked_qty or 0
                if qty and line.product_id:
                    if line.product_id.volume:
                        vol += line.product_id.volume * qty
                    if line.product_id.weight:
                        wgt += line.product_id.weight * qty
            o.order_vol_m3 = vol
            o.order_weight_kg = wgt

    @api.depends('actual_box_id', 'suggested_box_id', 'order_vol_m3',
                 'actual_box_id.volume', 'actual_box_id.unit_cost',
                 'actual_box_id.tape_cost_est', 'actual_box_id.bubble_cost_est',
                 'actual_box_id.total_material_cost')
    def _compute_box_analytics(self):
        for o in self:
            box = o.actual_box_id
            if box and o.order_vol_m3 > 0 and box.volume > 0:
                o.box_fill_pct = round(o.order_vol_m3 / box.volume * 100, 1)
            else:
                o.box_fill_pct = 0.0
            o.box_cost_est    = box.unit_cost       if box else 0.0
            o.tape_cost_est   = box.tape_cost_est   if box else 0.0
            o.bubble_cost_est = box.bubble_cost_est if box else 0.0
            o.total_pack_cost = box.total_material_cost if box else 0.0
            o.box_suggestion_hit = bool(
                box and o.suggested_box_id
                and box.id == o.suggested_box_id.id)

    @api.depends('line_ids.expected_qty', 'line_ids.picked_qty',
                 'line_ids.packed_qty')
    def _compute_totals(self):
        for order in self:
            order.expected_total = sum(order.line_ids.mapped('expected_qty'))
            order.picked_total = sum(order.line_ids.mapped('picked_qty'))
            order.packed_total = sum(order.line_ids.mapped('packed_qty'))
            order.all_picked = (order.expected_total > 0
                                and order.picked_total >= order.expected_total)
            order.all_packed = (order.picked_total > 0
                                and order.packed_total >= order.picked_total)

    @api.depends('create_date', 'sla_start_at', 'picked_at', 'packed_at',
                 'shipped_at', 'status', 'platform')
    def _compute_sla(self):
        Config = self.env['wms.sla.config'].sudo()
        now = fields.Datetime.now()
        for order in self:
            cfg = Config.get_for_platform(order.platform)
            # SLA starts from print pick list (sla_start_at), fallback to create_date
            base = order.sla_start_at or order.create_date or now
            order.sla_pick_deadline = base + timedelta(
                minutes=cfg.pick_sla_minutes if cfg else 120)
            pack_base = order.picked_at or order.sla_pick_deadline
            order.sla_pack_deadline = pack_base + timedelta(
                minutes=cfg.pack_sla_minutes if cfg else 60)
            ship_base = order.packed_at or order.sla_pack_deadline
            order.sla_ship_deadline = ship_base + timedelta(
                minutes=cfg.ship_sla_minutes if cfg else 240)

            if order.status in ('shipped', 'cancelled'):
                order.sla_status = 'done'
            else:
                if order.status in ('pending', 'picking'):
                    deadline = order.sla_pick_deadline
                elif order.status in ('picked', 'packing'):
                    deadline = order.sla_pack_deadline
                else:
                    deadline = order.sla_ship_deadline
                remaining = (deadline - now).total_seconds() / 60
                if remaining < 0:
                    order.sla_status = 'breached'
                elif remaining < 30:
                    order.sla_status = 'at_risk'
                else:
                    order.sla_status = 'on_track'

    @api.depends('sla_start_at', 'pick_start_at', 'picked_at',
                 'pack_start_at', 'packed_at', 'shipped_at', 'platform')
    def _compute_durations(self):
        SlaConfig = self.env['wms.sla.config'].sudo()
        for o in self:
            cfg = SlaConfig.get_for_platform(o.platform or 'default')

            def _net(a, b):
                if not a or not b:
                    return 0.0
                if cfg:
                    return cfg.net_working_minutes(a, b)
                return round((b - a).total_seconds() / 60, 1)

            base = o.sla_start_at or o.create_date
            o.wait_pick_min     = _net(base, o.pick_start_at)
            o.pick_duration_min = _net(o.pick_start_at, o.picked_at)
            o.wait_pack_min     = _net(o.picked_at, o.pack_start_at)
            o.pack_duration_min = _net(o.pack_start_at, o.packed_at)
            o.wait_ship_min     = _net(o.packed_at, o.shipped_at)
            o.ship_duration_min = 0
            o.total_duration_min = _net(base, o.shipped_at)

    @api.depends('line_ids.expected_qty')
    def _compute_difficulty(self):
        for o in self:
            o.items_count = sum(o.line_ids.mapped('expected_qty'))
            o.sku_count = len(o.line_ids)

    def action_print_picklist(self):
        """Admin prints pick list → starts SLA timer."""
        now = fields.Datetime.now()
        for order in self:
            if not order.sla_start_at:
                order.sla_start_at = now
                order.message_post(body=_('SLA timer started — Pick List printed.'))
        # Return print action
        return self.env.ref('kob_wms.action_report_wms_pick_list').report_action(self)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'wms.sales.order') or _('New')
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Stock integration helpers (strict — no best-effort)
    # ------------------------------------------------------------------
    def _ensure_picking_reserved(self):
        """Confirm + reserve the linked picking. Returns error string or None."""
        self.ensure_one()
        if not self.picking_id:
            return _('No delivery order linked.')
        picking = self.picking_id
        if picking.state == 'done':
            return None  # already done, OK
        if picking.state == 'cancel':
            return _('Delivery %s is cancelled.') % picking.name
        if picking.state == 'draft':
            picking.action_confirm()
        if picking.state in ('confirmed', 'waiting'):
            picking.action_assign()
        # Check reservation status — return error string, don't raise
        if picking.state != 'assigned':
            unreserved = picking.move_ids.filtered(
                lambda m: m.state not in ('assigned', 'done', 'cancel'))
            if unreserved:
                products = ', '.join(unreserved.mapped('product_id.display_name'))
                return _(
                    'Cannot reserve stock for %s. Products: %s. Location: %s'
                ) % (picking.name, products, picking.location_id.complete_name)
        return None

    def _get_demand_map(self):
        """Build demand map from stock.picking move_lines.
        Returns {product_id: {lot_id: remaining_demand_qty}}"""
        self.ensure_one()
        if not self.picking_id:
            return {}
        demand = {}
        for ml in self.picking_id.move_line_ids:
            pid = ml.product_id.id
            lot_id = ml.lot_id.id if ml.lot_id else 0
            reserved = ml.quantity_product_uom or 0
            done = ml.quantity or 0
            remaining = reserved - done
            if remaining <= 0:
                continue
            demand.setdefault(pid, {})[lot_id] = (
                demand.get(pid, {}).get(lot_id, 0) + remaining)
        return demand

    def _find_line_by_code(self, code):
        """Match a wms.sales.order.line by sku, default_code, or barcode (case-insensitive)."""
        code_upper = (code or "").strip().upper()
        def _match(l):
            if l.picked_qty >= l.expected_qty:
                return False
            if l.sku and l.sku.upper() == code_upper:
                return True
            if l.product_id:
                if l.product_id.default_code and l.product_id.default_code.upper() == code_upper:
                    return True
                if l.product_id.barcode and l.product_id.barcode == code:
                    return True
            return False
        return self.line_ids.filtered(_match)[:1]

    def _find_move_line(self, product, lot=None):
        """Find the exact stock.move.line to update for this product+lot.
        Strict match — returns None if nothing available."""
        if not self.picking_id:
            return None
        # Priority 1: match product + lot + has remaining demand
        if lot:
            ml = self.picking_id.move_line_ids.filtered(
                lambda m: m.product_id == product
                and m.lot_id == lot
                and (m.quantity or 0) < (m.quantity_product_uom or 0)
            )[:1]
            if ml:
                return ml
        # Priority 2: match product + no lot filter + has remaining demand
        ml = self.picking_id.move_line_ids.filtered(
            lambda m: m.product_id == product
            and (m.quantity or 0) < (m.quantity_product_uom or 0)
        )[:1]
        return ml or None

    def _resolve_lot(self, code, product):
        """Check if code is a Lot/Serial barcode for this product."""
        if not product or product.tracking == 'none':
            return None, False
        lot = self.env['stock.lot'].search([
            ('name', '=', code),
            ('product_id', '=', product.id),
        ], limit=1)
        return (lot, True) if lot else (None, False)

    def _get_fefo_lot(self, product, location):
        """Get the lot with earliest expiry date that has stock at location (FEFO)."""
        quants = self.env['stock.quant'].search([
            ('product_id', '=', product.id),
            ('location_id', '=', location.id),
            ('lot_id', '!=', False),
            ('quantity', '>', 0),
        ])
        if not quants:
            return None
        # Sort by lot expiration_date (earliest first), filter out expired
        lots_with_expiry = []
        for q in quants:
            lot = q.lot_id
            if lot.expiration_date:
                lots_with_expiry.append((lot.expiration_date, lot))
            else:
                lots_with_expiry.append((fields.Datetime.now() + timedelta(days=9999), lot))
        if not lots_with_expiry:
            return quants[0].lot_id  # fallback: any lot
        lots_with_expiry.sort(key=lambda x: x[0])  # earliest first
        return lots_with_expiry[0][1]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _auto_complete_service_lines(self, phase='pick'):
        """Auto-fill picked_qty / packed_qty for fee/service lines.
        Called after each physical item scan so service lines never block progress.
        phase='pick'  → set picked_qty = expected_qty
        phase='pack'  → set packed_qty = picked_qty (or expected_qty if 0)
        """
        for line in self.line_ids.filtered('is_service'):
            if phase == 'pick' and line.picked_qty < line.expected_qty:
                line.picked_qty = line.expected_qty
            elif phase == 'pack' and line.packed_qty < (line.picked_qty or line.expected_qty):
                line.packed_qty = line.picked_qty or line.expected_qty

    # ------------------------------------------------------------------
    # Count-lock helper
    # ------------------------------------------------------------------
    def _count_lock_msg(self):
        """Return error message if any picking location is being counted, else None."""
        self.ensure_one()
        if not self.picking_id:
            return None
        for move in self.picking_id.move_ids:
            for loc in (move.location_id, move.location_dest_id):
                if loc.counting_task_id:
                    return _(
                        '🔒 Location "%s" is currently being counted (Task: %s).\n'
                        'Please finish the count task before scanning this order.'
                    ) % (loc.display_name, loc.counting_task_id.name)
        return None

    # ------------------------------------------------------------------
    # Scan workflows
    # ------------------------------------------------------------------
    def scan_pick(self, sku, kob_worker_id=None):
        """Pick one unit. Checks: delivery assigned + qty. Logs errors."""
        self.ensure_one()
        if kob_worker_id:
            self = self.with_context(kob_worker_id=kob_worker_id)

        def _err(msg):
            self.pick_errors = (self.pick_errors or 0) + 1
            self._log_action('error_pick', sku or '', note=msg)
            return {'ok': False, 'error': msg}

        # 1. Must have delivery
        if not self.picking_id:
            return _err(_('No delivery linked to %s.') % (self.ref or self.name))

        # 1b. Count lock — block pick if source location is being counted
        lock_msg = self._count_lock_msg()
        if lock_msg:
            return _err(lock_msg)

        # 2. Ensure delivery is reserved (all items must be available)
        picking = self.picking_id
        if picking.state == 'cancel':
            return _err(_('Delivery %s is cancelled.') % picking.name)
        if picking.state == 'draft':
            picking.action_confirm()
        if picking.state in ('confirmed', 'waiting'):
            picking.action_assign()
        if picking.state != 'assigned':
            not_avail = picking.move_ids.filtered(
                lambda m: m.state not in ('assigned', 'done', 'cancel'))
            missing = ', '.join(
                '%s (%.0f)' % (m.product_id.default_code or m.product_id.display_name,
                               m.product_uom_qty)
                for m in not_avail)
            return _err(_(
                'Not all items available — cannot pick.\n'
                'Missing: %s\n'
                'Location: %s'
            ) % (missing, picking.location_id.complete_name))

        # 2b. Guard: picking is "assigned" but reserved qty may be 0 (e.g. after
        #     a cycle count adjustment unreserved the stock between order creation
        #     and scanning).  Re-verify actual reserved qty on move lines.
        total_reserved = sum(
            ml.quantity_product_uom for ml in picking.move_line_ids)
        if total_reserved == 0:
            return _err(_(
                '⚠️ สต็อคสำรองหาย (Delivery %s ไม่มี reserved qty)\n'
                'กรุณาตรวจสอบ Inventory → %s ว่ามีสินค้าพร้อมส่งหรือไม่'
            ) % (picking.name, picking.location_id.complete_name))

        # 3. Find WMS line (case-insensitive)
        line = self._find_line_by_code(sku)
        lot = None
        if not line:
            for l in self.line_ids.filtered(lambda x: x.picked_qty < x.expected_qty):
                if l.product_id and l.product_id.tracking != 'none':
                    found_lot, _ = self._resolve_lot(sku, l.product_id)
                    if found_lot:
                        line = l
                        lot = found_lot
                        break

        if not line:
            return _err(_('Invalid SKU or already fully picked: %s') % sku)

        product = line.product_id
        if not product:
            return _err(_('No product linked: %s') % line.sku)

        # 4. Check qty — don't exceed expected
        if line.picked_qty >= line.expected_qty:
            return _err(_('Already fully picked: %s (%d/%d)') % (
                sku, line.picked_qty, line.expected_qty))

        # 5. WMS only tracks picked_qty — does NOT touch delivery move_line
        # Odoo delivery handles qty/lot/reserve automatically
        # WMS validates completeness at close_box → then calls delivery validate
        line.picked_qty += 1
        # Auto-complete fee/service lines so they never block picking progress
        self._auto_complete_service_lines(phase='pick')
        now = fields.Datetime.now()
        if not self.picker_id:
            self.picker_id = self.env.user
        if not self.pick_start_at:
            self.pick_start_at = now
        self.status = 'picking'
        self._log_action('pick', sku, kob_user_id=self._context.get('kob_worker_id'))
        # Set WMS picker (kob.wms.user) if provided via context
        kob_wid = self._context.get('kob_worker_id')
        if kob_wid and not self.kob_picker_id:
            self.kob_picker_id = kob_wid

        if self.all_picked:
            self.status = 'picked'
            self.picked_at = now
        return {'ok': True}

    def scan_pack(self, sku, kob_worker_id=None):
        """Pack one unit. Logs errors. Sets pack_start_at."""
        self.ensure_one()
        kob_wid = kob_worker_id or self._context.get('kob_worker_id')

        def _err(msg):
            self.pack_errors = (self.pack_errors or 0) + 1
            self._log_action('error_pack', sku or '', note=msg, kob_user_id=kob_wid)
            return {'ok': False, 'error': msg}

        if self.status not in ('picked', 'packing'):
            return _err(_('Order must be picked first. Status: %s') % self.status)

        sku_upper = (sku or "").strip().upper()
        def _match(l):
            if l.packed_qty >= l.picked_qty:
                return False
            if l.sku and l.sku.upper() == sku_upper:
                return True
            if l.product_id:
                if l.product_id.default_code and l.product_id.default_code.upper() == sku_upper:
                    return True
                if l.product_id.barcode and l.product_id.barcode == sku:
                    return True
            return False

        line = self.line_ids.filtered(_match)[:1]
        if not line:
            return _err(_('Invalid SKU or already fully packed: %s') % sku)

        if line.packed_qty >= line.picked_qty:
            return _err(_('Already fully packed: %s (%d/%d)') % (
                sku, line.packed_qty, line.picked_qty))

        line.packed_qty += 1
        # Auto-complete fee/service lines so they never block packing progress
        self._auto_complete_service_lines(phase='pack')
        now = fields.Datetime.now()
        if not self.packer_id:
            self.packer_id = self.env.user
        if not self.pack_start_at:
            self.pack_start_at = now
        previous_status = self.status
        self.status = 'packing'
        self._log_action('pack', sku, kob_user_id=kob_wid)
        if kob_wid and not self.kob_packer_id:
            self.kob_packer_id = kob_wid
        # Outgoing QC: create pending checks on first transition into packing
        if previous_status != 'packing':
            self.env['wms.quality.check'].sudo().register_for_order(self)
        return {'ok': True, 'all_packed': self.all_packed}

    def close_box(self, box_barcode=False, box_size=False, kob_worker_id=None):
        """Select box size → validate picking (cut stock) → auto invoice → print AWB."""
        self.ensure_one()
        if not self.all_packed:
            return {'ok': False, 'error': _('Not all items are packed yet.')}
        # Outgoing QC gate — block if any pending or failed checks
        pending = self.quality_check_ids.filtered(lambda q: q.state == 'pending')
        if pending:
            return {'ok': False, 'error': _(
                '🎯 Outgoing QC required — %d pending checks on: %s'
            ) % (len(pending),
                 ', '.join(pending.mapped('product_id.default_code')[:5]))}
        failed = self.quality_check_ids.filtered(lambda q: q.state == 'failed')
        if failed:
            return {'ok': False, 'error': _(
                '❌ Pack blocked — %d failed QC checks. Resolve defects first.'
            ) % len(failed)}

        # 0. Count lock — block BEFORE setting any status or posting invoice
        lock_msg = self._count_lock_msg()
        if lock_msg:
            return {'ok': False, 'error': lock_msg}

        if box_size:
            self.box_barcode = box_size
        elif box_barcode:
            self.box_barcode = box_barcode

        self._log_action('box', self.box_barcode or '', kob_user_id=kob_worker_id)

        # 1. Validate stock.picking → ตัด stock จริง
        stock_errors = self._validate_picking()

        if stock_errors:
            # Stock failed — do NOT set packed status, do NOT post invoice
            # Return ok: False so pack screen shows the error clearly
            return {'ok': False, 'error': stock_errors[0]}

        # 2. Stock OK → mark packed + auto invoice
        self.status = 'packed'
        self.packed_at = fields.Datetime.now()
        self._auto_create_invoice()

        # 3. Return AWB print action
        awb_action = None
        if self.awb:
            awb_action = {
                'report': 'kob_wms.report_wms_awb_label',
                'id': self.id,
            }

        return {
            'ok': True,
            'awb_action': awb_action,
        }

    def select_box_and_close(self, box_size, kob_worker_id=None):
        """Called from Pack screen: select box → close → returns print AWB info."""
        self.ensure_one()
        if not self.all_packed:
            return {'ok': False, 'error': _('Not all items are packed yet.')}
        return self.close_box(box_size=box_size, kob_worker_id=kob_worker_id)

    def _validate_picking(self):
        """Set move_line done qty = reserved qty, then validate delivery.

        Auto-retry strategy (no manual button needed):
          Attempt 1 — confirm + assign + set done=reserved + button_validate
          Attempt 2 — if state != done: unreserve → re-assign → set done=reserved
                      → button_validate again (handles stale reservation after
                        count-adjustment or external stock change)
          Failure   — clear error pointing supervisor to Inventory directly.

        Odoo 18 field names on stock.move.line:
          ml.quantity_product_uom = reserved qty
          ml.quantity             = done qty (set before button_validate)
          ml.picked               = True signals line ready to validate
        """
        errors = []
        for order in self:
            picking = order.picking_id

            # ── No picking ───────────────────────────────────────────────
            if not picking:
                msg = _('No delivery order linked — stock was NOT deducted. '
                        'Assign a Delivery Order and validate manually in Inventory.')
                errors.append(msg)
                order.message_post(body='⚠️ %s' % msg)
                continue

            # ── Already done ─────────────────────────────────────────────
            if picking.state == 'done':
                continue

            # ── Cancelled ────────────────────────────────────────────────
            if picking.state == 'cancel':
                msg = _('Delivery %s is cancelled — stock was NOT deducted.') % picking.name
                errors.append(msg)
                order.message_post(body='⚠️ %s' % msg)
                continue

            try:
                # ── Ensure picking is confirmed + reserved ────────────────
                if picking.state == 'draft':
                    picking.action_confirm()
                if picking.state in ('confirmed', 'waiting'):
                    picking.action_assign()

                # ── Attempt 1 ────────────────────────────────────────────
                ok = order._picking_attempt(picking)

                # ── Attempt 2: unreserve → re-assign → retry ─────────────
                if not ok:
                    picking.invalidate_recordset()   # flush ORM cache first
                    if picking.state == 'done':
                        ok = True
                    else:
                        picking.do_unreserve()
                        picking.action_assign()
                        ok = order._picking_attempt(picking)

                if ok:
                    order.message_post(body='✅ Stock validated: %s' % picking.name)
                else:
                    picking.invalidate_recordset()
                    msg = _(
                        '❌ Validation incomplete — delivery %s is still "%s".\n'
                        'กรุณาไปที่ Inventory → Transfers → %s แล้วกด Validate โดยตรง'
                    ) % (picking.name, picking.state, picking.name)
                    errors.append(msg)
                    order.message_post(body='⚠️ %s' % msg)

            except Exception as exc:
                msg = str(exc)
                errors.append(msg)
                order.message_post(body=_(
                    '❌ Stock validation error: %s\n'
                    'กรุณาไปที่ Inventory → Transfers → %s แล้ว Validate โดยตรง'
                ) % (msg, picking.name))

        return errors

    def _picking_attempt(self, picking):
        """Single validation attempt: set done=reserved → button_validate.

        Returns True if picking.state == 'done' after the attempt.
        Called by _validate_picking(); safe to call twice (idempotent).
        """
        # Guard: if all reserved qty = 0 after assign, stock is truly gone
        total_reserved = sum(ml.quantity_product_uom for ml in picking.move_line_ids)
        if total_reserved == 0 and picking.move_line_ids:
            return False   # will trigger attempt 2 (unreserve → re-assign)

        # Set done qty = reserved qty
        # Use quantity_product_uom (reserved per line) NOT move demand
        # to avoid over-counting when a move has multiple lot lines.
        for ml in picking.move_line_ids:
            reserved = ml.quantity_product_uom or 0
            if reserved > 0:
                ml.quantity = reserved
            if hasattr(ml, 'picked'):
                ml.picked = True

        # skip_immediate → bypass "Set Quantities" wizard
        # skip_backorder → bypass "Create Backorder?" wizard
        picking.with_context(
            skip_immediate=True,
            skip_backorder=True,
            picking_ids_not_to_backorder=picking.ids,
        ).button_validate()

        picking.invalidate_recordset()
        return picking.state == 'done'

    def _auto_create_invoice(self):
        """Auto create and post invoice from the linked sale.order."""
        for order in self:
            so = order.sale_order_id
            if not so:
                continue
            # Skip if invoice already exists
            if so.invoice_ids.filtered(lambda i: i.state != 'cancel'):
                continue
            try:
                # Create invoice from SO (uses delivery qty if policy=delivery)
                invoice = so._create_invoices()
                if invoice:
                    # Auto post (confirm) the invoice
                    invoice.action_post()
                    order.message_post(
                        body=_('Invoice created and posted: %s') % invoice.name)
            except Exception as exc:
                order.message_post(
                    body=_('Auto-invoice warning: %s') % exc)

    def action_fix_packed_status(self):
        """Supervisor: fix WMS orders where picking is 'done' but status not updated.

        Scenario B only — picking already validated externally (e.g. via Inventory UI),
        WMS status still shows wrong state. Auto-retry validation is built into
        _validate_picking() so this button covers only the manual-fix edge case.
        """
        fixed, skipped = [], []
        for order in self:
            picking = order.picking_id
            if picking and picking.state == 'done':
                if order.status not in ('packed', 'shipped', 'cancelled'):
                    order.status = 'packed'
                    if not order.packed_at:
                        order.packed_at = fields.Datetime.now()
                    # Create invoice if missing
                    so = order.sale_order_id
                    if so and not so.invoice_ids.filtered(lambda i: i.state == 'posted'):
                        order._auto_create_invoice()
                    order.message_post(body='✅ Status synced: picking was already done.')
                    fixed.append(order.name)
                else:
                    skipped.append(order.name)
            else:
                skipped.append(order.name)

        msg = []
        if fixed:   msg.append('✅ Fixed: %s' % ', '.join(fixed))
        if skipped: msg.append('⏭ Skipped (not applicable): %s' % ', '.join(skipped))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Fix Packed Status'),
                'message': '\n'.join(msg) or 'Nothing to fix.',
                'type': 'success',
                'sticky': False,
            },
        }

    def action_ship(self):
        """Mark as shipped + create scan item + auto add to active batch."""
        for order in self:
            if order.status != 'packed':
                return {'ok': False, 'error': _('Order %s is not packed.') % order.name}

            order.status = 'shipped'
            order.shipped_at = fields.Datetime.now()
            order.shipper_id = self.env.user
            order._log_action('ship', order.awb or '')

            # Create scan item — only when courier is assigned
            # (courier_id is required on wms.scan.item)
            scan_item = None
            if order.awb and order.courier_id:
                scan_item = self.env['wms.scan.item'].create({
                    'barcode': order.awb,
                    'courier_id': order.courier_id.id,
                    'order_ref': order.ref or order.name,
                    'shop_name': order.platform or '',
                    'sales_order_id': order.id,
                })

            # Auto-add to active scanning batch (or create one)
            # Only when scan item was created (i.e. courier is assigned)
            if scan_item:
                batch = self.env['wms.courier.batch'].search([
                    ('state', '=', 'scanning'),
                    ('courier_id', '=', order.courier_id.id),
                ], limit=1)
                if not batch:
                    batch = self.env['wms.courier.batch'].create({
                        'state': 'scanning',
                        'courier_id': order.courier_id.id,
                    })
                scan_item.batch_id = batch.id

        # Navigate back to Outbound Queue after shipping
        action = self.env.ref('kob_wms.action_wms_outbound_screen').sudo().read()[0]
        action['target'] = 'main'
        return action

    def set_awb_and_ship(self, awb):
        """Set AWB barcode then ship. Called from Outbound screen."""
        self.ensure_one()
        if self.status != 'packed':
            return {'ok': False, 'error': _('Order %s is not packed.') % self.name}
        self.awb = awb
        return self.action_ship()

    # ------------------------------------------------------------------
    # Auto-Box Sizing
    # ------------------------------------------------------------------
    def get_recommended_box(self):
        """Recommend the smallest box that fits all order items.

        Algorithm:
        1.  Sum product.volume * picked_qty for every line.
            (product.volume is stored in m³ in Odoo.)
        2.  Apply 25 % packing buffer.
        3.  Find the smallest wms.box.size with volume (m³) >= required.
        4.  If no product volumes are set, fall back to item-count heuristic.
        """
        self.ensure_one()

        lines = self.env['wms.sales.order.line'].search([('order_id', '=', self.id)])
        total_volume_m3 = 0.0
        total_weight_kg = 0.0
        has_dims = False

        for line in lines:
            qty = line.picked_qty or 1
            if line.product_id:
                if line.product_id.volume:
                    total_volume_m3 += line.product_id.volume * qty
                    has_dims = True
                if line.product_id.weight:
                    total_weight_kg += line.product_id.weight * qty

        BoxSize = self.env['wms.box.size']

        # ── No dimensions available → heuristic by item count ──────────
        if not has_dims or total_volume_m3 <= 0:
            n_items = sum(l.picked_qty or 1 for l in lines)
            if n_items <= 2:
                code_fallback = 'B'
            elif n_items <= 5:
                code_fallback = 'C'
            elif n_items <= 10:
                code_fallback = '2C'
            else:
                code_fallback = 'L'
            box = BoxSize.search([('code', '=', code_fallback), ('active', '=', True)], limit=1) \
                or BoxSize.search([('active', '=', True)], order='volume asc', limit=1)
            if box:
                self.sudo().write({'suggested_box_id': box.id})
                return {
                    'ok': True,
                    'box_code': box.code,
                    'box_label': box.name_get()[0][1],
                    'box_volume_cm3': box.volume_cm3,
                    'total_volume_cm3': 0,
                    'basis': 'item_count',
                    'note': _('No product dimensions set — estimated from item count (%d items)') % n_items,
                }
            return {'ok': False, 'error': _('No box sizes configured. Please add box sizes in WMS settings.')}

        # ── Volume-based recommendation ────────────────────────────────
        required_m3 = total_volume_m3 * 1.25  # 25 % packing buffer

        box = BoxSize.search(
            [('active', '=', True), ('volume', '>=', required_m3)],
            order='volume asc',
            limit=1,
        )
        if not box:
            # Everything is too big — return the largest box
            box = BoxSize.search([('active', '=', True)], order='volume desc', limit=1)

        if not box:
            return {'ok': False, 'error': _('No box sizes configured.')}

        # Weight warning (informational)
        weight_note = ''
        if box.weight_limit and total_weight_kg > box.weight_limit:
            weight_note = _(' ⚠ Weight %.1f kg exceeds box limit %.1f kg') % (
                total_weight_kg, box.weight_limit)

        self.sudo().write({'suggested_box_id': box.id})
        return {
            'ok': True,
            'box_code':        box.code,
            'box_label':       box.name_get()[0][1],
            'box_volume_cm3':  box.volume_cm3,
            'total_volume_cm3': round(total_volume_m3 * 1_000_000, 2),
            'required_volume_cm3': round(required_m3 * 1_000_000, 2),
            'total_weight_kg': round(total_weight_kg, 3),
            'basis': 'volume',
            'note': weight_note,
        }

    def action_cancel(self):
        self.write({'status': 'cancelled'})

    def action_open_cancel_return(self):
        """Open Cancel / Return wizard for this order."""
        self.ensure_one()
        wizard = self.env['wms.cancel.return.wizard'].create({'order_id': self.id})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'wms.cancel.return.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_list_ship(self, scanned_val=None):
        """Ship from outbound list scan bar. Returns JSON dict (not an act_window).

        scanned_val — the raw barcode the worker scanned.  If the order has no
        AWB yet and scanned_val looks like a courier tracking number (not a WMS
        order name), it is saved as the AWB before shipping.
        """
        self.ensure_one()
        if self.status != 'packed':
            return {
                'ok': False,
                'error': _('Not packed yet (status: %s)') % self.status,
            }
        # Auto-fill AWB from the scanned barcode when it is not yet set.
        # Skip obvious non-AWB values (WMS order names start with "SO/").
        if scanned_val and not self.awb:
            if not scanned_val.upper().startswith('SO/'):
                self.awb = scanned_val

        result = self.action_ship()
        # action_ship returns {ok: False, error: ...} on error, else an act_window dict
        if isinstance(result, dict) and result.get('ok') is False:
            return result
        return {'ok': True, 'name': self.name, 'awb': self.awb or ''}

    # ------------------------------------------------------------------
    # Scan wizard launchers (form buttons)
    # ------------------------------------------------------------------
    def _open_scan_wizard(self, mode):
        self.ensure_one()
        return self.env['wms.scan.wizard'].action_open_from_order(self.id, mode)

    def action_open_scan_pick(self):
        return self._open_scan_wizard('pick')

    def action_open_scan_pack(self):
        return self._open_scan_wizard('pack')

    def action_open_scan_box(self):
        return self._open_scan_wizard('box')

    def action_scan_item(self, barcode, kob_worker_id=None):
        """Direct scan from the form view scan bar.
        Routes to scan_pick or scan_pack based on current status.
        Returns a JSON-friendly dict: {ok, msg, all_done, new_status} or {ok, error}.
        """
        self.ensure_one()
        barcode = (barcode or '').strip()
        if not barcode:
            return {'ok': False, 'error': _('Empty barcode')}

        status_before = self.status
        if status_before in ('pending', 'picking'):
            ctx = dict(self._context, kob_worker_id=kob_worker_id) if kob_worker_id else self._context
            result = self.with_context(ctx).scan_pick(barcode)
        elif status_before in ('picked', 'packing'):
            result = self.scan_pack(barcode, kob_worker_id=kob_worker_id)
        else:
            return {'ok': False, 'error': _('Cannot scan in status: %s') % self.status}

        if not result.get('ok'):
            return result  # already has 'error' key from scan_pick/scan_pack

        # Build a progress message from the matched line (quantities are now updated)
        b_up = barcode.upper()
        line = self.line_ids.filtered(
            lambda l: (l.sku or '').upper() == b_up
            or (l.product_id.barcode or '') == barcode
            or (l.product_id.default_code or '').upper() == b_up
        )[:1]

        if status_before in ('pending', 'picking'):
            msg = (_('%s: %d/%d picked') % (line.sku, int(line.picked_qty), int(line.expected_qty))
                   if line else _('Picked'))
            all_done = self.all_picked
            phase = 'pick'
        else:
            msg = (_('%s: %d/%d packed') % (line.sku, int(line.packed_qty), int(line.picked_qty))
                   if line else _('Packed'))
            all_done = self.all_packed
            phase = 'pack'

        return {
            'ok': True,
            'msg': msg,
            'all_done': bool(all_done),
            'phase': phase,           # 'pick' | 'pack'
            'new_status': self.status,
        }

    def action_get_close_box_data(self):
        """Return box suggestion + all available boxes for the close box dialog."""
        self.ensure_one()
        suggestion = self.get_recommended_box()
        boxes = self.env['wms.box.size'].search([('active', '=', True)], order='volume asc')
        return {
            'ok': True,
            'suggestion': suggestion,
            'boxes': [{'code': b.code, 'label': b.display_name} for b in boxes],
            'order_name': self.name,
        }

    def action_import_from_sale_order(self):
        """Create lines from the linked sale.order (or stock.picking)."""
        self.ensure_one()
        if not (self.sale_order_id or self.picking_id):
            raise UserError(_('Link a Sale Order or Delivery Order first.'))
        self.line_ids.unlink()
        lines = []
        source_picking = self.picking_id
        if self.sale_order_id:
            if not self.ref:
                self.ref = self.sale_order_id.name
            if not self.partner_id:
                self.partner_id = self.sale_order_id.partner_id
                self.customer = self.sale_order_id.partner_id.name
            for sol in self.sale_order_id.order_line:
                if sol.product_id and sol.product_uom_qty > 0:
                    lines.append({
                        'order_id': self.id,
                        'product_id': sol.product_id.id,
                        'product_name': sol.product_id.display_name,
                        'sku': sol.product_id.default_code or sol.product_id.barcode or '',
                        'expected_qty': int(sol.product_uom_qty),
                    })
            if not source_picking:
                source_picking = self.sale_order_id.picking_ids[:1]
                if source_picking:
                    self.picking_id = source_picking
        elif source_picking:
            if not self.ref:
                self.ref = source_picking.name
            if not self.partner_id:
                self.partner_id = source_picking.partner_id
                self.customer = source_picking.partner_id.name
            for ml in source_picking.move_ids:
                if ml.product_id and ml.product_uom_qty > 0:
                    lines.append({
                        'order_id': self.id,
                        'product_id': ml.product_id.id,
                        'product_name': ml.product_id.display_name,
                        'sku': ml.product_id.default_code or ml.product_id.barcode or '',
                        'expected_qty': int(ml.product_uom_qty),
                    })
        if lines:
            self.env['wms.sales.order.line'].create(lines)
        return True

    def _log_action(self, action, code='', note='', kob_user_id=None):
        self.env['wms.activity.log'].create({
            'user_id': self.env.user.id,
            'kob_user_id': kob_user_id or False,
            'action': action,
            'ref': self.ref or self.name,
            'code': code,
            'sales_order_id': self.id,
            'note': note,
        })

    # ------------------------------------------------------------------
    # Demo KPI seed — assign WMS workers to existing orders
    # ------------------------------------------------------------------
    @api.model
    def action_seed_demo_workers(self):
        """
        Spread kob.wms.user workers across existing orders and fill in
        missing timestamps so KPI / SLA views show realistic sample data.
        Call from: All Orders list → Actions → Seed Demo Workers.
        """
        import random
        from datetime import datetime, timedelta

        KobUser = self.env['kob.wms.user'].sudo()
        pickers = KobUser.search([
            ('role', 'in', ['picker', 'admin', 'supervisor']),
            ('is_active', '=', True),
        ])
        packers = KobUser.search([
            ('role', 'in', ['packer', 'admin', 'supervisor']),
            ('is_active', '=', True),
        ])

        if not pickers:
            pickers = KobUser.search([('is_active', '=', True)])
        if not packers:
            packers = pickers

        orders = self.sudo().search(
            [('status', 'not in', ['cancelled'])],
            order='id asc',
        )

        now = fields.Datetime.now()
        updated = 0

        for idx, order in enumerate(orders):
            picker = pickers[idx % len(pickers)]
            packer = packers[idx % len(packers)]

            # Random base time: 0–14 days ago, between 08:00–11:00
            days_ago = random.randint(0, 14)
            hour_offset = random.randint(0, 180)  # minutes after 08:00
            base = (now - timedelta(days=days_ago)).replace(
                hour=8, minute=0, second=0, microsecond=0
            ) + timedelta(minutes=hour_offset)

            vals = {
                'kob_picker_id': picker.id,
                'kob_packer_id': packer.id,
            }

            status = order.status
            # SLA start (picklist printed)
            if not order.sla_start_at and status != 'pending':
                vals['sla_start_at'] = base

            sla_base = order.sla_start_at or base

            if status in ('picking', 'picked', 'packing', 'packed', 'shipped'):
                if not order.pick_start_at:
                    vals['pick_start_at'] = sla_base + timedelta(
                        minutes=random.randint(3, 15))

            pick_start = order.pick_start_at or vals.get('pick_start_at', sla_base)

            if status in ('picked', 'packing', 'packed', 'shipped'):
                if not order.picked_at:
                    vals['picked_at'] = pick_start + timedelta(
                        minutes=random.randint(20, 55))

            picked_at = order.picked_at or vals.get('picked_at', pick_start + timedelta(minutes=30))

            if status in ('packing', 'packed', 'shipped'):
                if not order.pack_start_at:
                    vals['pack_start_at'] = picked_at + timedelta(
                        minutes=random.randint(1, 8))

            pack_start = order.pack_start_at or vals.get('pack_start_at', picked_at + timedelta(minutes=3))

            if status in ('packed', 'shipped'):
                if not order.packed_at:
                    vals['packed_at'] = pack_start + timedelta(
                        minutes=random.randint(8, 25))

            packed_at = order.packed_at or vals.get('packed_at', pack_start + timedelta(minutes=15))

            if status == 'shipped':
                if not order.shipped_at:
                    vals['shipped_at'] = packed_at + timedelta(
                        minutes=random.randint(5, 30))

            order.sudo().write(vals)
            updated += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': 'Assigned demo workers to %d orders. Refresh KPI view.' % updated,
                'type': 'success',
                'sticky': False,
            },
        }


class WmsSalesOrderLine(models.Model):
    _name = 'wms.sales.order.line'
    _description = 'WMS Sales Order Line'
    _order = 'sequence, id'

    order_id = fields.Many2one('wms.sales.order', string='Order',
                               required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    sku = fields.Char(string='SKU / Barcode', required=True)
    product_name = fields.Char(string='Product Name')
    product_id = fields.Many2one('product.product', string='Product')
    expected_qty = fields.Integer(string='Expected', default=1)
    picked_qty = fields.Integer(string='Picked', default=0)
    packed_qty = fields.Integer(string='Packed', default=0)
    product_barcode = fields.Char(
        related='product_id.barcode', string='Barcode', readonly=True,
        help='EAN/UPC barcode from product master — this is what the scanner reads.',
    )
    remaining_pick = fields.Integer(compute='_compute_remaining', store=False)
    remaining_pack = fields.Integer(compute='_compute_remaining', store=False)

    # True for service/fee lines that should NOT require scanning
    is_service = fields.Boolean(
        compute='_compute_is_service', store=True,
        string='Fee / Service Line',
        help='Auto-detected: service products or logistics/fee SKUs skip scanning.',
    )

    # Keywords in SKU or product name that identify a fee/service line
    _FEE_KEYWORDS = ('logistic', 'logistics', 'fee', 'fees', 'freight',
                     'shipping', 'delivery fee', 'rev-', 'service')

    @api.depends('product_id', 'product_id.type', 'sku', 'product_name')
    def _compute_is_service(self):
        for line in self:
            if line.product_id and line.product_id.type == 'service':
                line.is_service = True
            else:
                haystack = ' '.join(filter(None, [
                    (line.sku or '').lower(),
                    (line.product_name or '').lower(),
                ]))
                line.is_service = any(kw in haystack for kw in self._FEE_KEYWORDS)

    @api.depends('expected_qty', 'picked_qty', 'packed_qty')
    def _compute_remaining(self):
        for line in self:
            line.remaining_pick = max(line.expected_qty - line.picked_qty, 0)
            line.remaining_pack = max(line.picked_qty - line.packed_qty, 0)
