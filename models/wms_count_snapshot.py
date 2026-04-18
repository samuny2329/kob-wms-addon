from odoo import models, fields


class WmsCountSnapshot(models.Model):
    """Point-in-time snapshot of stock.quant taken when a worker starts
    counting a specific location (task state → 'counting').

    Used as the variance reference so that concurrent stock moves during
    the count do NOT corrupt the result — workers compare against the
    snapshot, not live quantities.

    Lifecycle:
        created  → start_counting()  (replaces any previous snapshot for the task)
        deleted  → cascade when the parent wms.count.task is deleted
        read     → submit_count_entries() uses it as expected_qty basis
    """
    _name = 'wms.count.snapshot'
    _description = 'WMS Count Location Snapshot'
    _order = 'task_id, product_id, lot_id'
    _rec_name = 'product_id'

    task_id = fields.Many2one(
        'wms.count.task', string='Task',
        required=True, ondelete='cascade', index=True)
    product_id = fields.Many2one(
        'product.product', string='Product', required=True)
    lot_id = fields.Many2one(
        'stock.lot', string='Lot / Serial')
    location_id = fields.Many2one(
        'stock.location', string='Location', required=True)
    qty = fields.Float(
        string='Qty at Snapshot',
        digits='Product Unit of Measure')
    snapshot_date = fields.Datetime(
        string='Taken At',
        default=fields.Datetime.now,
        readonly=True)
