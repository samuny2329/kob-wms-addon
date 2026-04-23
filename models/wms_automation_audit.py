"""WMS Process Automation Audit (K-OKR3-02).

Implements the Warehouse Automation Level KPI defined in Notion
(page 31be8572596481e9a89ec70c4497ce0c).

Formula:  Auto Level %  =  Σ(step scores) / (6 × 100) × 100
Steps:    Receive → Putaway → Pick → Pack → Ship → Invoice
Scale:    Manual=0 · Semi-Auto=50 · Full-Auto=100
Target:   ≥ 70%
"""
from odoo import models, fields, api, _

STEP_SEL = [
    ('manual', 'Manual (0)'),
    ('semi',   'Semi-Auto (50)'),
    ('full',   'Full-Auto (100)'),
]

SCORE_MAP = {'manual': 0, 'semi': 50, 'full': 100}

STATUS_SEL = [
    ('pass',     '✅ Pass (≥70%)'),
    ('watch',    '⚠️ Watch (50-70%)'),
    ('over',     '❌ Over (30-50%)'),
    ('critical', '🔴 Critical (<30%)'),
]


class WmsAutomationAudit(models.Model):
    _name = 'wms.automation.audit'
    _description = 'WMS Process Automation Audit (K-OKR3-02)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'audit_date desc, id desc'
    _rec_name = 'name'

    name = fields.Char(compute='_compute_name', store=True)
    audit_date = fields.Date(string='Audit Date', required=True,
                             default=fields.Date.context_today, tracking=True)
    company_id = fields.Many2one('res.company',
                                 default=lambda self: self.env.company)
    notes = fields.Text(string='Notes')

    # ── 6 workflow steps ──────────────────────────────────────────────────
    receive_level = fields.Selection(STEP_SEL, default='manual', required=True,
                                     string='Receive', tracking=True)
    putaway_level = fields.Selection(STEP_SEL, default='manual', required=True,
                                     string='Putaway', tracking=True)
    pick_level = fields.Selection(STEP_SEL, default='manual', required=True,
                                  string='Pick', tracking=True)
    pack_level = fields.Selection(STEP_SEL, default='manual', required=True,
                                  string='Pack', tracking=True)
    ship_level = fields.Selection(STEP_SEL, default='manual', required=True,
                                  string='Ship', tracking=True)
    invoice_level = fields.Selection(STEP_SEL, default='manual', required=True,
                                     string='Invoice', tracking=True)

    # ── Scores ────────────────────────────────────────────────────────────
    receive_score = fields.Integer(compute='_compute_scores', store=True)
    putaway_score = fields.Integer(compute='_compute_scores', store=True)
    pick_score = fields.Integer(compute='_compute_scores', store=True)
    pack_score = fields.Integer(compute='_compute_scores', store=True)
    ship_score = fields.Integer(compute='_compute_scores', store=True)
    invoice_score = fields.Integer(compute='_compute_scores', store=True)

    total_score = fields.Float(string='Automation Level %',
                               compute='_compute_scores', store=True,
                               digits=(5, 2),
                               help='Auto Level % = Σ step scores / 600 × 100')
    status = fields.Selection(STATUS_SEL, compute='_compute_status',
                              store=True, tracking=True)

    # ── Detected Odoo automation configs (auto-populated) ────────────────
    active_cron_count = fields.Integer(string='Active ir.cron',
                                       help='Number of active scheduled jobs')
    active_stock_rule_count = fields.Integer(string='Active stock.rule',
                                             help='Push/pull automation routes')
    auto_lot_picking_types = fields.Integer(
        string='Auto-Create Lot Picking Types',
        help='Count of stock.picking.type with use_create_lots=True')
    auto_print_picking_types = fields.Integer(
        string='Auto-Print Picking Types',
        help='Count of picking types with auto_print_delivery_slip=True')
    wms_active_workers = fields.Integer(
        string='Active WMS Workers',
        help='Handheld users = automated pick if > 0')
    platform_api_configs = fields.Integer(
        string='Platform API Configs',
        help='Shopee/Lazada/TikTok integrations configured')
    server_action_count = fields.Integer(string='Active Server Actions')

    recommendations = fields.Text(string='Recommended Improvements',
                                  compute='_compute_recommendations',
                                  store=True)

    _sql_constraints = [
        ('audit_date_company_unique',
         'unique(audit_date, company_id)',
         'Only one automation audit per day per company.'),
    ]

    # ────────────────────────────────────────────────────────────────────
    # Computes
    # ────────────────────────────────────────────────────────────────────
    @api.depends('audit_date', 'company_id')
    def _compute_name(self):
        for rec in self:
            d = rec.audit_date.strftime('%Y-%m-%d') if rec.audit_date else '—'
            co = rec.company_id.name or ''
            rec.name = _('Automation Audit %s (%s)') % (d, co)

    @api.depends('receive_level', 'putaway_level', 'pick_level',
                 'pack_level', 'ship_level', 'invoice_level')
    def _compute_scores(self):
        for rec in self:
            rec.receive_score = SCORE_MAP.get(rec.receive_level, 0)
            rec.putaway_score = SCORE_MAP.get(rec.putaway_level, 0)
            rec.pick_score = SCORE_MAP.get(rec.pick_level, 0)
            rec.pack_score = SCORE_MAP.get(rec.pack_level, 0)
            rec.ship_score = SCORE_MAP.get(rec.ship_level, 0)
            rec.invoice_score = SCORE_MAP.get(rec.invoice_level, 0)
            total = (rec.receive_score + rec.putaway_score + rec.pick_score
                     + rec.pack_score + rec.ship_score + rec.invoice_score)
            rec.total_score = round(total / 6.0, 2)

    @api.depends('total_score')
    def _compute_status(self):
        for rec in self:
            t = rec.total_score
            if t >= 70:
                rec.status = 'pass'
            elif t >= 50:
                rec.status = 'watch'
            elif t >= 30:
                rec.status = 'over'
            else:
                rec.status = 'critical'

    @api.depends('receive_level', 'putaway_level', 'pick_level',
                 'pack_level', 'ship_level', 'invoice_level', 'total_score')
    def _compute_recommendations(self):
        """Generate Thai-language recommendations based on weak steps."""
        for rec in self:
            recs = []
            if rec.total_score < 70:
                recs.append(_(
                    '⚠️ Automation Level %.2f%% ยังต่ำกว่าเป้า 70%% — '
                    'ตรวจสอบรายการปรับปรุงด้านล่าง') % rec.total_score)
            checks = [
                ('receive_level', rec.receive_level, _('Receive'),
                 _('📦 Handheld scan รับของ + Auto-create Lot — ตั้ง '
                   'Picking Type: use_create_lots=True')),
                ('putaway_level', rec.putaway_level, _('Putaway'),
                 _('📍 Putaway Rule (stock.rule) + suggested location — '
                   'เปิด Storage Locations ใน Operations')),
                ('pick_level', rec.pick_level, _('Pick'),
                 _('🏃 Handheld scanner + guided pick (wms.sales.order) — '
                   'KOB WMS Pick Screen มีแล้ว ใช้ต่อได้ทันที')),
                ('pack_level', rec.pack_level, _('Pack'),
                 _('📦 Auto-print delivery slip หลัง pack — ตั้ง '
                   'auto_print_delivery_slip=True บน Picking Type')),
                ('ship_level', rec.ship_level, _('Ship'),
                 _('🚚 Carrier API integration (wms.api.config) + '
                   'Auto-generate AWB ผ่าน wms.courier')),
                ('invoice_level', rec.invoice_level, _('Invoice'),
                 _('💰 Auto-invoice post-delivery — ตั้ง '
                   'sale.order invoice_policy=delivery + cron auto-post')),
            ]
            for _field, level, label, hint in checks:
                if level == 'manual':
                    recs.append('❌ %s: %s' % (label, hint))
                elif level == 'semi':
                    recs.append('🟡 %s: upgrade Semi → Full (%s)' % (label, hint))
            rec.recommendations = '\n'.join(recs) if recs else _(
                '🎉 ทุก step เป็น Full-Auto แล้ว — รักษาระดับนี้ไว้')

    # ────────────────────────────────────────────────────────────────────
    # Detection: scan Odoo config and auto-suggest levels
    # ────────────────────────────────────────────────────────────────────
    def action_run_audit(self):
        """Scan the database for automation signals and auto-populate
        levels + counts. Can be called manually or by cron."""
        for rec in self:
            env = rec.env
            # ── Counters ─────────────────────────────────────────────
            rec.active_cron_count = env['ir.cron'].sudo().search_count(
                [('active', '=', True)])
            rec.active_stock_rule_count = env['stock.rule'].sudo().search_count(
                [('active', '=', True)])
            rec.auto_lot_picking_types = env['stock.picking.type'].sudo().search_count(
                [('use_create_lots', '=', True)])
            rec.auto_print_picking_types = env['stock.picking.type'].sudo().search_count(
                [('auto_print_delivery_slip', '=', True)])
            rec.wms_active_workers = env['kob.wms.user'].sudo().search_count(
                [('is_active', '=', True)])
            rec.platform_api_configs = env['wms.api.config'].sudo().search_count([])
            rec.server_action_count = env['ir.actions.server'].sudo().search_count(
                [('state', '=', 'code')])

            # ── Auto-suggest levels per step ─────────────────────────
            # Receive
            if rec.auto_lot_picking_types >= 2:
                rec.receive_level = 'full'
            elif rec.wms_active_workers > 0:
                rec.receive_level = 'semi'
            else:
                rec.receive_level = 'manual'

            # Putaway
            if rec.active_stock_rule_count >= 5:
                rec.putaway_level = 'full'
            elif rec.active_stock_rule_count >= 1:
                rec.putaway_level = 'semi'
            else:
                rec.putaway_level = 'manual'

            # Pick — KOB WMS has dedicated pick screen, so if active workers exist
            # that means guided pick is in use
            if rec.wms_active_workers >= 5:
                rec.pick_level = 'full'
            elif rec.wms_active_workers >= 1:
                rec.pick_level = 'semi'
            else:
                rec.pick_level = 'manual'

            # Pack
            if rec.auto_print_picking_types >= 1:
                rec.pack_level = 'full' if rec.auto_print_picking_types >= 2 else 'semi'
            elif rec.wms_active_workers > 0:
                rec.pack_level = 'semi'
            else:
                rec.pack_level = 'manual'

            # Ship
            if rec.platform_api_configs >= 3:
                rec.ship_level = 'full'
            elif rec.platform_api_configs >= 1:
                rec.ship_level = 'semi'
            else:
                rec.ship_level = 'manual'

            # Invoice — check invoice_policy=delivery on products + auto-post cron
            auto_post_cron = env['ir.cron'].sudo().search_count([
                ('active', '=', True),
                ('model_id.model', '=', 'account.move'),
            ])
            delivery_invoice_products = env['product.template'].sudo().search_count([
                ('invoice_policy', '=', 'delivery'),
            ]) if 'invoice_policy' in env['product.template']._fields else 0
            if auto_post_cron >= 1 and delivery_invoice_products >= 10:
                rec.invoice_level = 'full'
            elif delivery_invoice_products >= 1:
                rec.invoice_level = 'semi'
            else:
                rec.invoice_level = 'manual'

            rec.message_post(body=_(
                '🤖 Audit executed · Automation Level: <b>%.2f%%</b> · Status: %s<br/>'
                'Active crons: %d · stock.rule: %d · auto-lot types: %d · '
                'auto-print types: %d · WMS workers: %d · platform APIs: %d'
            ) % (rec.total_score, dict(STATUS_SEL).get(rec.status, ''),
                 rec.active_cron_count, rec.active_stock_rule_count,
                 rec.auto_lot_picking_types, rec.auto_print_picking_types,
                 rec.wms_active_workers, rec.platform_api_configs))
        return True

    # ────────────────────────────────────────────────────────────────────
    # Cron entry (monthly)
    # ────────────────────────────────────────────────────────────────────
    @api.model
    def cron_monthly_audit(self):
        """Auto-create a new audit record at month start and run scan."""
        today = fields.Date.context_today(self)
        existing = self.sudo().search([('audit_date', '=', today)], limit=1)
        if existing:
            return existing.action_run_audit()
        audit = self.sudo().create({'audit_date': today})
        audit.action_run_audit()
        return audit
