"""WMS KPI Alert Rule Engine — automate "Alert เมื่อ KPI เข้าเงื่อนไข Trigger"
(P1 Critical from Audit). Replaces "ไม่มีระบบ alert / BI ดูเองแล้วแจ้ง LINE".

Define rules like:
  - "SLA Pick Pct < 90 daily" → post chatter to Supervisor group
  - "Defect Count >= 5 weekly" → alert Manager
  - "Platform sync errors > 3 daily" → escalate to Director

Cron evaluates all active rules once per day. Each rule has its own
frequency filter (daily / weekly / monthly) so rules only fire when
their period just closed.
"""
from datetime import timedelta

from odoo import models, fields, api, _


METRIC_SEL = [
    # Orders / SLA
    ('total_orders',       'Total Orders (day)'),
    ('shipped_orders',     'Shipped Orders (day)'),
    ('pending_orders',     'Pending Orders (day)'),
    ('cancelled_orders',   'Cancelled Orders (day)'),
    ('sla_pick_pct',       'SLA Pick Compliance %'),
    ('sla_pack_pct',       'SLA Pack Compliance %'),
    ('avg_pick_min',       'Avg Pick Duration (min)'),
    ('avg_pack_min',       'Avg Pack Duration (min)'),
    # Quality
    ('defect_count',       'Defect Count (day)'),
    ('expiry_alert_count', 'Expiry Alerts (day)'),
    # Platform
    ('platform_sync_errors', 'Platform Sync Errors'),
]

OPERATOR_SEL = [
    ('gte', '≥ (greater or equal)'),
    ('gt',  '> (greater)'),
    ('lte', '≤ (less or equal)'),
    ('lt',  '< (less)'),
    ('eq',  '= (equal)'),
]

FREQUENCY_SEL = [
    ('daily',   'Daily'),
    ('weekly',  'Weekly'),
    ('monthly', 'Monthly'),
]

CHANNEL_SEL = [
    ('chatter', '💬 Chatter'),
    ('activity','📋 Activity'),
    ('email',   '📧 Email'),
]


def _apply(op, value, threshold):
    if value is None:
        return False
    if op == 'gte': return value >= threshold
    if op == 'gt':  return value > threshold
    if op == 'lte': return value <= threshold
    if op == 'lt':  return value < threshold
    if op == 'eq':  return abs(value - threshold) < 0.001
    return False


