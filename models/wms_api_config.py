"""WMS Platform API Configuration (extended for Phase A — Platform Sync).

Holds credentials + sync state per marketplace (Shopee/Lazada/TikTok).
Extended from the original react-port to support:
  - Scheduled sync (last_sync_at, sync_interval_minutes, auto_sync)
  - OAuth flow (access_token, refresh_token, token_expires_at)
  - Webhook authentication (webhook_secret for signature validation)
  - Sync statistics (total_synced, sync_errors)
  - Manual sync via `action_sync_now()` (dispatches to the platform adapter)
"""
from datetime import datetime, timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class WmsApiConfig(models.Model):
    _name = 'wms.api.config'
    _description = 'WMS Platform API Configuration'
    _rec_name = 'platform'
    _inherit = ['mail.thread']

    platform = fields.Selection([
        ('odoo', 'Odoo ERP'),
        ('shopee', 'Shopee'),
        ('lazada', 'Lazada'),
        ('tiktok', 'TikTok'),
    ], string='Platform', required=True, tracking=True)
    enabled = fields.Boolean(string='Enabled', default=False, tracking=True)

    # ── Credentials ─────────────────────────────────────────────────────
    api_key = fields.Char(string='API Key / Partner ID')
    api_secret = fields.Char(string='API Secret', groups='kob_wms.group_wms_manager')
    endpoint_url = fields.Char(
        string='Endpoint URL',
        help='Base URL, e.g. https://partner.shopeemobile.com')
    shop_id = fields.Char(string='Shop / Seller ID')

    # ── OAuth flow ───────────────────────────────────────────────────────
    access_token = fields.Char(
        string='Access Token',
        groups='kob_wms.group_wms_manager',
        help='Current OAuth access token (auto-refreshed)')
    refresh_token = fields.Char(
        string='Refresh Token',
        groups='kob_wms.group_wms_manager',
        help='OAuth refresh token for auto-renewal')
    token_expires_at = fields.Datetime(
        string='Token Expires At',
        help='UTC timestamp when access_token expires')
    webhook_secret = fields.Char(
        string='Webhook Secret',
        groups='kob_wms.group_wms_manager',
        help='HMAC-SHA256 key for verifying inbound webhook signatures')

    # ── Sync schedule + state ───────────────────────────────────────────
    auto_sync = fields.Boolean(
        string='Auto Sync',
        default=False,
        help='Automatic sync via cron (requires enabled=True)')
    sync_interval_minutes = fields.Integer(
        string='Sync Interval (minutes)',
        default=15,
        help='How often the cron pulls orders (min 5 to avoid rate limits)')
    last_sync_at = fields.Datetime(
        string='Last Sync', readonly=True, tracking=True)
    next_sync_at = fields.Datetime(
        string='Next Sync', compute='_compute_next_sync',
        help='Expected next cron run')
    last_sync_status = fields.Selection([
        ('ok', '✅ OK'),
        ('partial', '⚠️ Partial'),
        ('error', '❌ Error'),
    ], string='Last Sync Status', readonly=True, tracking=True)
    last_sync_message = fields.Text(string='Last Sync Message', readonly=True)

    # ── Statistics ──────────────────────────────────────────────────────
    total_synced = fields.Integer(
        string='Total Orders Synced', readonly=True, default=0)
    sync_errors = fields.Integer(
        string='Total Errors', readonly=True, default=0)
    platform_order_ids = fields.One2many(
        'wms.platform.order', 'api_config_id',
        string='Platform Orders')
    platform_order_count = fields.Integer(
        compute='_compute_platform_order_count')

    # ── Misc ────────────────────────────────────────────────────────────
    note = fields.Text(string='Note')
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company)

    _sql_constraints = [
        ('platform_company_unique', 'unique(platform, company_id)',
         'One configuration per platform per company.'),
    ]

    @api.depends('last_sync_at', 'sync_interval_minutes', 'auto_sync', 'enabled')
    def _compute_next_sync(self):
        for rec in self:
            if not (rec.auto_sync and rec.enabled and rec.last_sync_at):
                rec.next_sync_at = False
                continue
            minutes = max(5, rec.sync_interval_minutes or 15)
            rec.next_sync_at = rec.last_sync_at + timedelta(minutes=minutes)

    def _compute_platform_order_count(self):
        for rec in self:
            rec.platform_order_count = len(rec.platform_order_ids)

    # ────────────────────────────────────────────────────────────────────
    # Manual sync action
    # ────────────────────────────────────────────────────────────────────
    def action_sync_now(self):
        """Dispatch to the correct platform adapter. Safe to call manually
        even if auto_sync is off; respects enabled flag."""
        self.ensure_one()
        if not self.enabled:
            raise UserError(_(
                'Platform %s is disabled — enable it first.') % self.platform)

        try:
            result = self._dispatch_sync()
            self.write({
                'last_sync_at': fields.Datetime.now(),
                'last_sync_status': result.get('status', 'ok'),
                'last_sync_message': result.get('message', ''),
                'total_synced': (self.total_synced or 0)
                                + result.get('count', 0),
            })
            self.message_post(body=_(
                '✅ Sync OK — fetched %d orders. %s'
            ) % (result.get('count', 0), result.get('message', '')))
            return True
        except NotImplementedError as e:
            self.write({
                'last_sync_status': 'error',
                'last_sync_message': str(e),
                'sync_errors': (self.sync_errors or 0) + 1,
            })
            raise UserError(_('%s adapter not implemented yet: %s') % (
                self.platform, e))
        except Exception as e:
            self.write({
                'last_sync_at': fields.Datetime.now(),
                'last_sync_status': 'error',
                'last_sync_message': str(e),
                'sync_errors': (self.sync_errors or 0) + 1,
            })
            self.message_post(body=_('❌ Sync failed: %s') % str(e))
            raise

    def _dispatch_sync(self):
        """Route to platform-specific adapter. Override per platform by
        inheriting this class or by adding a `_sync_<platform>()` method."""
        self.ensure_one()
        method = getattr(self, '_sync_%s' % self.platform, None)
        if method:
            return method()
        raise NotImplementedError(
            _('No sync adapter registered for platform "%s".') % self.platform)

    # ── Platform adapter stubs ─────────────────────────────────────────
    # Each adapter should return: {'count': int, 'status': 'ok'/'partial'/'error',
    #                              'message': str}
    def _sync_odoo(self):
        """Odoo is the source of truth — no inbound sync needed."""
        return {'count': 0, 'status': 'ok',
                'message': 'Odoo is source of truth, nothing to sync.'}

    def _sync_shopee(self):
        """Shopee Open API v2 adapter.
        TODO when real credentials provided: implement OAuth partner signature
        + GET /api/v2/order/get_order_list + POST /get_order_detail.
        """
        raise NotImplementedError(
            'Shopee adapter stub — fill in _sync_shopee() with partner API calls')

    def _sync_lazada(self):
        """Lazada Open API adapter.
        TODO: implement SellerCenter API signature + /orders/get.
        """
        raise NotImplementedError(
            'Lazada adapter stub — fill in _sync_lazada() with SellerCenter API')

    def _sync_tiktok(self):
        """TikTok Shop API adapter.
        TODO: implement app signature + /api/orders/search.
        """
        raise NotImplementedError(
            'TikTok adapter stub — fill in _sync_tiktok() with TikTok Shop API')

    # ────────────────────────────────────────────────────────────────────
    # Cron entry
    # ────────────────────────────────────────────────────────────────────
    @api.model
    def cron_auto_sync(self):
        """Run auto-sync for all configs where:
          - enabled=True AND auto_sync=True
          - last_sync_at older than (now - sync_interval_minutes)
        Errors on one platform don't stop the others.
        """
        configs = self.sudo().search([
            ('enabled', '=', True),
            ('auto_sync', '=', True),
        ])
        now = fields.Datetime.now()
        results = []
        for cfg in configs:
            interval = max(5, cfg.sync_interval_minutes or 15)
            if cfg.last_sync_at and (now - cfg.last_sync_at) < timedelta(
                    minutes=interval):
                continue  # not due yet
            try:
                cfg.action_sync_now()
                results.append((cfg.platform, 'ok'))
            except Exception as e:
                results.append((cfg.platform, 'error: %s' % e))
        return results

    # ────────────────────────────────────────────────────────────────────
    # Navigation
    # ────────────────────────────────────────────────────────────────────
    def action_view_platform_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Platform Orders — %s') % dict(
                self._fields['platform'].selection).get(self.platform),
            'res_model': 'wms.platform.order',
            'view_mode': 'list,form',
            'domain': [('api_config_id', '=', self.id)],
            'context': {'default_api_config_id': self.id},
        }
