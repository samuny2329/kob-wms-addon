from odoo import models, fields, api, _
from odoo.exceptions import UserError


class WmsBoxRecommenderLine(models.TransientModel):
    """One SKU line in the Box Recommender wizard."""
    _name        = 'wms.box.recommender.line'
    _description = 'Box Recommender SKU Line'

    wizard_id    = fields.Many2one('wms.box.recommender.wizard', ondelete='cascade')
    product_id   = fields.Many2one('product.product', string='Product', required=True)
    sku          = fields.Char(string='SKU', compute='_compute_sku', store=True)
    qty          = fields.Float(string='Qty', default=1.0, digits=(8, 2))
    unit_vol_cm3 = fields.Float(
        string='Vol/Unit (cm³)', compute='_compute_vol', store=True, digits=(12, 2),
        help='product.template.volume (m³) × 1,000,000')
    line_vol_cm3 = fields.Float(
        string='Line Vol (cm³)', compute='_compute_vol', store=True, digits=(12, 2))

    @api.depends('product_id')
    def _compute_sku(self):
        for r in self:
            r.sku = r.product_id.default_code or ''

    @api.depends('product_id', 'qty')
    def _compute_vol(self):
        for r in self:
            tmpl = r.product_id.product_tmpl_id if r.product_id else False
            unit_cm3 = (tmpl.volume * 1_000_000) if (tmpl and tmpl.volume) else 0.0
            r.unit_vol_cm3 = unit_cm3
            r.line_vol_cm3 = unit_cm3 * (r.qty or 1.0)


