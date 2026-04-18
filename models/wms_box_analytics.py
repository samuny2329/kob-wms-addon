from odoo import models, fields, tools


class WmsBoxAnalytics(models.Model):
    """360° Box Analytics SQL View.

    Aggregates wms.sales.order by date + box size to give:
    - Usage counts (orders per box)
    - AI suggestion accuracy (hit rate)
    - Fill efficiency %
    - Full cost breakdown: box + tape + bubble wrap + total
    - Weight distribution
    - Pack speed (avg minutes)
    """
    _name        = 'wms.box.analytics'
    _description = '360° Box Usage Analytics'
    _auto        = False
    _order       = 'date desc, order_count desc'

    # ── Time ─────────────────────────────────────────────────
    date  = fields.Date(string='Date',  readonly=True)
    month = fields.Char(string='Month', readonly=True)

    # ── Dimensions ───────────────────────────────────────────
    actual_box_id    = fields.Many2one('wms.box.size', string='Box Used',     readonly=True)
    suggested_box_id = fields.Many2one('wms.box.size', string='AI Suggested', readonly=True)
    courier_id       = fields.Many2one('wms.courier',  string='Courier',      readonly=True)
    platform         = fields.Selection([
        ('odoo', 'Odoo'), ('shopee', 'Shopee'), ('lazada', 'Lazada'),
        ('tiktok', 'TikTok'), ('pos', 'POS'), ('manual', 'Manual'),
    ], string='Platform', readonly=True)

    # ── Volume & Weight ──────────────────────────────────────
    order_count  = fields.Integer(string='Orders',           readonly=True)
    total_vol_m3 = fields.Float( string='Total Vol (m³)',    readonly=True, digits=(12, 6))
    avg_vol_m3   = fields.Float( string='Avg Vol/Order',     readonly=True, digits=(10, 6))
    total_weight = fields.Float( string='Total Weight (kg)', readonly=True, digits=(10, 3))
    avg_fill_pct = fields.Float( string='Avg Fill %',        readonly=True, digits=(5, 1))
    min_fill_pct = fields.Float( string='Min Fill %',        readonly=True, digits=(5, 1))
    max_fill_pct = fields.Float( string='Max Fill %',        readonly=True, digits=(5, 1))

    # ── AI Suggestion accuracy ────────────────────────────────
    suggestion_hits = fields.Integer(string='AI Hits',      readonly=True)
    hit_rate        = fields.Float( string='AI Hit Rate %', readonly=True, digits=(5, 1))

    # ── Cost breakdown ────────────────────────────────────────
    total_box_cost    = fields.Float(string='Box Cost (฿)',          readonly=True, digits=(12, 2))
    avg_box_cost      = fields.Float(string='Box Cost/Order (฿)',    readonly=True, digits=(10, 2))
    total_tape_cost   = fields.Float(string='Tape Cost (฿)',         readonly=True, digits=(12, 2))
    avg_tape_cost     = fields.Float(string='Tape Cost/Order (฿)',   readonly=True, digits=(10, 2))
    total_bubble_cost = fields.Float(string='Bubble Cost (฿)',       readonly=True, digits=(12, 2))
    avg_bubble_cost   = fields.Float(string='Bubble Cost/Order (฿)', readonly=True, digits=(10, 2))
    total_pack_cost   = fields.Float(string='Total Pack Cost (฿)',   readonly=True, digits=(12, 2))
    avg_pack_cost     = fields.Float(string='Total Pack/Order (฿)',  readonly=True, digits=(10, 2))

    # ── Fulfilment speed ─────────────────────────────────────
    avg_pack_min = fields.Float(string='Avg Pack Time (min)', readonly=True, digits=(8, 1))

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW wms_box_analytics AS
            SELECT
                row_number() OVER ()              AS id,
                DATE(o.packed_at)                 AS date,
                TO_CHAR(o.packed_at, 'YYYY-MM')   AS month,
                o.actual_box_id,
                o.suggested_box_id,
                o.courier_id,
                o.platform,

                COUNT(*)                          AS order_count,

                -- Volume & Weight
                COALESCE(SUM(o.order_vol_m3), 0)           AS total_vol_m3,
                COALESCE(AVG(o.order_vol_m3), 0)           AS avg_vol_m3,
                COALESCE(SUM(o.order_weight_kg), 0)        AS total_weight,
                ROUND(COALESCE(AVG(o.box_fill_pct),  0)::numeric, 1) AS avg_fill_pct,
                ROUND(COALESCE(MIN(o.box_fill_pct),  0)::numeric, 1) AS min_fill_pct,
                ROUND(COALESCE(MAX(o.box_fill_pct),  0)::numeric, 1) AS max_fill_pct,

                -- AI accuracy
                SUM(CASE WHEN o.box_suggestion_hit THEN 1 ELSE 0 END) AS suggestion_hits,
                ROUND(
                    100.0 * SUM(CASE WHEN o.box_suggestion_hit THEN 1 ELSE 0 END)
                    / NULLIF(COUNT(*), 0)
                , 1)                                       AS hit_rate,

                -- Cost: Box
                ROUND(COALESCE(SUM(o.box_cost_est),  0)::numeric, 2) AS total_box_cost,
                ROUND(COALESCE(AVG(o.box_cost_est),  0)::numeric, 2) AS avg_box_cost,

                -- Cost: Tape
                ROUND(COALESCE(SUM(o.tape_cost_est),   0)::numeric, 2) AS total_tape_cost,
                ROUND(COALESCE(AVG(o.tape_cost_est),   0)::numeric, 2) AS avg_tape_cost,

                -- Cost: Bubble Wrap
                ROUND(COALESCE(SUM(o.bubble_cost_est), 0)::numeric, 2) AS total_bubble_cost,
                ROUND(COALESCE(AVG(o.bubble_cost_est), 0)::numeric, 2) AS avg_bubble_cost,

                -- Cost: Total packaging material
                ROUND(COALESCE(SUM(o.total_pack_cost), 0)::numeric, 2) AS total_pack_cost,
                ROUND(COALESCE(AVG(o.total_pack_cost), 0)::numeric, 2) AS avg_pack_cost,

                -- Speed
                ROUND(COALESCE(AVG(o.pack_duration_min), 0)::numeric, 1) AS avg_pack_min

            FROM wms_sales_order o
            WHERE o.actual_box_id IS NOT NULL
              AND o.status IN ('packed', 'shipped')
              AND o.packed_at IS NOT NULL
            GROUP BY
                DATE(o.packed_at),
                TO_CHAR(o.packed_at, 'YYYY-MM'),
                o.actual_box_id,
                o.suggested_box_id,
                o.courier_id,
                o.platform
        """)
