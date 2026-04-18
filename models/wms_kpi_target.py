from odoo import models, fields, api, SUPERUSER_ID, _
from odoo.exceptions import ValidationError, AccessError

POSITION_SEL = [
    ('picker', 'Picker'),
    ('packer', 'Packer'),
    ('shipper', 'Shipper / Outbound'),
    ('inventory', 'Inventory / Cycle Count'),
    ('inbound', 'Inbound / Receiving'),
    ('driver', 'Driver / Transport'),
    ('admin_online', 'Admin Online'),
    ('supervisor', 'Supervisor'),
    ('manager', 'Manager'),
]

GRADE_MAP = [
    (4.5, 'A', 'Outstanding'),
    (3.5, 'B', 'Exceeds Expectation'),
    (2.5, 'C', 'Meets Expectation'),
    (1.5, 'D', 'Below Expectation'),
    (0, 'E', 'Needs Improvement'),
]


# =====================================================================
# Pillar
# =====================================================================
class WmsKpiPillar(models.Model):
    _name = 'wms.kpi.pillar'
    _description = 'KPI Pillar'
    _order = 'sequence, id'

    name = fields.Char(string='Pillar Name', required=True)
    icon = fields.Char()
    sequence = fields.Integer(default=10)
    description = fields.Text()
    active = fields.Boolean(default=True)
    color = fields.Integer(default=0)


# =====================================================================
# Template + Line + Criterion
# =====================================================================
class WmsKpiTemplate(models.Model):
    _name = 'wms.kpi.template'
    _description = 'KPI Template'
    _rec_name = 'position'
    _order = 'position'

    position = fields.Selection(POSITION_SEL, required=True)
    line_ids = fields.One2many('wms.kpi.template.line', 'template_id',
                               string='Pillar Weights')
    sop_ids = fields.One2many('wms.kpi.sop', 'template_id',
                              string='SOP Documents')
    total_weight = fields.Float(compute='_compute_total_weight', store=True)
    company_id = fields.Many2one('res.company',
                                 default=lambda self: self.env.company)

    _sql_constraints = [
        ('position_company_unique', 'unique(position, company_id)',
         'One KPI template per position per company.'),
    ]

    @api.depends('line_ids.weight')
    def _compute_total_weight(self):
        for rec in self:
            rec.total_weight = sum(rec.line_ids.mapped('weight'))


class WmsKpiTemplateLine(models.Model):
    _name = 'wms.kpi.template.line'
    _description = 'KPI Template Line'
    _order = 'sequence, id'

    template_id = fields.Many2one('wms.kpi.template', ondelete='cascade',
                                  required=True)
    pillar_id = fields.Many2one('wms.kpi.pillar', required=True,
                                ondelete='restrict')
    weight = fields.Float(string='Weight %', default=0, digits=(5, 1))
    sequence = fields.Integer(related='pillar_id.sequence', store=True)
    criterion_ids = fields.One2many('wms.kpi.criterion', 'template_line_id',
                                    string='Criteria')


class WmsKpiCriterion(models.Model):
    _name = 'wms.kpi.criterion'
    _description = 'KPI Criterion'
    _order = 'sequence, id'

    template_line_id = fields.Many2one('wms.kpi.template.line',
                                       ondelete='cascade', required=True)
    name = fields.Char(required=True)
    description = fields.Text()
    sequence = fields.Integer(default=10)
    weight = fields.Float(string='Weight %', default=0, digits=(5, 1))

    score_0 = fields.Char(default='Not applicable / Not observed')
    score_1 = fields.Char(default='Significantly below expectation')
    score_2 = fields.Char(default='Below expected standard')
    score_3 = fields.Char(default='Meets the expected standard')
    score_4 = fields.Char(default='Consistently above standard')
    score_5 = fields.Char(default='Exceptional performance')


# =====================================================================
# Enhancement 3: SOP per Position
# =====================================================================
class WmsKpiSop(models.Model):
    _name = 'wms.kpi.sop'
    _description = 'SOP Document'
    _order = 'sequence, id'

    template_id = fields.Many2one('wms.kpi.template', ondelete='cascade',
                                  required=True)
    name = fields.Char(string='SOP Title', required=True)
    description = fields.Html(string='SOP Content / Checklist')
    attachment_ids = fields.Many2many('ir.attachment', string='Attachments')
    sequence = fields.Integer(default=10)
    version = fields.Char(default='1.0')
    effective_date = fields.Date()
    active = fields.Boolean(default=True)
    pillar_id = fields.Many2one('wms.kpi.pillar', string='Related Pillar')