class WmsKpiAlertRule(models.Model):
    _name = 'wms.kpi.alert.rule'
    _description = 'KPI Alert Rule'
    _inherit = ['mail.thread']
    _order = 'sequence, id'

    name = fields.Char(required=True, tracking=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True, tracking=True)
    metric_code = fields.Selection(METRIC_SEL, required=True, tracking=True)
    operator = fields.Selection(OPERATOR_SEL, required=True, default='lt',
                                tracking=True)
    threshold = fields.Float(required=True, default=0.0, digits=(12, 2),
                             tracking=True)
    frequency = fields.Selection(FREQUENCY_SEL, required=True, default='daily',
                                 tracking=True)
    notify_channel = fields.Selection(CHANNEL_SEL, default='chatter',
                                      required=True)
    notify_group_id = fields.Many2one(
        'res.groups', string='Notify Group',
        default=lambda self: self.env.ref(
            'kob_wms.group_wms_supervisor', raise_if_not_found=False),
        help='All users of this group will receive the alert')
    description = fields.Text(help='Context for the alert (what does a breach mean?)')

    # ── Statistics ──────────────────────────────────────────────────────
    last_evaluated_at = fields.Datetime(readonly=True)
    last_value = fields.Float(readonly=True, digits=(12, 2))
    last_triggered_at = fields.Datetime(readonly=True, tracking=True)
    trigger_count = fields.Integer(readonly=True, default=0)

    company_id = fields.Many2one('res.company',
                                 default=lambda self: self.env.company)

    # ────────────────────────────────────────────────────────────────────
    # Evaluation
    # ────────────────────────────────────────────────────────────────────
    def _metric_value(self, as_of_date):
        """Compute the metric value for the period ending `as_of_date`."""
        self.ensure_one()
        # Determine period start
        if self.frequency == 'daily':
            start = as_of_date
        elif self.frequency == 'weekly':
            start = as_of_date - timedelta(days=6)
        else:  # monthly
            start = as_of_date.replace(day=1)

        start_dt = fields.Datetime.to_datetime(start)
        end_dt = fields.Datetime.to_datetime(as_of_date) + timedelta(days=1)
        env = self.env

        # For most metrics, we can use wms.daily.report aggregates
        Daily = env['wms.daily.report'].sudo()
        reports = Daily.search([
            ('report_date', '>=', start),
            ('report_date', '<=', as_of_date),
        ])

        if self.metric_code in (
                'total_orders', 'shipped_orders', 'pending_orders',
                'cancelled_orders', 'defect_count', 'expiry_alert_count'):
            return sum(reports.mapped(self.metric_code))

        if self.metric_code in ('sla_pick_pct', 'sla_pack_pct'):
            if not reports:
                return None
            return sum(reports.mapped(self.metric_code)) / len(reports)

        if self.metric_code in ('avg_pick_min', 'avg_pack_min'):
            if not reports:
                return None
            return sum(reports.mapped(self.metric_code)) / len(reports)

        if self.metric_code == 'platform_sync_errors':
            return sum(env['wms.api.config'].sudo().search(
                [('enabled', '=', True)]
            ).mapped('sync_errors'))

        return None

    def _format_value(self, val):
        if val is None:
            return '—'
        if self.metric_code.endswith('_pct'):
            return '%.1f%%' % val
        if self.metric_code.endswith('_min'):
            return '%.1f min' % val
        return '%.2f' % val if isinstance(val, float) else str(val)

    def _should_fire_today(self, as_of_date):
        """Return True only when the period just closed."""
        if self.frequency == 'daily':
            return True
        if self.frequency == 'weekly':
            # Fire on Monday (week just ended yesterday)
            return as_of_date.weekday() == 0
        if self.frequency == 'monthly':
            # Fire on 1st (previous month just ended)
            return as_of_date.day == 1
        return False

    def _notify_breach(self, value, period_label):
        """Send alert via configured channel."""
        self.ensure_one()
        metric_name = dict(self._fields['metric_code'].selection).get(
            self.metric_code, self.metric_code)
        op_name = dict(self._fields['operator'].selection).get(
            self.operator, self.operator)
        body = _(
            '🚨 <b>KPI Alert: %s</b><br/>'
            'Metric: <b>%s</b><br/>'
            'Current: <b>%s</b> %s <b>%s</b> (threshold)<br/>'
            'Period: %s<br/>'
            '%s'
        ) % (self.name, metric_name, self._format_value(value),
             op_name, self._format_value(self.threshold),
             period_label,
             self.description or '')

        partner_ids = []
        if self.notify_group_id:
            for u in self.notify_group_id.users:
                if u.partner_id:
                    partner_ids.append(u.partner_id.id)

        self.message_post(
            body=body,
            subject=_('KPI Alert: %s') % self.name,
            partner_ids=partner_ids,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

        if self.notify_channel == 'activity' and self.notify_group_id:
            for u in self.notify_group_id.users[:3]:  # cap at 3
                self.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=u.id,
                    summary=_('KPI Alert: %s') % self.name,
                    note=body,
                )

    def action_evaluate(self):
        """Manual evaluate button."""
        today = fields.Date.context_today(self)
        for rec in self:
            rec._evaluate_one(today, force=True)
        return True

    def _evaluate_one(self, as_of_date, force=False):
        self.ensure_one()
        if not self.active and not force:
            return False
        if not force and not self._should_fire_today(as_of_date):
            return False

        value = self._metric_value(as_of_date)
        self.last_value = value if value is not None else 0
        self.last_evaluated_at = fields.Datetime.now()

        if _apply(self.operator, value, self.threshold):
            period_label = {
                'daily':   as_of_date.strftime('%Y-%m-%d'),
                'weekly':  'Week ending %s' % as_of_date.strftime('%Y-%m-%d'),
                'monthly': as_of_date.strftime('%Y-%m'),
            }.get(self.frequency, '')
            self._notify_breach(value, period_label)
            self.last_triggered_at = fields.Datetime.now()
            self.trigger_count = (self.trigger_count or 0) + 1
            return True
        return False

    # ────────────────────────────────────────────────────────────────────
    # Cron
    # ────────────────────────────────────────────────────────────────────
    @api.model
    def cron_evaluate_all(self):
        today = fields.Date.context_today(self)
        rules = self.sudo().search([('active', '=', True)])
        fired = 0
        for rule in rules:
            if rule._evaluate_one(today):
                fired += 1
        return {'evaluated': len(rules), 'fired': fired}
