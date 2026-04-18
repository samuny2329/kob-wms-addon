from odoo import models, fields, tools


class WmsWorkerPerformance(models.Model):
    """SQL view: daily worker KPI with error rate, difficulty, score.

    Primary grouping is by kob.wms.user (PIN-login worker).
    Records without a kob worker (old data / admin-direct scans) are grouped
    separately under the Odoo user as a fallback.
    """
    _name = 'wms.worker.performance'
    _description = 'WMS Worker Daily Performance'
    _auto = False
    _order = 'date desc, kob_user_id'

    date = fields.Date(string='Date', readonly=True)
    # Primary: kob.wms.user (picker, packer …)
    kob_user_id = fields.Many2one('kob.wms.user', string='Employee', readonly=True)
    # Fallback: res.users (shows when kob_user_id is NULL — e.g. old records)
    user_id = fields.Many2one('res.users', string='Odoo User', readonly=True)

    # Action counts
    pick_count = fields.Integer(string='Picks', readonly=True)
    pack_count = fields.Integer(string='Packs', readonly=True)
    box_count = fields.Integer(string='Boxes', readonly=True)
    ship_count = fields.Integer(string='Ships', readonly=True)
    scan_count = fields.Integer(string='Scans', readonly=True)
    dispatch_count = fields.Integer(string='Dispatches', readonly=True)
    total_actions = fields.Integer(string='Total Actions', readonly=True)

    # Error counts
    pick_errors = fields.Integer(string='Pick Errors', readonly=True)
    pack_errors = fields.Integer(string='Pack Errors', readonly=True)
    total_errors = fields.Integer(string='Total Errors', readonly=True)

    # Rates
    uph = fields.Float(string='UPH (8h)', readonly=True, digits=(10, 2))
    error_rate = fields.Float(string='Error Rate %', readonly=True, digits=(5, 2))
    quality_score = fields.Float(string='Quality %', readonly=True, digits=(5, 2))

    # Worker Score (computed in SQL)
    worker_score = fields.Float(string='Worker Score', readonly=True, digits=(10, 2),
                                help='UPH × Quality% / 100')

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                WITH kob_actions AS (
                    -- ── Group 1: kob.wms.user rows (real worker attribution) ──
                    SELECT
                        date_trunc('day', create_date)::date AS date,
                        kob_user_id,
                        NULL::integer                        AS user_id,
                        COUNT(*) FILTER (WHERE action = 'pick')       AS pick_count,
                        COUNT(*) FILTER (WHERE action = 'pack')       AS pack_count,
                        COUNT(*) FILTER (WHERE action = 'box')        AS box_count,
                        COUNT(*) FILTER (WHERE action = 'ship')       AS ship_count,
                        COUNT(*) FILTER (WHERE action = 'scan')       AS scan_count,
                        COUNT(*) FILTER (WHERE action = 'dispatch')   AS dispatch_count,
                        COUNT(*) FILTER (WHERE action = 'error_pick') AS pick_errors,
                        COUNT(*) FILTER (WHERE action = 'error_pack') AS pack_errors,
                        COUNT(*) FILTER (WHERE action NOT IN
                            ('error_pick','error_pack','login','logout','other'))
                                AS total_actions,
                        COUNT(*) FILTER (WHERE action IN ('error_pick','error_pack'))
                                AS total_errors
                    FROM wms_activity_log
                    WHERE kob_user_id IS NOT NULL
                    GROUP BY date_trunc('day', create_date), kob_user_id

                    UNION ALL

                    -- ── Group 2: Odoo-user fallback (no kob worker set) ──
                    SELECT
                        date_trunc('day', create_date)::date AS date,
                        NULL::integer                        AS kob_user_id,
                        user_id,
                        COUNT(*) FILTER (WHERE action = 'pick')       AS pick_count,
                        COUNT(*) FILTER (WHERE action = 'pack')       AS pack_count,
                        COUNT(*) FILTER (WHERE action = 'box')        AS box_count,
                        COUNT(*) FILTER (WHERE action = 'ship')       AS ship_count,
                        COUNT(*) FILTER (WHERE action = 'scan')       AS scan_count,
                        COUNT(*) FILTER (WHERE action = 'dispatch')   AS dispatch_count,
                        COUNT(*) FILTER (WHERE action = 'error_pick') AS pick_errors,
                        COUNT(*) FILTER (WHERE action = 'error_pack') AS pack_errors,
                        COUNT(*) FILTER (WHERE action NOT IN
                            ('error_pick','error_pack','login','logout','other'))
                                AS total_actions,
                        COUNT(*) FILTER (WHERE action IN ('error_pick','error_pack'))
                                AS total_errors
                    FROM wms_activity_log
                    WHERE kob_user_id IS NULL AND user_id IS NOT NULL
                    GROUP BY date_trunc('day', create_date), user_id
                )
                SELECT
                    -- Unique row ID: kob rows use kob_user_id slot; fallback uses 50000+user_id
                    CASE
                        WHEN kob_user_id IS NOT NULL
                            THEN (EXTRACT(EPOCH FROM date)::bigint * 100000 + kob_user_id)
                        ELSE     (EXTRACT(EPOCH FROM date)::bigint * 100000 + 50000 + user_id)
                    END AS id,
                    date,
                    kob_user_id,
                    user_id,
                    pick_count,
                    pack_count,
                    box_count,
                    ship_count,
                    scan_count,
                    dispatch_count,
                    total_actions,
                    pick_errors,
                    pack_errors,
                    total_errors,
                    ROUND(total_actions::numeric / 8.0, 2) AS uph,
                    CASE WHEN (total_actions + total_errors) > 0
                        THEN ROUND(total_errors::numeric / (total_actions + total_errors) * 100, 2)
                        ELSE 0 END AS error_rate,
                    CASE WHEN (total_actions + total_errors) > 0
                        THEN ROUND((1 - total_errors::numeric / (total_actions + total_errors)) * 100, 2)
                        ELSE 100 END AS quality_score,
                    CASE WHEN (total_actions + total_errors) > 0
                        THEN ROUND(
                            (total_actions::numeric / 8.0) *
                            (1 - total_errors::numeric / (total_actions + total_errors)) * 100
                        , 2)
                        ELSE 0 END AS worker_score
                FROM kob_actions
            )
        """)