# =====================================================================
# Enhancement 2: Approver Config
# =====================================================================
class WmsKpiApproverConfig(models.Model):
    _name = 'wms.kpi.approver.config'
    _description = 'KPI Approver Configuration'
    _rec_name = 'position'

    position = fields.Selection(POSITION_SEL, required=True)
    company_id = fields.Many2one('res.company',
                                 default=lambda self: self.env.company)
    supervisor_id = fields.Many2one('res.users', string='Default Supervisor')
    asst_manager_id = fields.Many2one('res.users', string='Default Asst. Manager')
    manager_id = fields.Many2one('res.users', string='Default Manager')
    director_id = fields.Many2one('res.users', string='Default Director')
    user_override_ids = fields.One2many('wms.kpi.approver.config.line',
                                        'config_id',
                                        string='Per-User Overrides')

    _sql_constraints = [
        ('position_company_unique', 'unique(position, company_id)',
         'One approver config per position per company.'),
    ]


class WmsKpiApproverConfigLine(models.Model):
    _name = 'wms.kpi.approver.config.line'
    _description = 'KPI Approver Override per User'

    config_id = fields.Many2one('wms.kpi.approver.config', ondelete='cascade')
    user_id = fields.Many2one('res.users', string='Worker', required=True)
    supervisor_id = fields.Many2one('res.users', string='Supervisor')
    asst_manager_id = fields.Many2one('res.users', string='Asst. Manager')
    manager_id = fields.Many2one('res.users', string='Manager')
    director_id = fields.Many2one('res.users', string='Director')


# =====================================================================
# Season
# =====================================================================
class WmsKpiSeason(models.Model):
    _name = 'wms.kpi.season'
    _description = 'KPI Season'
    _order = 'date_start desc'

    name = fields.Char(required=True)
    date_start = fields.Date(required=True)
    date_end = fields.Date(required=True)
    season_type = fields.Selection([
        ('full', 'Full Year'),
        ('half', 'Half Year (H1/H2)'),
        ('mid_check', 'Mid-Year Check-in'),
    ], default='half')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('open', 'Open'),
        ('closed', 'Closed'),
    ], default='draft')
    self_weight_pct = fields.Float(string='Self Weight %', default=40)
    reviewer_weight_pct = fields.Float(string='Reviewer Weight %', default=60)
    assessment_ids = fields.One2many('wms.kpi.assessment', 'season_id')
    assessment_count = fields.Integer(compute='_compute_assessment_count')
    company_id = fields.Many2one('res.company',
                                 default=lambda self: self.env.company)

    def _compute_assessment_count(self):
        for rec in self:
            rec.assessment_count = len(rec.assessment_ids)

    def action_open(self):
        self.write({'state': 'open'})

    def action_close(self):
        self.write({'state': 'closed'})

    def action_bulk_create_assessments(self):
        self.ensure_one()
        created = 0

        existing_kob  = self.assessment_ids.mapped('kob_user_id')
        existing_users = self.assessment_ids.mapped('user_id')

        # ── Part 1: kob.wms.users (primary — covers PIN workers AND linked Odoo users) ──
        all_kob = self.env['kob.wms.user'].sudo().search([('is_active', '=', True)])
        for kob_user in (all_kob - existing_kob):
            template = self._auto_assign_template_for_kob(kob_user)
            assessment = self.env['wms.kpi.assessment'].create({
                'kob_user_id': kob_user.id,
                # user_id auto-filled by create() override from kob_user.res_user_id
                'season_id': self.id,
                'template_id': template.id if template else False,
            })
            assessment._auto_assign_approvers()
            assessment._onchange_template_id()
            created += 1

        # ── Part 2: Odoo-only users (supervisors/managers with no kob.wms.user) ──
        wms_groups = [
            self.env.ref('kob_wms.group_wms_supervisor', raise_if_not_found=False),
            self.env.ref('kob_wms.group_wms_manager', raise_if_not_found=False),
            self.env.ref('kob_wms.group_wms_director', raise_if_not_found=False),
        ]
        group_ids = [g.id for g in wms_groups if g]
        if group_ids:
            mgr_users = self.env['res.users'].search([
                ('groups_id', 'in', group_ids), ('active', '=', True),
                ('id', '!=', SUPERUSER_ID),
            ])
            # Only those without a linked kob.wms.user (already covered in part 1)
            linked_odoo_ids = all_kob.mapped('res_user_id').ids
            for user in mgr_users:
                if user.id in linked_odoo_ids:
                    continue   # already created via kob_user in part 1
                if user in existing_users:
                    continue
                template = self._auto_assign_template(user)
                assessment = self.env['wms.kpi.assessment'].create({
                    'user_id': user.id,
                    'season_id': self.id,
                    'template_id': template.id if template else False,
                })
                assessment._auto_assign_approvers()
                assessment._onchange_template_id()
                created += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Bulk Create'),
                'message': _('Created %d assessments.') % created,
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def _auto_assign_template(self, user):
        Template = self.env['wms.kpi.template']
        dir_grp = self.env.ref('kob_wms.group_wms_director', raise_if_not_found=False)
        mgr_grp = self.env.ref('kob_wms.group_wms_manager', raise_if_not_found=False)
        sup_grp = self.env.ref('kob_wms.group_wms_supervisor', raise_if_not_found=False)

        if dir_grp and user in dir_grp.users:
            t = Template.search([('position', '=', 'manager')], limit=1)
            if t: return t
        if mgr_grp and user in mgr_grp.users:
            t = Template.search([('position', '=', 'manager')], limit=1)
            if t: return t
        if sup_grp and user in sup_grp.users:
            t = Template.search([('position', '=', 'supervisor')], limit=1)
            if t: return t
        return Template.search([('position', '=', 'picker')], limit=1)

    def _auto_assign_template_for_kob(self, kob_user):
        """Assign template based on kob.wms.user.role / position."""
        Template = self.env['wms.kpi.template']
        # Map role to template position
        role_map = {
            'admin':       'manager',
            'supervisor':  'supervisor',
            'coordinator': 'supervisor',
            'picker':      'picker',
            'packer':      'packer',
            'outbound':    'shipper',
            'viewer':      'picker',
        }
        pos = role_map.get(kob_user.role, 'picker')
        t = Template.search([('position', '=', pos)], limit=1)
        return t or Template.search([('position', '=', 'picker')], limit=1)


