"""Command Center — Accounting Hub + OpEx Tracker + Platform Fee Audit.

Three SQL views for Sr WH Accounting Officer (Nuch):

1. wms.cc.accounting.hub
   Filter account.move where partner.ref = 'ECOMMERCE' (or similar flag)
   Group revenue vs 405xxx fees vs 603xxx fees.

2. wms.cc.opex.tracker
   Monthly aggregation of 603xxx account lines (vendor bill fees).

3. wms.cc.platform.fee.audit
   Per platform (Shopee / Lazada / TikTok): total orders value,
   expected commission %, actual commission booked. Highlights variance.
"""
from odoo import models, fields, tools


class WmsCcAccountingHub(models.Model):
    _name = 'wms.cc.accounting.hub'
    _description = 'CC — Accounting Hub (ECOMMERCE revenue + fees)'
    _auto = False
    _order = 'date desc, id desc'

    date = fields.Date(readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    partner_id = fields.Many2one('res.partner', readonly=True)
    account_id = fields.Many2one('account.account', readonly=True)
    account_code = fields.Char(readonly=True)
    account_type = fields.Char(readonly=True,
                               help='revenue / customer_fee_405 / vendor_fee_603 / other')
    move_id = fields.Many2one('account.move', readonly=True)
    move_name = fields.Char(readonly=True)
    amount = fields.Float(digits=(14, 2), readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    ROW_NUMBER() OVER (ORDER BY am.date DESC, aml.id) AS id,
                    am.date,
                    am.company_id,
                    am.partner_id,
                    aml.account_id,
                    (aa.code_store->>am.company_id::text) AS account_code,
                    CASE
                        WHEN (aa.code_store->>am.company_id::text) LIKE '405%%' THEN 'customer_fee_405'
                        WHEN (aa.code_store->>am.company_id::text) LIKE '603%%' THEN 'vendor_fee_603'
                        WHEN (aa.code_store->>am.company_id::text) LIKE '4%%' THEN 'revenue'
                        ELSE 'other'
                    END AS account_type,
                    am.id AS move_id,
                    am.name AS move_name,
                    (aml.debit - aml.credit) AS amount
                FROM account_move_line aml
                JOIN account_move am ON am.id = aml.move_id
                JOIN account_account aa ON aa.id = aml.account_id
                WHERE am.state = 'posted'
                  AND am.date >= NOW() - INTERVAL '365 days'
                  AND ((aa.code_store->>am.company_id::text) LIKE '4%%' OR (aa.code_store->>am.company_id::text) LIKE '603%%')
            )
        """ % self._table)


class WmsCcOpexTracker(models.Model):
    _name = 'wms.cc.opex.tracker'
    _description = 'CC — OpEx Monthly Tracker'
    _auto = False
    _order = 'period_month desc, account_code'

    period_month = fields.Char(readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    account_id = fields.Many2one('account.account', readonly=True)
    account_code = fields.Char(readonly=True)
    account_name = fields.Char(readonly=True)
    total_amount = fields.Float(digits=(14, 2), readonly=True,
                                string='Total OpEx')
    line_count = fields.Integer(readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    ROW_NUMBER() OVER (
                        ORDER BY TO_CHAR(am.date, 'YYYY-MM') DESC, (aa.code_store->>am.company_id::text)
                    ) AS id,
                    TO_CHAR(am.date, 'YYYY-MM') AS period_month,
                    am.company_id,
                    aa.id AS account_id,
                    (aa.code_store->>am.company_id::text) AS account_code,
                    aa.name::text AS account_name,
                    SUM(aml.debit - aml.credit) AS total_amount,
                    COUNT(aml.id) AS line_count
                FROM account_move_line aml
                JOIN account_move am ON am.id = aml.move_id
                JOIN account_account aa ON aa.id = aml.account_id
                WHERE am.state = 'posted'
                  AND (aa.code_store->>am.company_id::text) LIKE '603%%'
                  AND am.date >= NOW() - INTERVAL '24 months'
                GROUP BY TO_CHAR(am.date, 'YYYY-MM'), am.company_id,
                         aa.id, (aa.code_store->>am.company_id::text), aa.name
            )
        """ % self._table)


class WmsCcPlatformFeeAudit(models.Model):
    """Aggregates 405xxx platform fee accounts per platform."""
    _name = 'wms.cc.platform.fee.audit'
    _description = 'CC — Platform Fee Audit'
    _auto = False
    _order = 'period_month desc, platform_label'

    period_month = fields.Char(readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    platform_label = fields.Char(readonly=True)
    account_code = fields.Char(readonly=True)
    fee_amount = fields.Float(digits=(14, 2), readonly=True,
                              string='Fee Booked')
    line_count = fields.Integer(readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    ROW_NUMBER() OVER (
                        ORDER BY TO_CHAR(am.date, 'YYYY-MM') DESC, (aa.code_store->>am.company_id::text)
                    ) AS id,
                    TO_CHAR(am.date, 'YYYY-MM') AS period_month,
                    am.company_id,
                    CASE (aa.code_store->>am.company_id::text)
                        WHEN '405101' THEN 'Shopee'
                        WHEN '405102' THEN 'Lazada'
                        WHEN '405103' THEN 'TikTok'
                        WHEN '405104' THEN 'Odoo'
                        WHEN '405105' THEN 'POS'
                        WHEN '405106' THEN 'Manual'
                        ELSE (aa.code_store->>am.company_id::text)
                    END AS platform_label,
                    (aa.code_store->>am.company_id::text) AS account_code,
                    SUM(ABS(aml.debit - aml.credit)) AS fee_amount,
                    COUNT(aml.id) AS line_count
                FROM account_move_line aml
                JOIN account_move am ON am.id = aml.move_id
                JOIN account_account aa ON aa.id = aml.account_id
                WHERE am.state = 'posted'
                  AND (aa.code_store->>am.company_id::text) LIKE '405%%'
                  AND am.date >= NOW() - INTERVAL '12 months'
                GROUP BY TO_CHAR(am.date, 'YYYY-MM'), am.company_id,
                         (aa.code_store->>am.company_id::text)
            )
        """ % self._table)
