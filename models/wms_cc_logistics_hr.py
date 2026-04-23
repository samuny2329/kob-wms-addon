"""Command Center — Logistics (OTIF/OTD) + HR (Turnover/Training).

Four models for Yong (Asst WH Manager) + Aoy (Sr Admin & Ops):

1. wms.cc.otif.monitor (SQL view)
   On-Time In-Full per stock.picking (outgoing). Combines:
     - on_time = (date_done <= scheduled_date)
     - in_full = (delivered_qty == demand_qty)
   OTIF = on_time AND in_full.

2. wms.cc.otd.rate (SQL view)
   OTD per month (outgoing pickings only, % on-time).

3. wms.cc.hr.turnover (SQL view)
   Monthly summary of active/inactive hr.employee changes.

4. wms.cc.training.log (model)
   Simple model to log training sessions per employee — replaces
   spreadsheet tracking of OKR4 Training Hours.
"""
from odoo import models, fields, tools


class WmsCcOtifMonitor(models.Model):
    _name = 'wms.cc.otif.monitor'
    _description = 'CC — On-Time In-Full Monitor'
    _auto = False
    _order = 'date_done desc, id'

    picking_id = fields.Many2one('stock.picking', readonly=True)
    picking_name = fields.Char(readonly=True)
    partner_id = fields.Many2one('res.partner', readonly=True)
    scheduled_date = fields.Datetime(readonly=True)
    date_done = fields.Datetime(readonly=True)
    delay_days = fields.Float(digits=(10, 2), readonly=True)
    demand_qty = fields.Float(digits=(14, 2), readonly=True)
    delivered_qty = fields.Float(digits=(14, 2), readonly=True)
    is_on_time = fields.Boolean(readonly=True)
    is_in_full = fields.Boolean(readonly=True)
    is_otif = fields.Boolean(readonly=True, string='OTIF')
    company_id = fields.Many2one('res.company', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                WITH pick_qty AS (
                    SELECT
                        sm.picking_id,
                        SUM(sm.product_uom_qty)   AS demand_qty,
                        SUM(sm.quantity)          AS delivered_qty
                    FROM stock_move sm
                    WHERE sm.picking_id IS NOT NULL
                    GROUP BY sm.picking_id
                )
                SELECT
                    sp.id                         AS id,
                    sp.id                         AS picking_id,
                    sp.name                       AS picking_name,
                    sp.partner_id                 AS partner_id,
                    sp.scheduled_date             AS scheduled_date,
                    sp.date_done                  AS date_done,
                    CASE WHEN sp.date_done IS NOT NULL AND sp.scheduled_date IS NOT NULL THEN
                        EXTRACT(EPOCH FROM (sp.date_done - sp.scheduled_date)) / 86400.0
                    ELSE 0 END                    AS delay_days,
                    COALESCE(pq.demand_qty, 0)    AS demand_qty,
                    COALESCE(pq.delivered_qty, 0) AS delivered_qty,
                    (sp.date_done <= sp.scheduled_date) AS is_on_time,
                    (ABS(COALESCE(pq.demand_qty,0) - COALESCE(pq.delivered_qty,0)) < 0.001
                        AND COALESCE(pq.demand_qty, 0) > 0)
                        AS is_in_full,
                    ((sp.date_done <= sp.scheduled_date)
                     AND ABS(COALESCE(pq.demand_qty,0) - COALESCE(pq.delivered_qty,0)) < 0.001
                     AND COALESCE(pq.demand_qty, 0) > 0)
                        AS is_otif,
                    sp.company_id                 AS company_id
                FROM stock_picking sp
                JOIN stock_picking_type spt ON spt.id = sp.picking_type_id
                LEFT JOIN pick_qty pq ON pq.picking_id = sp.id
                WHERE sp.state = 'done'
                  AND spt.code = 'outgoing'
                  AND sp.date_done >= NOW() - INTERVAL '90 days'
            )
        """ % self._table)


class WmsCcOtdRate(models.Model):
    _name = 'wms.cc.otd.rate'
    _description = 'CC — OTD Rate (monthly)'
    _auto = False
    _order = 'period_month desc'

    period_month = fields.Char(readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    total_pickings = fields.Integer(readonly=True)
    on_time_count = fields.Integer(readonly=True)
    otd_pct = fields.Float(digits=(5, 2), readonly=True,
                           string='OTD %')
    otif_count = fields.Integer(readonly=True)
    otif_pct = fields.Float(digits=(5, 2), readonly=True,
                            string='OTIF %')

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                WITH pick_qty AS (
                    SELECT
                        sm.picking_id,
                        SUM(sm.product_uom_qty)   AS demand_qty,
                        SUM(sm.quantity)          AS delivered_qty
                    FROM stock_move sm
                    WHERE sm.picking_id IS NOT NULL
                    GROUP BY sm.picking_id
                ),
                pickings AS (
                    SELECT
                        TO_CHAR(sp.date_done, 'YYYY-MM') AS period_month,
                        sp.company_id,
                        sp.id,
                        (sp.date_done <= sp.scheduled_date) AS on_time,
                        ((sp.date_done <= sp.scheduled_date)
                         AND ABS(COALESCE(pq.demand_qty,0) - COALESCE(pq.delivered_qty,0)) < 0.001
                         AND COALESCE(pq.demand_qty,0) > 0) AS otif
                    FROM stock_picking sp
                    JOIN stock_picking_type spt ON spt.id = sp.picking_type_id
                    LEFT JOIN pick_qty pq ON pq.picking_id = sp.id
                    WHERE sp.state = 'done'
                      AND spt.code = 'outgoing'
                      AND sp.date_done IS NOT NULL
                      AND sp.scheduled_date IS NOT NULL
                )
                SELECT
                    ROW_NUMBER() OVER (ORDER BY period_month DESC, company_id) AS id,
                    period_month,
                    company_id,
                    COUNT(*) AS total_pickings,
                    SUM(CASE WHEN on_time THEN 1 ELSE 0 END) AS on_time_count,
                    ROUND(
                        SUM(CASE WHEN on_time THEN 1 ELSE 0 END)::numeric
                        / NULLIF(COUNT(*), 0) * 100, 2
                    ) AS otd_pct,
                    SUM(CASE WHEN otif THEN 1 ELSE 0 END) AS otif_count,
                    ROUND(
                        SUM(CASE WHEN otif THEN 1 ELSE 0 END)::numeric
                        / NULLIF(COUNT(*), 0) * 100, 2
                    ) AS otif_pct
                FROM pickings
                GROUP BY period_month, company_id
            )
        """ % self._table)