# =====================================================================
# Assessment
# =====================================================================
class WmsKpiAssessment(models.Model):
    _name = 'wms.kpi.assessment'
    _description = 'KPI Assessment'
    _order = 'season_id desc, kob_user_id, user_id'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(compute='_compute_name', store=True)
    user_id = fields.Many2one('res.users', string='Odoo User', tracking=True)
    kob_user_id = fields.Many2one('kob.wms.user', string='Employee', tracking=True,
                                  help='WMS employee (PIN login). Set automatically when linked via Odoo Account.')
    season_id = fields.Many2one('wms.kpi.season', required=True, tracking=True)
    template_id = fields.Many2one('wms.kpi.template', tracking=True)
    position = fields.Selection(related='template_id.position', store=True)

    # 4-level approval
    supervisor_id = fields.Many2one('res.users', string='Supervisor',
                                    tracking=True)
    asst_manager_id = fields.Many2one('res.users', string='Asst. Manager',
                                      tracking=True)
    manager_id = fields.Many2one('res.users', string='Manager', tracking=True)
    director_id = fields.Many2one('res.users', string='Director', tracking=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('self_review', 'Self Assessment'),
        ('supervisor', 'Supervisor Review'),
        ('asst_manager', 'Asst. Manager Review'),
        ('manager', 'Manager Approval'),
        ('director', 'Director Approval'),
        ('done', 'Completed'),
        ('rejected', 'Rejected'),
    ], default='draft', tracking=True)

    supervisor_approved = fields.Boolean(tracking=True)
    asst_manager_approved = fields.Boolean(tracking=True)
    manager_approved = fields.Boolean(tracking=True)
    director_approved = fields.Boolean(tracking=True)
    reject_reason = fields.Text()

    line_ids = fields.One2many('wms.kpi.assessment.line', 'assessment_id')

    # Scores
    self_score = fields.Float(compute='_compute_scores', store=True,
                              digits=(5, 2))
    supervisor_score = fields.Float(compute='_compute_scores', store=True,
                                    digits=(5, 2))
    final_score = fields.Float(compute='_compute_scores', store=True,
                               digits=(5, 2))
    grade = fields.Char(compute='_compute_scores', store=True)
    grade_label = fields.Char(compute='_compute_scores', store=True)

    prev_final_score = fields.Float(compute='_compute_prev_score')
    score_change = fields.Float(compute='_compute_prev_score')

    self_comment = fields.Text()
    supervisor_comment = fields.Text()
    asst_manager_comment = fields.Text()
    manager_comment = fields.Text()
    director_comment = fields.Text()

    goal_ids = fields.One2many('wms.kpi.goal', 'assessment_id')

    # SOP reference (read-only, from template)
    sop_ids = fields.One2many(related='template_id.sop_ids', readonly=True)

    company_id = fields.Many2one('res.company',
                                 default=lambda self: self.env.company)

    _sql_constraints = [
        ('user_season_unique', 'unique(user_id, season_id)',
         'One assessment per Odoo user per season.'),
        ('kob_user_season_unique', 'unique(kob_user_id, season_id)',
         'One assessment per employee per season.'),
    ]

    @api.constrains('user_id', 'kob_user_id')
    def _check_worker_set(self):
        for rec in self:
            if not rec.user_id and not rec.kob_user_id:
                raise ValidationError(
                    'Assessment must have either an Odoo user or an Employee.')

    @api.depends('user_id', 'kob_user_id', 'season_id')
    def _compute_name(self):
        for rec in self:
            # Prioritise kob.wms.user (Employee) over res.users (Odoo account)
            worker = rec.kob_user_id.name or rec.user_id.name or ''
            rec.name = f"{worker} - {rec.season_id.name or ''}"

    @api.depends('line_ids.self_score', 'line_ids.reviewer_score',
                 'line_ids.weight')
    def _compute_scores(self):
        for rec in self:
            total_weight = sum(rec.line_ids.mapped('weight')) or 1
            rec.self_score = sum(
                l.self_score * l.weight / total_weight for l in rec.line_ids)
            rec.supervisor_score = sum(
                l.reviewer_score * l.weight / total_weight for l in rec.line_ids)
            sw = (rec.season_id.self_weight_pct or 40) / 100
            rw = (rec.season_id.reviewer_weight_pct or 60) / 100
            rec.final_score = rec.self_score * sw + rec.supervisor_score * rw
            rec.grade = 'E'
            rec.grade_label = 'Needs Improvement'
            for threshold, grade, label in GRADE_MAP:
                if rec.final_score >= threshold:
                    rec.grade = grade
                    rec.grade_label = label
                    break

    def _compute_prev_score(self):
        for rec in self:
            domain = [('season_id', '!=', rec.season_id.id), ('state', '=', 'done')]
            if rec.user_id:
                domain.append(('user_id', '=', rec.user_id.id))
            elif rec.kob_user_id:
                domain.append(('kob_user_id', '=', rec.kob_user_id.id))
            else:
                rec.prev_final_score = 0
                rec.score_change = 0
                continue
            prev = self.sudo().search(domain, order='season_id desc', limit=1)
            rec.prev_final_score = prev.final_score if prev else 0
            rec.score_change = rec.final_score - rec.prev_final_score

    # --- Auto-assign approvers ---
    def _auto_assign_approvers(self):
        for rec in self:
            if not rec.position:
                continue
            config = self.env['wms.kpi.approver.config'].search([
                ('position', '=', rec.position),
                ('company_id', '=', rec.company_id.id),
            ], limit=1)
            if not config:
                continue
            # Use res.user from user_id or from kob_user's linked account
            res_user = rec.user_id or (
                rec.kob_user_id.res_user_id if rec.kob_user_id else False)
            override = config.user_override_ids.filtered(
                lambda l: l.user_id == res_user)
            src = override[0] if override else config
            vals = {}
            vals['supervisor_id'] = (src.supervisor_id or config.supervisor_id).id or False
            vals['asst_manager_id'] = (src.asst_manager_id or config.asst_manager_id).id or False
            vals['manager_id'] = (src.manager_id or config.manager_id).id or False
            vals['director_id'] = (src.director_id or config.director_id).id or False
            rec.write(vals)

    # --- Workflow ---
    def action_start_self_review(self):
        self.write({'state': 'self_review'})

    def action_submit_to_supervisor(self):
        self.write({'state': 'supervisor'})
        self._notify_next_approver('supervisor_id', 'Supervisor Review')

    def action_supervisor_approve(self):
        self.write({'state': 'asst_manager', 'supervisor_approved': True})
        self._notify_next_approver('asst_manager_id', 'Asst. Manager Review')

    def action_supervisor_reject(self):
        self.write({'state': 'rejected', 'supervisor_approved': False})

    def action_asst_manager_approve(self):
        self.write({'state': 'manager', 'asst_manager_approved': True})
        self._notify_next_approver('manager_id', 'Manager Approval')

    def action_asst_manager_reject(self):
        self.write({'state': 'rejected', 'asst_manager_approved': False})

    def action_manager_approve(self):
        self.write({'state': 'director', 'manager_approved': True})
        self._notify_next_approver('director_id', 'Director Approval')

    def action_manager_reject(self):
        self.write({'state': 'rejected', 'manager_approved': False})

    def action_director_approve(self):
        self.write({'state': 'done', 'director_approved': True})

    def action_director_reject(self):
        self.write({'state': 'rejected', 'director_approved': False})

    def action_reset_draft(self):
        self.write({
            'state': 'draft',
            'supervisor_approved': False,
            'asst_manager_approved': False,
            'manager_approved': False,
            'director_approved': False,
            'reject_reason': False,
        })

    def _notify_next_approver(self, approver_field, summary):
        for rec in self:
            approver = rec[approver_field]
            if approver:
                rec.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=approver.id,
                    summary=_('%s: %s') % (summary, rec.name),
                    note=_('KPI Assessment for %s is waiting for your review.')
                         % (rec.user_id.name or rec.kob_user_id.name or ''),
                )

    @api.onchange('user_id')
    def _onchange_user_id(self):
        if self.user_id and self.season_id:
            template = self.season_id._auto_assign_template(self.user_id)
            if template:
                self.template_id = template
            # Auto-link kob.wms.user if not already set
            if not self.kob_user_id:
                kob = self.env['kob.wms.user'].sudo().search(
                    [('res_user_id', '=', self.user_id.id)], limit=1)
                if kob:
                    self.kob_user_id = kob

    @api.onchange('kob_user_id')
    def _onchange_kob_user_id(self):
        """Auto-fill Odoo account from the employee's linked res.users."""
        if self.kob_user_id and self.kob_user_id.res_user_id and not self.user_id:
            self.user_id = self.kob_user_id.res_user_id
        # Auto-assign template from employee position
        if self.kob_user_id and self.season_id and not self.template_id:
            pos = self.kob_user_id.position
            if pos:
                tmpl = self.env['wms.kpi.template'].search(
                    [('position', '=', pos)], limit=1)
                if tmpl:
                    self.template_id = tmpl

    @api.model_create_multi
    def create(self, vals_list):
        """On create: auto-link user_id ↔ kob_user_id if one is missing."""
        for vals in vals_list:
            kob_id  = vals.get('kob_user_id')
            user_id = vals.get('user_id')
            if kob_id and not user_id:
                kob = self.env['kob.wms.user'].browse(kob_id)
                if kob.res_user_id:
                    vals['user_id'] = kob.res_user_id.id
            elif user_id and not kob_id:
                kob = self.env['kob.wms.user'].sudo().search(
                    [('res_user_id', '=', user_id)], limit=1)
                if kob:
                    vals['kob_user_id'] = kob.id
        return super().create(vals_list)

    @api.onchange('template_id')
    def _onchange_template_id(self):
        if self.template_id and not self.line_ids:
            lines = []
            for tl in self.template_id.line_ids:
                scores = [(0, 0, {'criterion_id': cr.id})
                          for cr in tl.criterion_ids]
                lines.append((0, 0, {
                    'pillar_id': tl.pillar_id.id,
                    'weight': tl.weight,
                    'score_ids': scores,
                }))
            self.line_ids = lines


