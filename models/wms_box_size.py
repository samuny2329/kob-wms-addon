from odoo import models, fields, api


class WmsBoxSize(models.Model):
    """Box size catalogue — pre-populated from THE BOX price list.
    Dimensions stored in cm; volume computed in m³ to match
    Odoo's product.template.volume (m³ by default).

    v3: Added tape-length formula, bubble-wrap estimate, total material cost.

    Tape formula (per box sealed):
        girth     = (width + height) × 2          cm
        tape_len  = girth × rounds + overlap_cm   cm  → ÷100 → metres
        tape_cost = tape_len_m × tape_cost_per_m  ฿

    Bubble wrap: flat estimate per box size (manager sets based on typical products).
    """
    _name        = 'wms.box.size'
    _description = 'WMS Box Size'
    _order       = 'volume asc'

    # ── Identity ───────────────────────────────────────────────
    code     = fields.Char(string='Code', required=True, index=True)
    label    = fields.Char(string='Display Label')
    active   = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)

    # ── Physical dimensions (cm) ───────────────────────────────
    length = fields.Float(string='Length (cm)', required=True)
    width  = fields.Float(string='Width (cm)',  required=True)
    height = fields.Float(string='Height (cm)', required=True)

    # ── Computed volumes ───────────────────────────────────────
    volume_cm3 = fields.Float(
        string='Volume (cm³)',
        compute='_compute_volume', store=True, readonly=True)
    volume = fields.Float(
        string='Volume (m³)',
        compute='_compute_volume', store=True, readonly=True,
        help='Used to compare against product.template.volume (m³)')

    # ── Weight limit ───────────────────────────────────────────
    weight_limit = fields.Float(string='Max Weight (kg)', default=0.0)

    # ── Box Cost & Procurement ─────────────────────────────────
    unit_cost = fields.Float(
        string='Box Cost (฿)', default=0.0, digits=(10, 2),
        help='Purchase price per box (THE BOX price list, THB)')
    restock_qty = fields.Integer(
        string='Min Stock Level', default=0,
        help='Trigger restock when current_stock drops below this')
    restock_lead_days = fields.Integer(
        string='Lead Time (days)', default=3,
        help='Days from order to delivery for this box size')
    current_stock = fields.Integer(
        string='Current Stock', default=0,
        help='How many boxes are currently in store')

    # ── Tape Calculation ───────────────────────────────────────
    tape_rounds = fields.Integer(
        string='Tape Rounds', default=3,
        help='Minimum number of tape wraps around the box girth when sealing')
    tape_overlap_cm = fields.Float(
        string='Tape Overlap (cm)', default=20.0,
        help='Extra length per seal for overlaps and tab ends (cm)')
    tape_cost_per_m = fields.Float(
        string='Tape Price/m (฿)', default=0.50, digits=(6, 3),
        help='Cost per metre of packaging tape in THB '
             '(e.g. 48 mm × 100 m roll ÷ roll cost)')
    tape_length_m = fields.Float(
        string='Tape/Box (m)',
        compute='_compute_tape', store=True, digits=(8, 3),
        help='Computed tape per box: [(W+H)×2 × rounds + overlap] ÷ 100')
    tape_cost_est = fields.Float(
        string='Tape Cost/Box (฿)',
        compute='_compute_tape', store=True, digits=(10, 2),
        help='tape_length_m × tape_cost_per_m')

    # ── Bubble Wrap ────────────────────────────────────────────
    bubble_cost_est = fields.Float(
        string='Bubble Wrap Cost/Box (฿)', default=0.0, digits=(10, 2),
        help='Estimated bubble-wrap material cost per order using this box.\n'
             'Set by manager based on typical product fragility for this size.')

    # ── Total Material Cost (per sealed box) ───────────────────
    total_material_cost = fields.Float(
        string='Total Material Cost (฿)',
        compute='_compute_total_material', store=True, digits=(10, 2),
        help='Box + Tape + Bubble Wrap cost per sealed order')

    # ── Analytics (computed from wms.sales.order, not stored) ──
    usage_30d = fields.Integer(
        string='Used (30d)', compute='_compute_usage', store=False,
        help='Number of orders using this box in the last 30 days')
    cost_30d = fields.Float(
        string='Total Material Cost (30d ฿)', compute='_compute_usage',
        store=False, digits=(10, 2),
        help='Total material cost (box+tape+bubble) in last 30 days')
    restock_alert = fields.Boolean(
        string='Needs Restock', compute='_compute_usage', store=False)

    note  = fields.Char(string='Note')
    image = fields.Image(string='Box Photo', max_width=400, max_height=400)

    # ── Computes ───────────────────────────────────────────────

    @api.depends('length', 'width', 'height')
    def _compute_volume(self):
        for r in self:
            r.volume_cm3 = r.length * r.width * r.height
            r.volume = (r.length / 100.0) * (r.width / 100.0) * (r.height / 100.0)

    @api.depends('width', 'height', 'tape_rounds', 'tape_overlap_cm', 'tape_cost_per_m')
    def _compute_tape(self):
        """Tape length = (W+H)×2 × rounds + overlap  [cm → m].
        Girth wraps around the cross-section perpendicular to the box length.
        """
        for r in self:
            girth_cm = (r.width + r.height) * 2.0
            length_cm = girth_cm * (r.tape_rounds or 3) + (r.tape_overlap_cm or 20.0)
            r.tape_length_m = round(length_cm / 100.0, 3)
            r.tape_cost_est = round(r.tape_length_m * (r.tape_cost_per_m or 0.0), 2)

    @api.depends('unit_cost', 'tape_cost_est', 'bubble_cost_est')
    def _compute_total_material(self):
        for r in self:
            r.total_material_cost = (
                (r.unit_cost or 0.0)
                + (r.tape_cost_est or 0.0)
                + (r.bubble_cost_est or 0.0)
            )

    def _compute_usage(self):
        """Compute 30-day usage stats from wms.sales.order."""
        from datetime import timedelta
        cutoff = fields.Datetime.to_string(
            fields.Datetime.now() - timedelta(days=30))
        for r in self:
            orders = self.env['wms.sales.order'].sudo().search([
                ('actual_box_id', '=', r.id),
                ('packed_at', '>=', cutoff),
            ])
            r.usage_30d = len(orders)
            # Total material cost (box + tape + bubble) × orders
            r.cost_30d  = len(orders) * (r.total_material_cost or 0.0)
            r.restock_alert = (r.restock_qty > 0
                               and r.current_stock < r.restock_qty)

    def name_get(self):
        return [(r.id, r.label or
                 f"{r.code} {r.length:.0f}×{r.width:.0f}×{r.height:.0f} cm")
                for r in self]
