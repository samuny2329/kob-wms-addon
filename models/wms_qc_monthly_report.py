"""WMS QC Monthly Report — automate "สร้าง QC Report รายเดือน"
(P2 High from Audit). Replaces "รวบรวม data defect/damage ทำ report ใน Excel"
manual process.

Model stores a monthly snapshot of QC metrics (from wms.quality.defect)
and the associated PDF (via report/wms_qc_monthly_report_template.xml).
Cron runs on the 1st of each month to generate last-month's report.
"""
from datetime import date

from odoo import models, fields, api, _


class WmsQcMonthlyReport(models.Model):
    _name = 'wms.qc.monthly.report'
    _description = 'WMS QC Monthly Report'
    _order = 'period_month desc'
    _rec_name = 'period_month'

    period_month = fields.Char(
        string='Period', required=True,
        help='e.g. "2026-04" (YYYY-MM)')
    period_start = fields.Date(string='Period Start', required=True)
    period_end = fields.Date(string='Period End', required=True)

    # Defect aggregates
    total_defects = fields.Integer(readonly=True)
    defects_by_type = fields.Text(readonly=True,
                                  help='JSON-like summary by defect_type')
    critical_defects = fields.Integer(readonly=True)
    high_defects = fields.Integer(readonly=True)
    closed_defects = fields.Integer(readonly=True)
    avg_resolution_days = fields.Float(readonly=True, digits=(10, 2))

    # Top offenders
    top_product_name = fields.Char(readonly=True)
    top_product_count = fields.Integer(readonly=True)

    defect_ids = fields.One2many(
        'wms.quality.defect', compute='_compute_defect_ids')
    defect_count = fields.Integer(compute='_compute_defect_ids')

    company_id = fields.Many2one('res.company',
                                 default=lambda self: self.env.company)

    _sql_constraints = [
        ('period_company_unique',
         'unique(period_month, company_id)',
         'Only one QC report per month per company.'),
    ]

    def _compute_defect_ids(self):
        Defect = self.env['wms.quality.defect'].sudo()
        for rec in self:
            if rec.period_start and rec.period_end:
                rec.defect_ids = Defect.search([
                    ('report_date', '>=', rec.period_start),
                    ('report_date', '<=', rec.period_end),
                ])
                rec.defect_count = len(rec.defect_ids)
            else:
                rec.defect_ids = False
                rec.defect_count = 0

    # ────────────────────────────────────────────────────────────────────
    # Build metrics for a period
    # ────────────────────────────────────────────────────────────────────
    def _compute_metrics(self):
        self.ensure_one()
        defects = self.env['wms.quality.defect'].sudo().search([
            ('report_date', '>=', self.period_start),
            ('report_date', '<=', self.period_end),
        ])
        by_type = {}
        for d in defects:
            key = dict(d._fields['defect_type'].selection).get(
                d.defect_type, d.defect_type or '?')
            by_type[key] = by_type.get(key, 0) + 1

        # Resolution days
        resolved = defects.filtered(lambda x: x.resolved_at and x.report_date)
        res_days = []
        for d in resolved:
            delta = (d.resolved_at - d.report_date).days
            if delta >= 0:
                res_days.append(delta)
        avg_res = sum(res_days) / len(res_days) if res_days else 0.0

        # Top product
        prod_counts = {}
        for d in defects:
            if d.product_id:
                prod_counts[d.product_id.id] = prod_counts.get(
                    d.product_id.id, 0) + 1
        top_pid, top_count = (None, 0)
        if prod_counts:
            top_pid, top_count = max(prod_counts.items(), key=lambda x: x[1])
        top_name = ''
        if top_pid:
            top_name = self.env['product.product'].browse(top_pid).display_name

        self.write({
            'total_defects': len(defects),
            'defects_by_type': str(by_type),
            'critical_defects': len(defects.filtered(
                lambda x: x.severity == 'critical')),
            'high_defects': len(defects.filtered(
                lambda x: x.severity == 'high')),
            'closed_defects': len(defects.filtered(
                lambda x: x.state == 'closed')),
            'avg_resolution_days': avg_res,
            'top_product_name': top_name,
            'top_product_count': top_count,
        })
        return True

    def action_regenerate(self):
        for rec in self:
            rec._compute_metrics()
        return True

    def action_print_pdf(self):
        self.ensure_one()
        return self.env.ref(
            'kob_wms.action_report_qc_monthly').report_action(self)

    # ────────────────────────────────────────────────────────────────────
    # Cron: generate last-month report on the 1st of each month
    # ────────────────────────────────────────────────────────────────────
    @api.model
    def cron_generate_monthly(self):
        today = fields.Date.context_today(self)
        # last month
        last_end = today.replace(day=1)
        # back up 1 day to get last day of prev month
        from datetime import timedelta
        last_end = last_end - timedelta(days=1)
        last_start = last_end.replace(day=1)
        period_month = last_end.strftime('%Y-%m')

        existing = self.sudo().search(
            [('period_month', '=', period_month)], limit=1)
        if existing:
            existing._compute_metrics()
            return existing

        report = self.sudo().create({
            'period_month': period_month,
            'period_start': last_start,
            'period_end': last_end,
        })
        report._compute_metrics()
        return report