class WmsBoxRecommenderWizard(models.TransientModel):
    """Wizard: enter SKUs + quantities → get smallest box that fits,
    with fill %, tape cost, bubble wrap, total packaging cost.
    Also shows 2 alternative (larger) box options.
    """
    _name        = 'wms.box.recommender.wizard'
    _description = 'Box Size Recommender'

    # ── Input ──────────────────────────────────────────────────────
    line_ids = fields.One2many(
        'wms.box.recommender.line', 'wizard_id', string='Products to Pack')

    fill_buffer_pct = fields.Float(
        string='Pack Buffer %', default=15.0, digits=(5, 1),
        help='Extra headroom added on top of product volume '
             '(packing material, void fill, irregular shapes)')

    # ── Computed totals ────────────────────────────────────────────
    total_vol_cm3 = fields.Float(
        string='Product Volume (cm³)',
        compute='_compute_totals', store=True, digits=(12, 2))
    required_vol_cm3 = fields.Float(
        string='Required incl. buffer (cm³)',
        compute='_compute_totals', store=True, digits=(12, 2))

    state = fields.Selection(
        [('draft', 'Draft'), ('done', 'Done')], default='draft')

    # ── Recommended box results ────────────────────────────────────
    recommended_box_id = fields.Many2one('wms.box.size', string='Recommended Box', readonly=True)
    fill_pct           = fields.Float(string='Box Fill %',         readonly=True, digits=(5, 1))
    box_cost           = fields.Float(string='Box Cost (฿)',       readonly=True, digits=(10, 2))
    tape_cost          = fields.Float(string='Tape Cost (฿)',      readonly=True, digits=(10, 2))
    bubble_cost        = fields.Float(string='Bubble Wrap (฿)',    readonly=True, digits=(10, 2))
    total_cost         = fields.Float(string='Total Pack Cost (฿)', readonly=True, digits=(10, 2))
    result_note        = fields.Char(string='Note',                readonly=True)

    # ── Alternative boxes ──────────────────────────────────────────
    alt1_box_id   = fields.Many2one('wms.box.size', string='Option 2', readonly=True)
    alt1_fill_pct = fields.Float(string='Fill %',        readonly=True, digits=(5, 1))
    alt1_cost     = fields.Float(string='Pack Cost (฿)', readonly=True, digits=(10, 2))

    alt2_box_id   = fields.Many2one('wms.box.size', string='Option 3', readonly=True)
    alt2_fill_pct = fields.Float(string='Fill %',        readonly=True, digits=(5, 1))
    alt2_cost     = fields.Float(string='Pack Cost (฿)', readonly=True, digits=(10, 2))

    # ── Computes ───────────────────────────────────────────────────

    @api.depends('line_ids.line_vol_cm3', 'fill_buffer_pct')
    def _compute_totals(self):
        for r in self:
            total = sum(r.line_ids.mapped('line_vol_cm3'))
            r.total_vol_cm3    = total
            r.required_vol_cm3 = total * (1.0 + (r.fill_buffer_pct or 0.0) / 100.0)

    # ── Private helpers ────────────────────────────────────────────

    def _fill_pct(self, total_cm3, box):
        if not box.volume_cm3:
            return 0.0
        return round(total_cm3 / box.volume_cm3 * 100.0, 1)

    def _set_result(self, box, note=''):
        self.recommended_box_id = box
        self.fill_pct    = self._fill_pct(self.total_vol_cm3, box)
        self.box_cost    = box.unit_cost
        self.tape_cost   = box.tape_cost_est
        self.bubble_cost = box.bubble_cost_est
        self.total_cost  = box.total_material_cost
        self.result_note = note

    def _set_alts(self, boxes, total_cm3):
        if len(boxes) >= 1:
            self.alt1_box_id   = boxes[0]
            self.alt1_fill_pct = self._fill_pct(total_cm3, boxes[0])
            self.alt1_cost     = boxes[0].total_material_cost
        if len(boxes) >= 2:
            self.alt2_box_id   = boxes[1]
            self.alt2_fill_pct = self._fill_pct(total_cm3, boxes[1])
            self.alt2_cost     = boxes[1].total_material_cost

    # ── Actions ────────────────────────────────────────────────────

    def action_compute(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('Please add at least one product.'))

        total_vol    = self.total_vol_cm3
        required_vol = self.required_vol_cm3

        if required_vol <= 0:
            raise UserError(_(
                'All product volumes are zero.\n'
                'Set product dimensions (Length × Width × Height) on the '
                'product form first, then try again.'))

        # Smallest 3 boxes that fit the required volume (incl. buffer)
        fitting = self.env['wms.box.size'].search(
            [('active', '=', True), ('volume_cm3', '>=', required_vol)],
            order='volume_cm3 asc', limit=3)

        note = ''
        if not fitting:
            # Nothing fits — pick the largest and warn
            biggest = self.env['wms.box.size'].search(
                [('active', '=', True)], order='volume_cm3 desc', limit=1)
            if not biggest:
                raise UserError(_('No active box sizes found — set up the Box Catalogue first.'))
            self._set_result(
                biggest,
                note=_('⚠️ No single box fits! Largest box selected. '
                        'Consider splitting into multiple packages.'))
        else:
            rec = fitting[0]
            if total_vol and rec.volume_cm3 and (total_vol / rec.volume_cm3 * 100) > 90:
                note = _('⚠️ Very tight fit (%.0f%% fill) — consider the next size up.')  \
                       % (total_vol / rec.volume_cm3 * 100)
            self._set_result(rec, note=note)
            self._set_alts(fitting[1:], total_vol)

        self.state = 'done'
        # Re-open the same dialog to show results
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_reset(self):
        """Clear results and go back to input mode."""
        self.write({
            'state': 'draft',
            'recommended_box_id': False,
            'fill_pct': 0.0, 'box_cost': 0.0, 'tape_cost': 0.0,
            'bubble_cost': 0.0, 'total_cost': 0.0, 'result_note': '',
            'alt1_box_id': False, 'alt1_fill_pct': 0.0, 'alt1_cost': 0.0,
            'alt2_box_id': False, 'alt2_fill_pct': 0.0, 'alt2_cost': 0.0,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
