"""WMS Daily Sales Report — automate "สร้าง Daily Sales Report"
(P1 Critical from Audit). Replaces "รวม data จากหลาย source ใน Excel
แล้วส่ง LINE/Email" manual process.

Cron runs at 07:00 daily → creates a wms.daily.report record for
yesterday, computes sales + fulfilment metrics, and emails it to all
active supervisors + managers.
"""
from datetime import timedelta

from odoo import models, fields, api, _


class WmsDailyReport(models.Model):
    _name = 'wms.daily.report'
    _description = 'WMS Daily Sales & Fulfilment Report'
    _inherit = ['mail.thread']
    _order = 'report_date desc'
    _rec_name = 'report_date'

    report_date = fields.Date(string='Report Date', required=True,
                              default=fields.Date.context_today)
    # Order metrics (from wms.sales.order)
    total_orders = fields.Integer(readonly=True)
    shipped_orders = fields.Integer(readonly=True)
    cancelled_orders = fields.Integer(readonly=True)
    pending_orders = fields.Integer(readonly=True)

    total_qty = fields.Float(readonly=True, digits=(12, 2))
    total_value = fields.Float(readonly=True, digits=(14, 2))

    # Platform breakdown
    shopee_orders = fields.Integer(readonly=True)
    lazada_orders = fields.Integer(readonly=True)
    tiktok_orders = fields.Integer(readonly=True)
    odoo_orders = fields.Integer(readonly=True)

    # SLA metrics
    avg_pick_min = fields.Float(readonly=True, digits=(10, 2))
    avg_pack_min = fields.Float(readonly=True, digits=(10, 2))
    sla_pick_pct = fields.Float(readonly=True, digits=(5, 2))
    sla_pack_pct = fields.Float(readonly=True, digits=(5, 2))

    # Quality metrics
    defect_count = fields.Integer(readonly=True)
    expiry_alert_count = fields.Integer(readonly=True)

    body_html = fields.Html(readonly=True, sanitize=False)
    company_id = fields.Many2one('res.company',
                                 default=lambda self: self.env.company)

    _sql_constraints = [
        ('report_date_company_unique',
         'unique(report_date, company_id)',
         'Only one daily report per day per company.'),
    ]

    # ────────────────────────────────────────────────────────────────────
    # Compute report metrics for a date
    # ────────────────────────────────────────────────────────────────────
    def _compute_metrics(self, for_date):
        env = self.env
        date_from = fields.Datetime.to_datetime(for_date)
        date_to = date_from + timedelta(days=1)

        SO = env['wms.sales.order'].sudo()
        base_domain = [
            ('create_date', '>=', date_from),
            ('create_date', '<', date_to),
        ]
        orders = SO.search(base_domain)
        shipped = orders.filtered(lambda o: o.status == 'shipped')
        cancelled = orders.filtered(lambda o: o.status == 'cancelled')
        pending = orders.filtered(
            lambda o: o.status in ('pending', 'picking', 'picked', 'packing'))

        def _count_platform(platform):
            return len(orders.filtered(
                lambda o: getattr(o, 'platform', None) == platform))

        metrics = {
            'total_orders': len(orders),
            'shipped_orders': len(shipped),
            'cancelled_orders': len(cancelled),
            'pending_orders': len(pending),
            'shopee_orders': _count_platform('shopee'),
            'lazada_orders': _count_platform('lazada'),
            'tiktok_orders': _count_platform('tiktok'),
            'odoo_orders': _count_platform('odoo'),
        }

        # Value & qty
        sale_orders = orders.mapped('sale_order_id')
        metrics['total_value'] = sum(sale_orders.mapped('amount_total'))
        try:
            metrics['total_qty'] = sum(
                line.qty_picked or 0
                for o in orders for line in getattr(o, 'line_ids', [])
            )
        except Exception:
            metrics['total_qty'] = 0.0

        # SLA (if fields exist)
        if 'pick_duration_min' in SO._fields:
            pick_mins = [o.pick_duration_min for o in shipped
                         if o.pick_duration_min]
            metrics['avg_pick_min'] = (
                sum(pick_mins) / len(pick_mins)) if pick_mins else 0
            compliant_pick = sum(1 for m in pick_mins if m <= 120)
            metrics['sla_pick_pct'] = (
                compliant_pick / len(pick_mins) * 100) if pick_mins else 0
        if 'pack_duration_min' in SO._fields:
            pack_mins = [o.pack_duration_min for o in shipped
                         if o.pack_duration_min]
            metrics['avg_pack_min'] = (
                sum(pack_mins) / len(pack_mins)) if pack_mins else 0
            compliant_pack = sum(1 for m in pack_mins if m <= 60)
            metrics['sla_pack_pct'] = (
                compliant_pack / len(pack_mins) * 100) if pack_mins else 0

        # Quality
        metrics['defect_count'] = env['wms.quality.defect'].sudo().search_count([
            ('report_date', '>=', date_from),
            ('report_date', '<', date_to),
        ])
        metrics['expiry_alert_count'] = env['wms.expiry.alert'].sudo().search_count([
            ('alert_date', '=', for_date),
        ])

        return metrics

    def _render_body_html(self, m, for_date):
        return """
        <h2>📊 Daily WMS Report — {date}</h2>
        <h3>📦 Order Summary</h3>
        <ul>
          <li><b>Total Orders:</b> {total_orders}</li>
          <li>✅ Shipped: {shipped_orders} · ⏳ Pending: {pending_orders} · ❌ Cancelled: {cancelled_orders}</li>
          <li><b>Total Value:</b> ฿{total_value:,.2f}</li>
        </ul>
        <h3>🌐 Platform Breakdown</h3>
        <ul>
          <li>Shopee: {shopee_orders} · Lazada: {lazada_orders} · TikTok: {tiktok_orders} · Odoo: {odoo_orders}</li>
        </ul>
        <h3>⏱️ SLA Compliance</h3>
        <ul>
          <li>Avg Pick: {avg_pick_min:.1f} min · SLA Pass: {sla_pick_pct:.1f}%</li>
          <li>Avg Pack: {avg_pack_min:.1f} min · SLA Pass: {sla_pack_pct:.1f}%</li>
        </ul>
        <h3>🎯 Quality</h3>
        <ul>
          <li>Defects reported: {defect_count}</li>
          <li>Expiry alerts: {expiry_alert_count}</li>
        </ul>
        <hr/>
        <p style="font-size:11px;color:#888">Auto-generated by KOB WMS · Daily Sales Report Cron</p>
        """.format(date=for_date, **m)

    # ────────────────────────────────────────────────────────────────────
    # Cron: generate yesterday's report at 07:00
    # ────────────────────────────────────────────────────────────────────
    @api.model
    def cron_generate_daily_report(self):
        today = fields.Date.context_today(self)
        yesterday = today - timedelta(days=1)

        existing = self.sudo().search([('report_date', '=', yesterday)], limit=1)
        if existing:
            return existing

        metrics = self._compute_metrics(yesterday)
        body = self._render_body_html(metrics, yesterday)

        report = self.sudo().create({
            'report_date': yesterday,
            'body_html': body,
            **metrics,
        })

        # Email to supervisors + managers
        report._notify_recipients(body, yesterday)
        return report

    def _notify_recipients(self, body, for_date):
        recipient_groups = [
            self.env.ref('kob_wms.group_wms_supervisor',
                         raise_if_not_found=False),
            self.env.ref('kob_wms.group_wms_manager',
                         raise_if_not_found=False),
        ]
        recipient_ids = set()
        for g in recipient_groups:
            if g:
                for user in g.users:
                    if user.partner_id:
                        recipient_ids.add(user.partner_id.id)
        if not recipient_ids:
            return

        self.ensure_one()
        self.message_post(
            body=body,
            subject=_('📊 Daily WMS Report — %s') % for_date,
            partner_ids=list(recipient_ids),
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

    def action_regenerate(self):
        """Manual regeneration button."""
        self.ensure_one()
        metrics = self._compute_metrics(self.report_date)
        self.write({
            'body_html': self._render_body_html(metrics, self.report_date),
            **metrics,
        })
        return True
