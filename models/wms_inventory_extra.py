from odoo import models, fields, api, _
from datetime import timedelta


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

    def action_generate_abc_tasks(self):
        """Generate cycle count tasks based on ABC classification.
        A = top 20% products by order volume → count daily
        B = next 30% → count weekly
        C = bottom 50% → count monthly
        """
        self.ensure_one()
        if self.state != 'draft':
            return

        # Get order volume from last 30 days
        date_from = fields.Date.today() - timedelta(days=30)
        self.env.cr.execute("""
            SELECT sol.product_id, SUM(sol.expected_qty) as total_qty
            FROM wms_sales_order_line sol
            JOIN wms_sales_order so ON so.id = sol.order_id
            WHERE so.create_date >= %s
              AND sol.product_id IS NOT NULL
            GROUP BY sol.product_id
            ORDER BY total_qty DESC
        """, (date_from,))
        results = self.env.cr.fetchall()

        if not results:
            return

        total_products = len(results)
        a_cutoff = int(total_products * 0.2)  # top 20%
        b_cutoff = int(total_products * 0.5)  # next 30%

        # Get pickface locations for these products
        Pickface = self.env['wms.pickface']
        Task = self.env['wms.count.task']
        created = 0

        for idx, (product_id, qty) in enumerate(results):
            if idx < a_cutoff:
                abc = 'A'
            elif idx < b_cutoff:
                abc = 'B'
            else:
                abc = 'C'

            # For cycle count: only count A items daily, B weekly
            if self.session_type == 'cycle':
                if abc == 'C':
                    continue  # skip C items in cycle count

            # Find pickface for this product
            pf = Pickface.search([('product_id', '=', product_id)], limit=1)
            location = pf.location_id if pf else None
            zone = pf.zone_id if pf else None

            if not location:
                continue

            # zone_id on wms.count.task is a related field (rack_id.zone_id)
            # so we must set rack_id — find any rack in the pickface zone.
            rack = self.env['wms.rack'].search(
                [('zone_id', '=', zone.id)], limit=1
            ) if zone else self.env['wms.rack']

            product_code = self.env['product.product'].browse(product_id).default_code or str(product_id)
            Task.create({
                'session_id': self.id,
                'name': _('[%s] Count %s') % (abc, product_code),
                'location_id': location.id,
                'rack_id': rack.id if rack else False,
            })
            created += 1

        self.abc_based = True
        self.message_post(body=_(
            'ABC tasks generated: %d tasks (A=%d, B=%d products analyzed from %d total)'
        ) % (created, a_cutoff, b_cutoff - a_cutoff, total_products))
