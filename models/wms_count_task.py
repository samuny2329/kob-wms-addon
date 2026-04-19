from odoo import models, fields, api, _
from odoo.exceptions import UserError


class WmsCountTask(models.Model):
    _name = 'wms.count.task'
    _description = 'WMS Count Task (per location)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, id'

    name = fields.Char(string='Reference', required=True, copy=False,
                       readonly=True, default=lambda self: _('New'))
    sequence = fields.Integer(default=10)
    session_id = fields.Many2one('wms.count.session', string='Session',
                                 required=True, ondelete='cascade')
    rack_id = fields.Many2one('wms.rack', string='Rack')
    zone_id = fields.Many2one('wms.zone', string='Zone',
                              related='rack_id.zone_id', store=True)
    location_id = fields.Many2one('stock.location', string='Location')
    product_id = fields.Many2one('product.product', string='Product',
                                 index=True,
                                 help='Set for ABC/SKU-specific tasks. '
                                      'When set, only this product is counted.')
    assigned_user_id = fields.Many2one('res.users', string='Assigned To',
                                       tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('assigned', 'Assigned'),
        ('counting', 'Counting'),
        ('submitted', 'Submitted'),
        ('verified', 'Verified'),
        ('approved', 'Approved'),
    ], string='State', default='draft', tracking=True)
    entry_ids = fields.One2many('wms.count.entry', 'task_id', string='Entries')
    entry_count = fields.Integer(string='Entry Count',
                                 compute='_compute_entry_count')
    expected_qty = fields.Float(string='Expected Qty')
    counted_qty = fields.Float(string='Counted Qty',
                               compute='_compute_counted_qty', store=True)
    variance = fields.Float(string='Variance',
                            compute='_compute_counted_qty', store=True)
    company_id = fields.Many2one('res.company', related='session_id.company_id',
                                 store=True)

    # ── Verification fields ────────────────────────────────────
    verified_by = fields.Many2one('res.users', string='Verified By',
                                   tracking=True)
    verified_date = fields.Datetime(string='Verified Date')
    adjustment_ids = fields.One2many(
        'wms.count.adjustment', 'task_id', string='Adjustments')
    adjustment_count = fields.Integer(
        string='Adjustments', compute='_compute_adjustment_count')

    @api.depends('entry_ids')
    def _compute_entry_count(self):
        for task in self:
            task.entry_count = len(task.entry_ids)

    @api.depends('entry_ids.qty', 'expected_qty')
    def _compute_counted_qty(self):
        for task in self:
            total = sum(task.entry_ids.mapped('qty'))
            task.counted_qty = total
            task.variance = total - task.expected_qty

    @api.depends('adjustment_ids')
    def _compute_adjustment_count(self):
        for task in self:
            task.adjustment_count = len(task.adjustment_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'wms.count.task') or _('New')
        return super().create(vals_list)

    def action_assign(self):
        self.write({'state': 'assigned'})

    def action_start_counting(self):
        self.write({'state': 'counting'})

    def action_submit(self):
        for task in self:
            if not task.entry_ids:
                raise UserError(_(
                    'Cannot submit task %s — no scan entries.') % task.name)
        self.write({'state': 'submitted'})

    def action_verify(self):
        """Supervisor verifies the count and creates adjustment records."""
        Adjustment = self.env['wms.count.adjustment']
        for task in self:
            if task.state != 'submitted':
                raise UserError(_(
                    'Task %s must be submitted before verification.') % task.name)
            # Create adjustment lines (snapshots system qty)
            adjustments = Adjustment._create_from_task(task)
            task.write({
                'state': 'verified',
                'verified_by': self.env.uid,
                'verified_date': fields.Datetime.now(),
            })
            task.message_post(body=_(
                'Verified by %s. %d adjustment line(s) created.')
                % (self.env.user.name, len(adjustments)))

    def action_request_recount(self):
        """Supervisor sends task back to counting (variance too high)."""
        for task in self:
            if task.state != 'submitted':
                raise UserError(_('Can only request recount for submitted tasks.'))
            # Clear previous entries
            task.entry_ids.unlink()
            task.write({'state': 'counting'})
            task.message_post(body=_(
                'Recount requested by %s. Previous entries cleared.')
                % self.env.user.name)

    def action_approve(self):
        """Manager approves — triggers approval on linked adjustments."""
        for task in self:
            if task.state != 'verified':
                raise UserError(_(
                    'Task %s must be verified before approval.') % task.name)
            pending = task.adjustment_ids.filtered(
                lambda a: a.state == 'pending')
            if pending:
                pending.action_approve()
            task.write({'state': 'approved'})
            task.message_post(body=_(
                'Approved by %s. %d adjustment(s) approved.')
                % (self.env.user.name, len(pending)))

    # ------------------------------------------------------------------
    # Mobile / Handheld Count Screen API
    # ------------------------------------------------------------------
    @api.model
    def get_my_count_tasks(self, kob_user_id=None):
        """Return count tasks for the current worker (count screen API).

        Returns a list of task dicts with full location breadcrumb and
        expected product list — enough for the OWL count screen to render
        without further RPC calls.
        """
        domain = [('state', 'in', ('assigned', 'counting'))]
        if kob_user_id:
            kob = self.env['kob.wms.user'].browse(int(kob_user_id))
            res_user = kob.res_user_id
            if res_user:
                # Show tasks explicitly assigned to this worker OR
                # broadcast tasks (no assigned_user = auto-generated, available to all)
                domain += ['|',
                           ('assigned_user_id', '=', res_user.id),
                           ('assigned_user_id', '=', False)]
        else:
            domain += ['|',
                       ('assigned_user_id', '=', self.env.uid),
                       ('assigned_user_id', '=', False)]

        tasks = self.search(domain, order='zone_id, rack_id, id')
        result = []
        for t in tasks:
            # Build location breadcrumb
            zone_name = t.zone_id.name or ''
            zone_code = t.zone_id.code or ''
            rack_name = t.rack_id.name or ''
            loc_name  = t.location_id.complete_name or t.location_id.name or ''

            # Expected products from stock.quant at this location.
            # If the task has a specific product_id (ABC/SKU tasks), only load that product.
            products = []
            if t.location_id:
                quant_domain = [
                    ('location_id', '=', t.location_id.id),
                    ('quantity', '>', 0),
                ]
                if t.product_id:
                    quant_domain.append(('product_id', '=', t.product_id.id))
                quants = self.env['stock.quant'].sudo().search(quant_domain)
                seen = set()
                for q in quants:
                    pid = q.product_id.id
                    if pid not in seen:
                        seen.add(pid)
                        products.append({
                            'product_id':   pid,
                            'product_name': q.product_id.display_name,
                            'product_code': q.product_id.default_code or '',
                            'barcode':      q.product_id.barcode or '',
                        })

            result.append({
                'id':           t.id,
                'name':         t.name,
                'state':        t.state,
                'zone_name':    zone_name,
                'zone_code':    zone_code,
                'rack_name':    rack_name,
                'location_id':  t.location_id.id if t.location_id else False,
                'location_name': loc_name,
                'product_count': len(products),
                'products':     products,
                'session_name': t.session_id.name if t.session_id else '',
                # For SKU-specific tasks (ABC): the single target product
                'target_product_id':   t.product_id.id if t.product_id else False,
                'target_product_name': t.product_id.display_name if t.product_id else '',
                'target_product_code': t.product_id.default_code if t.product_id else '',
            })
        return result

    def start_counting(self):
        """Called when worker taps a task in Count (F5).

        1. Locks the task's location — blocks all stock.picking validations.
        2. Takes a snapshot of stock.quant (reference for variance calc).
        3. Transitions task → 'counting', claims it for the current worker.

        Returns {'ok': True, 'quants': [...]} on success, or
                {'ok': False, 'error': '...'} on failure.
        Quant format: same as the old get_expected_quants().
        """
        self.ensure_one()
        if self.state not in ('assigned', 'counting'):
            return {'ok': False, 'error': _('Task is not in an assignable state.')}

        location = self.location_id
        if not location:
            return {'ok': False, 'error': _('Task has no location assigned.')}

        # Block if another task from a DIFFERENT session holds this location.
        # Tasks in the SAME session share the location lock — allowed.
        existing = location.counting_task_id
        if existing and existing != self:
            same_session = (
                existing.session_id and
                self.session_id and
                existing.session_id == self.session_id
            )
            if not same_session:
                return {
                    'ok': False,
                    'error': _('Location "%s" is already locked by task %s (session %s). '
                               'Finish that session first.')
                             % (location.display_name,
                                existing.name,
                                existing.session_id.name if existing.session_id else '?'),
                }
            # Same session — proceed without re-locking (already locked)

        # ── Lock location (set to this task; same-session tasks share it) ─
        if not location.counting_task_id:
            location.sudo().counting_task_id = self

        # ── Take snapshot (clear old one first for re-entry) ─────────
        Snapshot = self.env['wms.count.snapshot'].sudo()
        Snapshot.search([('task_id', '=', self.id)]).unlink()

        snap_domain = [('location_id', '=', location.id)]
        if self.product_id:
            snap_domain.append(('product_id', '=', self.product_id.id))
        quants = self.env['stock.quant'].sudo().search(
            snap_domain, order='product_id, lot_id')

        for q in quants:
            Snapshot.create({
                'task_id':    self.id,
                'product_id': q.product_id.id,
                'lot_id':     q.lot_id.id if q.lot_id else False,
                'location_id': location.id,
                'qty':        q.quantity,
            })

        # ── Transition ───────────────────────────────────────────────
        if self.state == 'assigned':
            self.state = 'counting'
        if not self.assigned_user_id:
            self.assigned_user_id = self.env.uid

        # ── Return snapshot as quant list ────────────────────────────
        result = []
        for snap in Snapshot.search([('task_id', '=', self.id)],
                                     order='product_id, lot_id'):
            lot = snap.lot_id
            result.append({
                'product_id':   snap.product_id.id,
                'product_name': snap.product_id.display_name,
                'product_code': snap.product_id.default_code or '',
                'barcode':      snap.product_id.barcode or '',
                'lot_id':       lot.id if lot else False,
                'lot_name':     lot.name if lot else '',
                'lot_ref':      lot.ref if lot else '',
                'expiry_date':  str(lot.expiration_date.date()
                                    if hasattr(lot.expiration_date, 'date')
                                    else lot.expiration_date)
                                if lot and lot.expiration_date else '',
                'expected_qty': snap.qty,
            })
        return {'ok': True, 'quants': result}

    def get_expected_quants(self):
        """Legacy helper — kept for backward compat; prefer start_counting()."""
        self.ensure_one()
        if not self.location_id:
            return []
        quants = self.env['stock.quant'].sudo().search([
            ('location_id', '=', self.location_id.id),
        ], order='product_id, lot_id')
        result = []
        for q in quants:
            lot = q.lot_id
            result.append({
                'product_id':   q.product_id.id,
                'product_name': q.product_id.display_name,
                'product_code': q.product_id.default_code or '',
                'barcode':      q.product_id.barcode or '',
                'lot_id':       lot.id if lot else False,
                'lot_name':     lot.name if lot else '',
                'lot_ref':      lot.ref if lot else '',
                'expiry_date':  str(lot.expiration_date.date()
                                    if hasattr(lot.expiration_date, 'date')
                                    else lot.expiration_date)
                                if lot and lot.expiration_date else '',
                'expected_qty': q.quantity,
            })
        return result

    @api.model
    def resolve_product_barcode(self, barcode, location_id=False):
        """Scan a product barcode → navigate to that product in count list.

        Returns {'ok': True, 'product_id', 'product_name', 'product_code', 'barcode'}
        or      {'ok': False, 'error': '...'}
        """
        if not barcode:
            return {'ok': False, 'error': _('Empty barcode.')}
        product = self.env['product.product'].sudo().search([
            '|', ('barcode', '=', barcode), ('default_code', '=', barcode)
        ], limit=1)
        if not product:
            return {'ok': False, 'error': _('Product not found: %s') % barcode}
        return {
            'ok': True,
            'product_id':   product.id,
            'product_name': product.display_name,
            'product_code': product.default_code or '',
            'barcode':      product.barcode or '',
        }

    @api.model
    def search_lots_for_product(self, product_id, location_id=False):
        """Return all lots for a product — for the 'Add Lot' picker.

        Shows qty at the task's location so worker knows what system expects.
        Returns [{lot_id, lot_name, lot_ref, expiry_date, qty}]
        """
        lots = self.env['stock.lot'].sudo().search(
            [('product_id', '=', int(product_id))],
            order='name', limit=200)
        result = []
        for lot in lots:
            qty = 0.0
            if location_id:
                q = self.env['stock.quant'].sudo().search([
                    ('lot_id', '=', lot.id),
                    ('location_id', '=', int(location_id)),
                ], limit=1)
                qty = q.quantity if q else 0.0
            result.append({
                'lot_id':      lot.id,
                'lot_name':    lot.name,
                'lot_ref':     lot.ref or '',
                'expiry_date': str(lot.expiration_date.date())
                               if lot.expiration_date else '',
                'qty':         qty,
            })
        return result

    @api.model
    def submit_count_entries(self, task_id, entries):
        """Bulk-create count entries from the mobile screen and submit task.

        entries: [{'product_id': int, 'lot_id': int|False,
                   'qty': float, 'barcode': str}]
        Returns {'ok': bool, 'task_name': str, 'variance_count': int}
        """
        task = self.browse(int(task_id))
        if not task.exists():
            return {'ok': False, 'error': 'Task not found'}
        if task.state not in ('assigned', 'counting'):
            return {'ok': False, 'error': 'Task not in countable state'}

        # Activate counting state + auto-claim broadcast tasks
        if task.state == 'assigned':
            task.state = 'counting'
        if not task.assigned_user_id:
            task.assigned_user_id = self.env.uid

        # Delete existing draft entries (allow re-submit from mobile)
        task.entry_ids.unlink()

        Entry = self.env['wms.count.entry']
        for e in entries:
            if not e.get('product_id'):
                continue
            Entry.create({
                'task_id':    task.id,
                'product_id': int(e['product_id']),
                'lot_id':     int(e['lot_id']) if e.get('lot_id') else False,
                'qty':        float(e.get('qty', 0)),
                'barcode':    e.get('barcode', ''),
                'scan_type':  'piece',
            })

        # Auto-submit
        task.action_submit()

        # ── Unfreeze location ────────────────────────────────────────
        if task.location_id and task.location_id.counting_task_id == task:
            task.location_id.sudo().counting_task_id = False

        # ── Notify session chatter (supervisor visibility) ───────────
        worker_name = self.env.user.name
        entry_count = len(task.entry_ids)
        task.session_id.message_post(
            body=_('✅ <b>%s</b> submitted task <b>%s</b> — %d entries @ %s')
                 % (worker_name, task.name, entry_count,
                    task.location_id.display_name or '—'),
            message_type='notification',
            subtype_xmlid='mail.mt_note',
        )

        # Variance count (products with difference)
        variance_count = 0
        for entry in task.entry_ids:
            exp = sum(task.entry_ids.filtered(
                lambda x: x.product_id == entry.product_id
            ).mapped('qty'))
            # Compare with original expected_qty on task
            if abs(exp - (task.expected_qty or 0)) > 0.001:
                variance_count += 1
                break

        return {
            'ok': True,
            'task_name': task.name,
            'variance_count': variance_count,
        }

    @api.model
    def resolve_lot_barcode(self, barcode, location_id=False):
        """Resolve a scanned barcode to lot/serial info.

        Returns {'ok': bool, 'lot_id': int, 'lot_name': str,
                 'product_id': int, 'product_name': str, 'qty': float}
        """
        if not barcode:
            return {'ok': False}
        # Try stock.lot
        lot = self.env['stock.lot'].sudo().search(
            [('name', '=', barcode)], limit=1)
        if not lot:
            # Try lot ref
            lot = self.env['stock.lot'].sudo().search(
                [('ref', '=', barcode)], limit=1)
        if lot:
            qty = 0.0
            if location_id:
                quant = self.env['stock.quant'].sudo().search([
                    ('lot_id', '=', lot.id),
                    ('location_id', '=', int(location_id)),
                ], limit=1)
                qty = quant.quantity if quant else 0.0
            return {
                'ok': True,
                'lot_id':      lot.id,
                'lot_name':    lot.name,
                'lot_ref':     lot.ref or '',
                'product_id':  lot.product_id.id,
                'product_name': lot.product_id.display_name,
                'product_code': lot.product_id.default_code or '',
                'qty':         qty,
            }
        return {'ok': False, 'error': _('Lot/Serial not found: %s') % barcode}