# =====================================================================
# Assessment Line (per pillar)
# =====================================================================
class WmsKpiAssessmentLine(models.Model):
    _name = 'wms.kpi.assessment.line'
    _description = 'KPI Assessment Line'
    _order = 'sequence, id'

    assessment_id = fields.Many2one('wms.kpi.assessment', ondelete='cascade',
                                    required=True)
    pillar_id = fields.Many2one('wms.kpi.pillar', required=True)
    weight = fields.Float(string='Weight %', digits=(5, 1))
    sequence = fields.Integer(related='pillar_id.sequence', store=True)
    score_ids = fields.One2many('wms.kpi.assessment.score', 'line_id')

    self_score = fields.Float(digits=(5, 2),
                              compute='_compute_scores_from_criteria',
                              store=True, readonly=False)
    reviewer_score = fields.Float(digits=(5, 2),
                                  compute='_compute_scores_from_criteria',
                                  store=True, readonly=False)
    self_comment = fields.Text()
    reviewer_comment = fields.Text()

    weighted_self = fields.Float(compute='_compute_weighted', digits=(5, 2))
    weighted_reviewer = fields.Float(compute='_compute_weighted', digits=(5, 2))

    @api.depends('score_ids.self_score', 'score_ids.reviewer_score')
    def _compute_scores_from_criteria(self):
        for rec in self:
            scores = rec.score_ids.filtered('criterion_id')
            if scores:
                total_w = sum(s.weight for s in scores) or 1
                rec.self_score = sum(
                    s.self_score * s.weight / total_w for s in scores)
                rec.reviewer_score = sum(
                    s.reviewer_score * s.weight / total_w for s in scores)

    @api.depends('self_score', 'reviewer_score', 'weight')
    def _compute_weighted(self):
        for rec in self:
            rec.weighted_self = rec.self_score * rec.weight / 100
            rec.weighted_reviewer = rec.reviewer_score * rec.weight / 100