class WmsCcHrTurnover(models.Model):
    _name = 'wms.cc.hr.turnover'
    _description = 'CC — HR Turnover Summary'
    _auto = False
    _order = 'id'

    company_id = fields.Many2one('res.company', readonly=True)
    department_id = fields.Many2one('hr.department', readonly=True)
    active_count = fields.Integer(readonly=True, string='Active Employees')
    inactive_count = fields.Integer(readonly=True, string='Inactive')
    total_count = fields.Integer(readonly=True)
    turnover_pct = fields.Float(digits=(5, 2), readonly=True,
                                string='Turnover %')

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    ROW_NUMBER() OVER (ORDER BY department_id) AS id,
                    e.company_id,
                    e.department_id,
                    SUM(CASE WHEN e.active THEN 1 ELSE 0 END) AS active_count,
                    SUM(CASE WHEN NOT e.active THEN 1 ELSE 0 END) AS inactive_count,
                    COUNT(*) AS total_count,
                    ROUND(
                        SUM(CASE WHEN NOT e.active THEN 1 ELSE 0 END)::numeric
                        / NULLIF(COUNT(*), 0) * 100, 2
                    ) AS turnover_pct
                FROM hr_employee e
                GROUP BY e.company_id, e.department_id
            )
        """ % self._table)


class WmsCcTrainingLog(models.Model):
    _name = 'wms.cc.training.log'
    _description = 'CC — Training Session Log'
    _inherit = ['mail.thread']
    _order = 'training_date desc, id desc'

    name = fields.Char(required=True, string='Training Title')
    training_date = fields.Date(required=True,
                                default=fields.Date.context_today,
                                tracking=True)
    employee_id = fields.Many2one('hr.employee', required=True,
                                  string='Employee', tracking=True)
    department_id = fields.Many2one(related='employee_id.department_id',
                                    store=True)
    hours = fields.Float(required=True, default=1.0, digits=(10, 2),
                         tracking=True)
    training_type = fields.Selection([
        ('ojt',      '70% On-the-Job'),
        ('social',   '20% Social Learning'),
        ('formal',   '10% Formal Training'),
    ], default='ojt', required=True,
       help='70-20-10 integrated learning model')
    trainer = fields.Char(string='Trainer / Mentor')
    topic = fields.Char()
    notes = fields.Text()
    company_id = fields.Many2one('res.company',
                                 default=lambda self: self.env.company)
