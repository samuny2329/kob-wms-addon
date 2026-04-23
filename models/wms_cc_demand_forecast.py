"""Command Center — Demand Forecasting (Supply Chain audit).

SQL view aggregating sale.order.line quantities over 30/60/90 days
per product to support SC Planner (Benz). Computes:
  - qty_30d, qty_60d, qty_90d
  - avg_daily (from 30d)
  - forecast_next_7d (7 × avg_daily)
  - forecast_next_30d

Replaces manual "ดูยอดขายย้อนหลัง + ประสบการณ์ / Excel" process
from the Notion Process Automation Audit (P1 Critical).
"""
from odoo import models, fields, tools


class WmsCcDemandForecast(models.Model):
    _name = 'wms.cc.demand.forecast'
    _description = 'CC — Demand Forecasting'
    _auto = False
    _order = 'qty_30d desc, product_id'

    product_id = fields.Many2one('product.product', readonly=True)
    product_code = fields.Char(readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    qty_30d = fields.Float(digits=(14, 2), readonly=True,
                           string='Sold Last 30d')
    qty_60d = fields.Float(digits=(14, 2), readonly=True,
                           string='Sold Last 60d')
    qty_90d = fields.Float(digits=(14, 2), readonly=True,
                           string='Sold Last 90d')
    avg_daily = fields.Float(digits=(14, 2), readonly=True,
                             string='Avg Daily (30d)')
    forecast_7d = fields.Float(digits=(14, 2), readonly=True,
                               string='Forecast Next 7d')
    forecast_30d = fields.Float(digits=(14, 2), readonly=True,
                                string='Forecast Next 30d')
    trend_pct = fields.Float(digits=(5, 2), readonly=True,
                             string='Trend %',
                             help='Change of last 30d vs prior 30d — '
                                  'positive = increasing demand')
    current_stock = fields.Float(digits=(14, 2), readonly=True,
                                 string='Current Stock')
    days_of_stock = fields.Float(digits=(10, 1), readonly=True,
                                 help='How many days current stock will last '
                                      'at the 30d avg rate')

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                WITH d30 AS (
                    SELECT sol.product_id, so.company_id,
                           SUM(sol.product_uom_qty) AS qty
                    FROM sale_order_line sol
                    JOIN sale_order so ON so.id = sol.order_id
                    WHERE so.date_order >= NOW() - INTERVAL '30 days'
                      AND so.state IN ('sale', 'done')
                    GROUP BY sol.product_id, so.company_id
                ),
                d60 AS (
                    SELECT sol.product_id, so.company_id,
                           SUM(sol.product_uom_qty) AS qty
                    FROM sale_order_line sol
                    JOIN sale_order so ON so.id = sol.order_id
                    WHERE so.date_order >= NOW() - INTERVAL '60 days'
                      AND so.state IN ('sale', 'done')
                    GROUP BY sol.product_id, so.company_id
                ),
                d90 AS (
                    SELECT sol.product_id, so.company_id,
                           SUM(sol.product_uom_qty) AS qty
                    FROM sale_order_line sol
                    JOIN sale_order so ON so.id = sol.order_id
                    WHERE so.date_order >= NOW() - INTERVAL '90 days'
                      AND so.state IN ('sale', 'done')
                    GROUP BY sol.product_id, so.company_id
                ),
                prev30 AS (
                    -- previous 30d (31-60 days ago) — for trend
                    SELECT sol.product_id, so.company_id,
                           SUM(sol.product_uom_qty) AS qty
                    FROM sale_order_line sol
                    JOIN sale_order so ON so.id = sol.order_id
                    WHERE so.date_order >= NOW() - INTERVAL '60 days'
                      AND so.date_order < NOW() - INTERVAL '30 days'
                      AND so.state IN ('sale', 'done')
                    GROUP BY sol.product_id, so.company_id
                ),
                stk AS (
                    SELECT q.product_id, q.company_id,
                           SUM(q.quantity) AS stock
                    FROM stock_quant q
                    JOIN stock_location sl ON sl.id = q.location_id
                    WHERE sl.usage = 'internal'
                    GROUP BY q.product_id, q.company_id
                )
                SELECT
                    ROW_NUMBER() OVER (
                        ORDER BY d30.qty DESC NULLS LAST, d30.product_id
                    ) AS id,
                    d30.product_id,
                    pt.default_code AS product_code,
                    d30.company_id,
                    d30.qty                            AS qty_30d,
                    COALESCE(d60.qty, d30.qty)         AS qty_60d,
                    COALESCE(d90.qty, d30.qty)         AS qty_90d,
                    ROUND((d30.qty / 30.0)::numeric, 2) AS avg_daily,
                    ROUND((d30.qty * 7.0 / 30.0)::numeric, 2) AS forecast_7d,
                    d30.qty                            AS forecast_30d,
                    CASE
                        WHEN COALESCE(prev30.qty, 0) > 0 THEN
                            ROUND(((d30.qty - prev30.qty) / prev30.qty * 100)::numeric, 2)
                        ELSE NULL
                    END AS trend_pct,
                    COALESCE(stk.stock, 0) AS current_stock,
                    CASE
                        WHEN d30.qty > 0 THEN
                            ROUND((COALESCE(stk.stock, 0) / (d30.qty / 30.0))::numeric, 1)
                        ELSE 999
                    END AS days_of_stock
                FROM d30
                JOIN product_product pp  ON pp.id = d30.product_id
                JOIN product_template pt ON pt.id = pp.product_tmpl_id
                LEFT JOIN d60 ON d60.product_id = d30.product_id AND d60.company_id = d30.company_id
                LEFT JOIN d90 ON d90.product_id = d30.product_id AND d90.company_id = d30.company_id
                LEFT JOIN prev30 ON prev30.product_id = d30.product_id AND prev30.company_id = d30.company_id
                LEFT JOIN stk ON stk.product_id = d30.product_id AND stk.company_id = d30.company_id
                WHERE d30.qty > 0
            )
        """ % self._table)
