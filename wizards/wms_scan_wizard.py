from odoo import models, fields, api, _
from odoo.exceptions import UserError


class WmsScanWizard(models.TransientModel):
    """Modal wizard that lets a worker keep scanning SKUs / barcodes against
    a single wms.sales.order without closing the dialog between scans."""
    _name = 'wms.scan.wizard'
    _description = 'WMS Scan Wizard'

    def init(self):
        """Drop NOT NULL on order_id so gateway mode (no order) works.
        This runs on every module load (install + upgrade)."""
        try:
            self.env.cr.execute(
                "ALTER TABLE wms_scan_wizard "
                "ALTER COLUMN order_id DROP NOT NULL"
            )
        except Exception:
            pass

    order_id = fields.Many2one(
        'wms.sales.order', string='Order', required=False, readonly=True,
    )
    order_name = fields.Char(related='order_id.name', readonly=True)
    order_ref = fields.Char(related='order_id.ref', readonly=True)
    order_customer = fields.Char(related='order_id.customer', readonly=True)
    order_status = fields.Selection(related='order_id.status', readonly=True)

    mode = fields.Selection([
        ('pick', 'Pick (F1)'),
        ('pack', 'Pack (F2)'),
        ('box', 'Close Box'),
    ], string='Mode', default='pick', required=True)

    scan_input = fields.Char(string='Scan / Barcode', required=False)

    expected_total = fields.Integer(related='order_id.expected_total', readonly=True)
    picked_total = fields.Integer(related='order_id.picked_total', readonly=True)
    packed_total = fields.Integer(related='order_id.packed_total', readonly=True)

    history = fields.Text(
        string='Recent scans', readonly=True,
        help='Last successful scans in this wizard session.',
    )

    line_preview = fields.Html(
        string='Items', compute='_compute_line_preview', sanitize=False,
    )

    # ── Close Box fields ──────────────────────────────────────────────
    box_size_id = fields.Many2one(
        'wms.box.size', string='Override Box',
        help='Leave empty to accept the recommended box.'
    )
    box_suggestion_label = fields.Char(
        compute='_compute_box_suggestion', string='Recommended Box',
    )
    box_suggestion_note = fields.Char(
        compute='_compute_box_suggestion', string='Basis',
    )
    box_suggestion_code = fields.Char(
        compute='_compute_box_suggestion', string='Box Code',
    )

    @api.depends('order_id', 'mode')
    def _compute_box_suggestion(self):
        for wiz in self:
            if wiz.order_id and wiz.mode == 'box':
                s = wiz.order_id.get_recommended_box()
                if s.get('ok'):
                    wiz.box_suggestion_label = s.get('box_label', '—')
                    wiz.box_suggestion_note  = s.get('note', '')
                    wiz.box_suggestion_code  = s.get('box_code', '')
                else:
                    wiz.box_suggestion_label = s.get('error', '—')
                    wiz.box_suggestion_note  = ''
                    wiz.box_suggestion_code  = ''
            else:
                wiz.box_suggestion_label = ''
                wiz.box_suggestion_note  = ''
                wiz.box_suggestion_code  = ''

    @api.depends('order_id.line_ids.picked_qty', 'order_id.line_ids.packed_qty')
    def _compute_line_preview(self):
        for wiz in self:
            if not wiz.order_id:
                wiz.line_preview = ''
                continue
            rows = []
            for line in wiz.order_id.line_ids:
                bar = ''
                if line.expected_qty:
                    if wiz.mode == 'pack':
                        done, total = line.packed_qty, line.picked_qty or line.expected_qty
                    else:
                        done, total = line.picked_qty, line.expected_qty
                    color = '#017E84' if done >= total else '#E8A940'
                    pct = int((done / total) * 100) if total else 0
                    bar = (
                        f'<div style="background:#e5e7eb;border-radius:4px;height:10px;'
                        f'width:120px;display:inline-block;overflow:hidden;">'
                        f'<div style="background:{color};height:100%;width:{pct}%;"></div>'
                        f'</div> {done}/{total}'
                    )
                # Show barcode prominently so worker knows what to scan
                barcode = ''
                if line.product_id and line.product_id.barcode:
                    barcode = (
                        f'<br/><small style="color:#714B67;font-family:monospace;">'
                        f'🔖 {line.product_id.barcode}</small>'
                    )
                elif line.sku:
                    barcode = (
                        f'<br/><small style="color:#80747A;font-family:monospace;">'
                        f'SKU: {line.sku}</small>'
                    )
                rows.append(
                    f'<tr><td><strong>{line.sku or ""}</strong>{barcode}</td>'
                    f'<td>{line.product_name or ""}</td>'
                    f'<td>{bar}</td></tr>'
                )
            wiz.line_preview = (
                '<table class="table table-sm"><thead><tr>'
                '<th>SKU / Barcode</th><th>Product</th><th>Progress</th></tr></thead>'
                '<tbody>' + ''.join(rows) + '</tbody></table>'
            )

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'wms.scan.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }

    def action_scan(self):
        self.ensure_one()
        code = (self.scan_input or '').strip()
        if not code:
            raise UserError(_('Please scan or type a barcode first.'))

        # --- GATEWAY MODE: no order selected yet → find order by barcode ---
        if not self.order_id:
            order = self.env['wms.sales.order'].search([
                '|', '|',
                ('name', '=', code),
                ('ref', '=', code),
                ('ref', 'ilike', code),
            ], limit=1)
            if not order:
                raise UserError(
                    _('Order not found: %s\n'
                      'Scan a valid order reference (SO/YYYY/NNNNN or platform ref).')
                    % code
                )
            self.order_id = order
            self.scan_input = False
            return self._reopen()

        # --- ITEM SCAN MODE: order is set → scan SKU ---
        try:
            if self.mode == 'pick':
                self.order_id.scan_pick(code)
            elif self.mode == 'pack':
                self.order_id.scan_pack(code)
            elif self.mode == 'box':
                self.order_id.close_box(code)
        except UserError:
            raise
        # Append to history, clear input, keep wizard open
        prev = (self.history or '').splitlines()
        entry = f'✓ {self.mode.upper()}  {code}'
        prev.insert(0, entry)
        self.history = '\n'.join(prev[:15])
        self.scan_input = False
        return self._reopen()

    def action_close_box(self):
        """Close box using selected or recommended size, then auto-print AWB."""
        self.ensure_one()
        if not self.order_id:
            raise UserError(_('No order selected.'))
        # Use override if set, otherwise fall back to the computed recommendation
        box_code = self.box_size_id.code if self.box_size_id else self.box_suggestion_code
        res = self.order_id.select_box_and_close(box_code)
        if not res.get('ok'):
            raise UserError(res.get('error', _('Close box failed.')))
        # Auto-print AWB
        if res.get('awb_action'):
            return res['awb_action']
        return {'type': 'ir.actions.act_window_close'}

    def action_done(self):
        return {'type': 'ir.actions.act_window_close'}

    def action_next_order(self):
        """Close current order and open the wizard for the next order
        in the same mode's queue."""
        self.ensure_one()
        domain = self._domain_for_mode(self.mode)
        # Find next order (skip current)
        next_order = self.env['wms.sales.order'].search(
            domain + [('id', '!=', self.order_id.id)],
            limit=1, order='sla_pick_deadline asc, create_date desc',
        )
        if not next_order:
            return {'type': 'ir.actions.act_window_close'}
        wiz = self.create({'order_id': next_order.id, 'mode': self.mode})
        return wiz._reopen()

    @staticmethod
    def _domain_for_mode(mode):
        return {
            'pick': [('status', 'in', ['pending', 'picking'])],
            'pack': [('status', 'in', ['picked', 'packing'])],
            'box':  [('status', '=', 'packing')],
        }.get(mode, [('status', 'in', ['pending', 'picking'])])

    @api.model
    def action_open_from_order(self, order_id, mode='pick'):
        wiz = self.create({'order_id': order_id, 'mode': mode})
        return wiz._reopen()

    @api.model
    def action_open_next_in_queue(self, mode='pick'):
        """Open the wizard for the first order in the given mode's queue.
        Called from menu server actions."""
        domain = self._domain_for_mode(mode)
        order = self.env['wms.sales.order'].search(
            domain, limit=1, order='sla_pick_deadline asc, create_date desc',
        )
        if not order:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Queue empty',
                    'message': f'No orders in {mode.upper()} queue.',
                    'type': 'info',
                    'sticky': False,
                },
            }
        wiz = self.create({'order_id': order.id, 'mode': mode})
        return wiz._reopen()
