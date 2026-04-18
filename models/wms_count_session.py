from odoo import models, fields, api, _
from odoo.exceptions import UserError


class WmsCountSession(models.Model):
    _name = 'wms.count.session'
    _description = 'WMS Count Session (Full/Cycle Count)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(string='Reference', required=True, copy=False,
                       readonly=True, default=lambda self: _('New'))
    session_type = fields.Selection([
        ('full', 'Full Count'),
        ('cycle', 'Cycle Count'),
    ], string='Type', default='full', required=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('reconciling', 'Reconciling'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], string='State', default='draft', tracking=True)
    warehouse_id = fields.Many2one('stock.warehouse', string='Warehouse',
                                   required=True,
                                   default=lambda self: self.env['stock.warehouse'].search([], limit=1))
    company_id = fields.Many2one('res.company', related='warehouse_id.company_id',
                                 store=True)
    date_start = fields.Datetime(string='Start Date', default=fields.Datetime.now)
    date_end = fields.Datetime(string='End Date')
    responsible_id = fields.Many2one('res.users', string='Responsible',
                                     default=lambda self: self.env.user)
    task_ids = fields.One2many('wms.count.task', 'session_id', string='Tasks')
    task_count = fields.Integer(string='Task Count', compute='_compute_task_count')
    note = fields.Text(string='Notes')

    # ── Live progress counters ─────────────────────────────────
    assigned_count = fields.Integer(
        string='Assigned', compute='_compute_task_state_counts', store=True)
    counting_count = fields.Integer(
        string='🔴 Counting', compute='_compute_task_state_counts', store=True)
    submitted_count = fields.Integer(
        string='🟡 Submitted', compute='_compute_task_state_counts', store=True)
    done_count = fields.Integer(
        string='✅ Done', compute='_compute_task_state_counts', store=True)
    progress_pct = fields.Float(
        string='Progress %', compute='_compute_task_state_counts', store=True)

    # ── Adjustment tracking ────────────────────────────────────
    adjustment_ids = fields.One2many(
        'wms.count.adjustment', 'session_id', string='Adjustments')
    adjustment_count = fields.Integer(
        string='Adjustments', compute='_compute_adjustment_count', store=True)
    pending_adjustment_count = fields.Integer(
        string='Pending', compute='_compute_adjustment_count', store=True)
    variance_threshold_pct = fields.Float(
        string='Variance Threshold %', default=5.0,
        help='Variance above this % will be flagged for recount')

    @api.depends('task_ids')
    def _compute_task_count(self):
        for sess in self:
            sess.task_count = len(sess.task_ids)

    @api.depends('task_ids.state')
    def _compute_task_state_counts(self):
        for sess in self:
            tasks = sess.task_ids
            total = len(tasks)
            assigned  = len(tasks.filtered(lambda t: t.state == 'assigned'))
            counting  = len(tasks.filtered(lambda t: t.state == 'counting'))
            submitted = len(tasks.filtered(lambda t: t.state == 'submitted'))
            done      = len(tasks.filtered(lambda t: t.state in ('verified', 'approved')))
            sess.assigned_count  = assigned
            sess.counting_count  = counting
            sess.submitted_count = submitted
            sess.done_count      = done
            sess.progress_pct    = round((done / total * 100) if total else 0, 1)

    @api.depends('adjustment_ids', 'adjustment_ids.state')
    def _compute_adjustment_count(self):
        for sess in self:
            sess.adjustment_count = len(sess.adjustment_ids)
            sess.pending_adjustment_count = len(
                sess.adjustment_ids.filtered(lambda a: a.state == 'pending'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'wms.count.session') or _('New')
        return super().create(vals_list)

    def action_start(self):
        for sess in self:
            if sess.state != 'draft':
                raise UserError(_('Only draft sessions can be started.'))
            sess.state = 'in_progress'
            sess.date_start = fields.Datetime.now()

    def action_reconcile(self):
        for sess in self:
            if sess.state != 'in_progress':
                raise UserError(_('Session must be in progress to reconcile.'))
            sess.state = 'reconciling'

    def action_done(self):
        for sess in self:
            # Guard: all adjustments must be applied or rejected
            open_adjs = sess.adjustment_ids.filtered(
                lambda a: a.state in ('pending', 'approved'))
            if open_adjs:
                raise UserError(_(
                    'Cannot close session — %d adjustment(s) still pending or approved. '
                    'Apply or reject them first.') % len(open_adjs))
            sess.state = 'done'
            sess.date_end = fields.Datetime.now()

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_draft(self):
        self.write({'state': 'draft'})

    # ── Stat button actions ────────────────────────────────────

    def _task_action(self, state_filter, title):
        return {
            'type': 'ir.actions.act_window',
            'name': title,
            'res_model': 'wms.count.task',
            'view_mode': 'list,form',
            'domain': [('session_id', '=', self.id), ('state', 'in', state_filter)],
            'context': {'search_default_g_worker': 1},
        }

    def action_open_counting_tasks(self):
        self.ensure_one()
        return self._task_action(['counting'], _('🔴 Currently Counting'))

    def action_open_submitted_tasks(self):
        self.ensure_one()
        return self._task_action(['submitted'], _('🟡 Submitted — Awaiting Verification'))

    def action_open_done_tasks(self):
        self.ensure_one()
        return self._task_action(['verified', 'approved'], _('✅ Verified / Approved'))

    def action_verify_all(self):
        """Bulk verify all submitted tasks."""
        submitted = self.task_ids.filtered(lambda t: t.state == 'submitted')
        if not submitted:
            raise UserError(_('No submitted tasks to verify.'))
        submitted.action_verify()

    def action_approve_all(self):
        """Bulk approve all verified tasks."""
        verified = self.task_ids.filtered(lambda t: t.state == 'verified')
        if not verified:
            raise UserError(_('No verified tasks to approve.'))
        verified.action_approve()

    def action_apply_all(self):
        """Bulk apply all approved adjustments."""
        approved = self.adjustment_ids.filtered(lambda a: a.state == 'approved')
        if not approved:
            raise UserError(_('No approved adjustments to apply.'))
        approved.action_apply()
