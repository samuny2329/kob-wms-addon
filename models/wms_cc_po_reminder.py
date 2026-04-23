"""Command Center — PO Status Reminder (Supply Chain automation).

Automates "ติดตาม PO Status กับ Supplier" (P2 High from Notion
Process Automation Audit). Replaces "LINE / โทรตาม supplier ทีละคำสั่ง"
manual process.

Logic:
  - Cron daily scans purchase.order where:
      state = 'purchase' (confirmed)
      AND any picking still pending
      AND date_planned <= today (or >= N days since confirmation)
  - For each overdue PO, create a wms.cc.po.reminder log record (once
    per day) + schedule activity on purchase.user_id
  - Tracks total reminders sent per PO to avoid spam
"""
from datetime import timedelta

from odoo import models, fields, api, _


class WmsCcPoReminder(models.Model):
    _name = 'wms.cc.po.reminder'
    _description = 'CC — PO Reminder Log'
    _order = 'reminder_date desc, id desc'
    _rec_name = 'purchase_order_id'

    purchase_order_id = fields.Many2one('purchase.order', required=True,
                                        ondelete='cascade', index=True)
    partner_id = fields.Many2one(related='purchase_order_id.partner_id',
                                 store=True, string='Supplier')
    date_order = fields.Datetime(related='purchase_order_id.date_order',
                                 store=True)
    date_planned = fields.Datetime(related='purchase_order_id.date_planned',
                                   store=True, string='Planned')
    overdue_days = fields.Integer(readonly=True)
    reminder_date = fields.Date(default=fields.Date.context_today,
                                required=True, index=True)
    reminder_count = fields.Integer(readonly=True, default=1)
    acknowledged = fields.Boolean(default=False,
                                  help='Purchasing team confirmed action taken')
    note = fields.Text()

    _sql_constraints = [
        ('po_day_unique',
         'unique(purchase_order_id, reminder_date)',
         'Only one reminder per PO per day.'),
    ]

    @api.model
    def cron_scan_overdue_pos(self, grace_days=3):
        """Scan all confirmed POs overdue by >= grace_days from
        date_planned. Create a reminder record + schedule activity."""
        today = fields.Date.context_today(self)
        cutoff = fields.Datetime.to_datetime(today) - timedelta(days=grace_days)
        POs = self.env['purchase.order'].sudo()
        overdue = POs.search([
            ('state', '=', 'purchase'),
            ('date_planned', '<=', cutoff),
        ])
        created = 0
        for po in overdue:
            # Check if any pending picking
            pending = po.picking_ids.filtered(
                lambda p: p.state not in ('done', 'cancel'))
            if not pending:
                continue
            # Idempotent per day
            existing = self.sudo().search([
                ('purchase_order_id', '=', po.id),
                ('reminder_date', '=', today),
            ], limit=1)
            if existing:
                continue
            # Compute overdue days
            if po.date_planned:
                delta = (fields.Datetime.to_datetime(today) - po.date_planned).days
            else:
                delta = 0
            # Count prior reminders
            prior_count = self.sudo().search_count([
                ('purchase_order_id', '=', po.id),
            ])
            self.sudo().create({
                'purchase_order_id': po.id,
                'reminder_date': today,
                'overdue_days': delta,
                'reminder_count': prior_count + 1,
            })
            # Schedule activity on PO user
            target_user = po.user_id or po.create_uid
            if target_user:
                po.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=target_user.id,
                    summary=_('PO Overdue — chase supplier'),
                    note=_('PO <b>%s</b> (supplier %s) is overdue by '
                           '<b>%d days</b>. Planned: %s. Please contact '
                           'supplier for update.'
                    ) % (po.name, po.partner_id.display_name, delta,
                         po.date_planned or '—'),
                )
            created += 1
        return {'overdue_count': len(overdue), 'reminders_created': created}

    def action_acknowledge(self):
        self.write({'acknowledged': True})
