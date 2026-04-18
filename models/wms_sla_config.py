# -*- coding: utf-8 -*-
from odoo import models, fields, api
from datetime import timedelta


class WmsSlaConfig(models.Model):
    """SLA thresholds per platform + break time deduction + Hard/Soft SLA toggle."""
    _name = 'wms.sla.config'
    _description = 'WMS SLA Configuration'
    _rec_name = 'platform'

    platform = fields.Selection([
        ('odoo', 'Odoo'),
        ('shopee', 'Shopee'),
        ('lazada', 'Lazada'),
        ('tiktok', 'TikTok'),
        ('pos', 'Point of Sale'),
        ('manual', 'Manual'),
        ('default', 'Default (fallback)'),
    ], string='Platform', required=True, default='default')

    # ── Soft SLA (daily average) ──────────────────────────────────────
    soft_sla_enabled = fields.Boolean('Soft SLA (Daily Avg)', default=True,
        help='Alert when daily average OCT exceeds target')
    soft_sla_avg_oct_min = fields.Integer('Avg OCT Target (min)', default=90,
        help='Target: average Order Cycle Time per day must stay below this')

    # ── Hard SLA (per order) ──────────────────────────────────────────
    hard_sla_enabled = fields.Boolean('Hard SLA (Per Order)', default=False,
        help='Every single order must complete within the limit')
    pick_sla_minutes = fields.Integer('Pick SLA (min)', default=120)
    pack_sla_minutes = fields.Integer('Pack SLA (min)', default=60)
    ship_sla_minutes = fields.Integer('Ship SLA (min)', default=240)

    # ── Working hours ─────────────────────────────────────────────────
    working_start = fields.Float('Work Start', default=8.0,
        help='e.g. 8.0 = 08:00')
    working_end = fields.Float('Work End', default=17.0,
        help='e.g. 17.0 = 17:00')

    # ── Break periods (float hour, e.g. 10.1667 = 10:10) ─────────────
    break_am_enabled = fields.Boolean('Morning Break', default=True)
    break_am_start = fields.Float('Start', default=10.0)
    break_am_end = fields.Float('End', default=10.1667)   # 10:10

    break_lunch_enabled = fields.Boolean('Lunch Break', default=True)
    break_lunch_start = fields.Float('Start', default=12.0)
    break_lunch_end = fields.Float('End', default=13.0)

    break_pm_enabled = fields.Boolean('Afternoon Break', default=True)
    break_pm_start = fields.Float('Start', default=15.0)
    break_pm_end = fields.Float('End', default=15.1667)   # 15:10

    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company,
    )

    _sql_constraints = [
        ('platform_company_unique', 'unique(platform, company_id)',
         'One SLA configuration per platform per company.'),
    ]

    # ── Helpers ───────────────────────────────────────────────────────

    def _get_breaks(self):
        """Return list of (start_hour, end_hour) for enabled breaks."""
        self.ensure_one()
        breaks = []
        if self.break_am_enabled and self.break_am_end > self.break_am_start:
            breaks.append((self.break_am_start, self.break_am_end))
        if self.break_lunch_enabled and self.break_lunch_end > self.break_lunch_start:
            breaks.append((self.break_lunch_start, self.break_lunch_end))
        if self.break_pm_enabled and self.break_pm_end > self.break_pm_start:
            breaks.append((self.break_pm_start, self.break_pm_end))
        return breaks

    def net_working_minutes(self, start_dt, end_dt):
        """
        Calculate net working minutes between two datetimes,
        subtracting break periods on each calendar day.
        """
        self.ensure_one()
        if not start_dt or not end_dt or end_dt <= start_dt:
            return 0.0

        total = (end_dt - start_dt).total_seconds() / 60.0
        breaks = self._get_breaks()
        if not breaks:
            return round(total, 1)

        # Iterate each calendar day in the interval
        day = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end_day = end_dt.replace(hour=0, minute=0, second=0, microsecond=0)

        while day <= end_day:
            for brk_h_start, brk_h_end in breaks:
                brk_start = day + timedelta(hours=brk_h_start)
                brk_end = day + timedelta(hours=brk_h_end)
                overlap_start = max(start_dt, brk_start)
                overlap_end = min(end_dt, brk_end)
                if overlap_end > overlap_start:
                    total -= (overlap_end - overlap_start).total_seconds() / 60.0
            day += timedelta(days=1)

        return round(max(0.0, total), 1)

    # ── API ───────────────────────────────────────────────────────────

    @api.model
    def get_for_platform(self, platform):
        """Return the SLA config for the given platform or the default."""
        rec = self.search([('platform', '=', platform)], limit=1)
        if not rec:
            rec = self.search([('platform', '=', 'default')], limit=1)
        return rec

    @api.model
    def _ensure_defaults(self):
        """Seed a default SLA row if none exists."""
        if not self.search_count([('platform', '=', 'default')]):
            self.create({'platform': 'default'})
