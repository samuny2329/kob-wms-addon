from odoo import models, fields, api, _
from datetime import timedelta
import random
import math


class StockLocationCountLock(models.Model):
    """Extend stock.location with a counting lock flag.

    When a worker starts counting a location (start_counting API),
    counting_task_id is set.  All stock.picking validations that touch
    that location will be blocked until the task is submitted.
    """
    _inherit = 'stock.location'

    counting_task_id = fields.Many2one(
        'wms.count.task', string='Active Count Task',
        help='Set while this location is being counted. Blocks stock moves.',
        ondelete='set null')
    is_counting = fields.Boolean(
        string='Being Counted',
        compute='_compute_is_counting',
        store=True)

    @api.depends('counting_task_id')
    def _compute_is_counting(self):
        for loc in self:
            loc.is_counting = bool(loc.counting_task_id)


class StockQuantPickface(models.Model):
    """Auto-create pickface when product enters PICKFACE location."""
    _inherit = 'stock.quant'

    def _apply_inventory(self):
        """Override to auto-create pickface after inventory adjustment."""
        res = super()._apply_inventory()
        for quant in self:
            if quant.location_id and 'PICKFACE' in (quant.location_id.complete_name or ''):
                self.env['wms.pickface']._auto_register_product(
                    quant.product_id, quant.location_id, quant.quantity)
        return res


class StockLotExpiry(models.Model):
    """Add expiry_days computed field to stock.lot for Near Expiry alert."""
    _inherit = 'stock.lot'

    expiry_days = fields.Integer(string='Days Until Expiry',
                                 compute='_compute_expiry_days', store=True)

    @api.depends('expiration_date')
    def _compute_expiry_days(self):
        today = fields.Date.today()
        for lot in self:
            if lot.expiration_date:
                exp = lot.expiration_date
                if hasattr(exp, 'date'):
                    exp = exp.date()
                lot.expiry_days = (exp - today).days
            else:
                lot.expiry_days = 9999