# =====================================================================
# Assessment Score (per criterion)
# =====================================================================
class WmsKpiAssessmentScore(models.Model):
    _name = 'wms.kpi.assessment.score'
    _description = 'KPI Assessment Criterion Score'
    _order = 'sequence, id'

    line_id = fields.Many2one('wms.kpi.assessment.line', ondelete='cascade',
                              required=True)
    criterion_id = fields.Many2one('wms.kpi.criterion')
    name = fields.Char(related='criterion_id.name', readonly=True)
    description = fields.Text(related='criterion_id.description', readonly=True)
    weight = fields.Float(related='criterion_id.weight', readonly=True)
    sequence = fields.Integer(related='criterion_id.sequence', store=True)

    SCORE_SEL = [('0', '0'), ('1', '1'), ('2', '2'),
                 ('3', '3'), ('4', '4'), ('5', '5')]

    self_score_sel = fields.Selection(SCORE_SEL, string='Self', default='0')
    reviewer_score_sel = fields.Selection(SCORE_SEL, string='Reviewer',
                                          default='0')

    self_score = fields.Float(compute='_compute_numeric', store=True,
                              digits=(3, 1))
    reviewer_score = fields.Float(compute='_compute_numeric', store=True,
                                  digits=(3, 1))
    self_comment = fields.Text()
    reviewer_comment = fields.Text()

    score_0 = fields.Char(related='criterion_id.score_0')
    score_1 = fields.Char(related='criterion_id.score_1')
    score_2 = fields.Char(related='criterion_id.score_2')
    score_3 = fields.Char(related='criterion_id.score_3')
    score_4 = fields.Char(related='criterion_id.score_4')
    score_5 = fields.Char(related='criterion_id.score_5')

    @api.depends('self_score_sel', 'reviewer_score_sel')
    def _compute_numeric(self):
        for rec in self:
            rec.self_score = float(rec.self_score_sel or '0')
            rec.reviewer_score = float(rec.reviewer_score_sel or '0')


# =====================================================================
# Goals / Action Items
# =====================================================================
class WmsKpiGoal(models.Model):
    _name = 'wms.kpi.goal'
    _description = 'KPI Goal / Action Item'
    _order = 'deadline, id'

    assessment_id = fields.Many2one('wms.kpi.assessment', ondelete='cascade',
                                    required=True)
    name = fields.Char(string='Goal', required=True)
    description = fields.Text()
    pillar_id = fields.Many2one('wms.kpi.pillar')
    deadline = fields.Date()
    state = fields.Selection([
        ('todo', 'To Do'),
        ('in_progress', 'In Progress'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], default='todo')
    progress_note = fields.Text()
    completed_date = fields.Date()