class WmsCountSession(models.Model):
    """Extend count session with ABC auto-generation."""
    _inherit = 'wms.count.session'

    abc_based = fields.Boolean(string='ABC Based',
                               help='Auto-generate tasks based on order volume (ABC classification)')

    # ── ABC sample sizes per rank ──────────────────────────────────────────
    # A (fast movers)  : sample 30% of yesterday's A movers, max 5 tasks
    # B (medium movers): sample 20% of yesterday's B movers, max 3 tasks
    # C (slow movers)  : sample 10% of yesterday's C movers, max 2 tasks
    _ABC_SAMPLE = {
        'A': {'pct': 0.30, 'max': 5},
        'B': {'pct': 0.20, 'max': 3},
        'C': {'pct': 0.10, 'max': 2},
    }

    @staticmethod
    def _weighted_sample_no_replace(items, n):
        """Weighted random sample without replacement.

        items: [(product_id, weight), ...]  weight = yesterday qty (> 0)
        Returns list of product_ids (up to n, deduplicated).
        """
        if not items or n <= 0:
            return []
        n = min(n, len(items))
        pool = list(items)
        result = []
        for _ in range(n):
            if not pool:
                break
            total = sum(w for _, w in pool)
            r = random.uniform(0, total)
            cumsum = 0.0
            for i, (pid, w) in enumerate(pool):
                cumsum += w
                if cumsum >= r:
                    result.append(pid)
                    pool.pop(i)
                    break
        return result

    def action_generate_abc_tasks(self):
        """Generate cycle count tasks based on ABC classification.

        Logic:
          1. Classify all products into A/B/C by 30-day order volume.
          2. Get yesterday's outbound qty per product (only movers get sampled).
          3. From each rank, randomly sample a subset weighted by yesterday's qty
             — fast movers are more likely to be picked.
          4. Create one task per sampled product (specific SKU, specific location).

        Sample sizes (see _ABC_SAMPLE):
          A → 30% of yesterday's A-movers, max 5
          B → 20% of yesterday's B-movers, max 3
          C → 10% of yesterday's C-movers, max 2
        """
        self.ensure_one()
        if self.state != 'draft':
            return

        today = fields.Date.today()

        # ── Step 1: 30-day actual OUT volume → A/B/C rank ────────────────
        # Use packed_at + status packed/shipped = confirmed OUT only.
        date_from_30 = today - timedelta(days=30)
        self.env.cr.execute("""
            SELECT sol.product_id, SUM(sol.expected_qty) AS total_qty
            FROM wms_sales_order_line sol
            JOIN wms_sales_order so ON so.id = sol.order_id
            WHERE so.packed_at >= %s
              AND so.status IN ('packed', 'shipped')
              AND sol.product_id IS NOT NULL
            GROUP BY sol.product_id
            ORDER BY total_qty DESC
        """, (date_from_30,))
        results_30d = self.env.cr.fetchall()   # [(product_id, qty), ...]

        if not results_30d:
            return

        total_products = len(results_30d)
        a_cutoff = max(1, int(total_products * 0.20))   # top 20%
        b_cutoff = max(a_cutoff + 1, int(total_products * 0.50))  # next 30%

        # Build rank map: product_id → 'A' | 'B' | 'C'
        rank_map = {}
        for idx, (product_id, _) in enumerate(results_30d):
            if idx < a_cutoff:
                rank_map[product_id] = 'A'
            elif idx < b_cutoff:
                rank_map[product_id] = 'B'
            else:
                rank_map[product_id] = 'C'

        # ── Step 2: yesterday's actual OUT qty per product ───────────────────
        # Use packed_at (= when stock was validated/cut) not create_date.
        # Status must be packed or shipped = stock actually left the warehouse.
        yesterday = today - timedelta(days=1)
        self.env.cr.execute("""
            SELECT sol.product_id, SUM(sol.expected_qty) AS yest_qty
            FROM wms_sales_order_line sol
            JOIN wms_sales_order so ON so.id = sol.order_id
            WHERE so.packed_at::date = %s
              AND so.status IN ('packed', 'shipped')
              AND sol.product_id IS NOT NULL
            GROUP BY sol.product_id
        """, (yesterday,))
        yesterday_qty = dict(self.env.cr.fetchall())   # {product_id: qty}

        # ── Step 3: group yesterday's movers by rank ──────────────────────
        groups = {'A': [], 'B': [], 'C': []}
        for product_id, yest_qty in yesterday_qty.items():
            if yest_qty <= 0:
                continue
            abc = rank_map.get(product_id)
            if abc:
                groups[abc].append((product_id, float(yest_qty)))

        # For cycle count skip C entirely (count C only in full counts)
        if self.session_type == 'cycle':
            groups['C'] = []

        # ── Step 4: weighted random sample from each rank ─────────────────
        sampled = []   # [(product_id, abc_rank), ...]
        for abc, items in groups.items():
            if not items:
                continue
            cfg = self._ABC_SAMPLE[abc]
            n = min(cfg['max'], max(1, math.ceil(len(items) * cfg['pct'])))
            chosen = self._weighted_sample_no_replace(items, n)
            for pid in chosen:
                sampled.append((pid, abc))

        if not sampled:
            return

        # ── Step 5: create tasks ──────────────────────────────────────────
        Pickface = self.env['wms.pickface']
        Task = self.env['wms.count.task']
        created = 0

        for product_id, abc in sampled:
            pf = Pickface.search([('product_id', '=', product_id)], limit=1)
            if not pf or not pf.location_id:
                continue

            location = pf.location_id
            zone = pf.zone_id
            rack = self.env['wms.rack'].search(
                [('zone_id', '=', zone.id)], limit=1
            ) if zone else self.env['wms.rack']

            product = self.env['product.product'].browse(product_id)
            product_code = product.default_code or str(product_id)
            yest_qty = yesterday_qty.get(product_id, 0)

            Task.create({
                'session_id': self.id,
                'name': _('[%s] Count %s') % (abc, product_code),
                'location_id': location.id,
                'rack_id': rack.id if rack else False,
                'product_id': product_id,
                'expected_qty': yest_qty,   # yesterday's out qty as reference
            })
            created += 1

        self.abc_based = True
        a_n = sum(1 for _, r in sampled if r == 'A')
        b_n = sum(1 for _, r in sampled if r == 'B')
        c_n = sum(1 for _, r in sampled if r == 'C')
        self.message_post(body=_(
            'ABC tasks generated (yesterday %s): %d tasks — A=%d, B=%d, C=%d '
            '(sampled from %d total products in 30-day window)'
        ) % (yesterday, created, a_n, b_n, c_n, total_products))
