"""WMS Platform Order — raw order records pulled from marketplaces.

Stores the raw platform order payload + maps to an internal
`sale.order` and `wms.sales.order` for fulfilment.

States:
  - received:  raw payload stored, not yet mapped
  - mapped:    sale.order created
  - fulfilled: wms.sales.order created & fulfilled
  - cancelled: platform cancelled the order
  - error:     mapping failed (see error_message)
"""
import json

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class WmsPlatformOrder(models.Model):
    _name = 'wms.platform.order'
    _description = 'WMS Platform Order (raw from marketplace)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'platform_date desc, id desc'
    _rec_name = 'platform_order_no'

    name = fields.Char(compute='_compute_name', store=True)
    platform_order_no = fields.Char(
        string='Platform Order No.', required=True, index=True,
        help='Marketplace order number (Shopee SN / Lazada ID / TikTok OrderID)')
    api_config_id = fields.Many2one(
        'wms.api.config', string='Platform Config',
        required=True, ondelete='restrict', tracking=True)
    platform = fields.Selection(
        related='api_config_id.platform', store=True)

    # ── Raw payload from platform ───────────────────────────────────────
    payload_json = fields.Text(
        string='Raw Payload',
        help='Full JSON payload as returned by the platform API')
    platform_date = fields.Datetime(
        string='Platform Order Date', tracking=True)
    platform_status = fields.Char(
        string='Platform Status', tracking=True,
        help='As reported by the marketplace (UNPAID / READY_TO_SHIP / etc.)')
    buyer_name = fields.Char(string='Buyer')
    total_amount = fields.Float(string='Total Amount', digits=(12, 2))
    currency_code = fields.Char(string='Currency', default='THB')

    # ── Sync state ──────────────────────────────────────────────────────
    state = fields.Selection([
        ('received', '📥 Received'),
        ('mapped',   '🔗 Mapped'),
        ('fulfilled','✅ Fulfilled'),
        ('cancelled','❌ Cancelled'),
        ('error',    '⚠️ Error'),
    ], default='received', tracking=True, required=True)
    error_message = fields.Text(string='Error Message')

    # ── Links to internal records ───────────────────────────────────────
    sale_order_id = fields.Many2one(
        'sale.order', string='Sale Order', ondelete='set null')
    wms_sales_order_id = fields.Many2one(
        'wms.sales.order', string='WMS Order', ondelete='set null')

    company_id = fields.Many2one(
        'res.company', related='api_config_id.company_id', store=True)

    _sql_constraints = [
        ('platform_order_no_unique',
         'unique(api_config_id, platform_order_no)',
         'Platform order number must be unique per platform config.'),
    ]

    @api.depends('platform', 'platform_order_no')
    def _compute_name(self):
        for rec in self:
            rec.name = '[%s] %s' % (
                (rec.platform or '??').upper(),
                rec.platform_order_no or '—')

    # ────────────────────────────────────────────────────────────────────
    # Create / parse payload
    # ────────────────────────────────────────────────────────────────────
    @api.model
    def register_from_payload(self, api_config, payload):
        """Idempotent create-or-update from a normalised payload dict.

        payload dict contract:
          {
            'platform_order_no': str (required),
            'platform_date': datetime|str,
            'platform_status': str,
            'buyer_name': str,
            'total_amount': float,
            'currency_code': str,
            'raw': dict (full raw payload from platform),
          }
        Returns the `wms.platform.order` record.
        """
        order_no = payload.get('platform_order_no')
        if not order_no:
            raise UserError(_('Platform payload missing platform_order_no'))

        vals = {
            'api_config_id': api_config.id,
            'platform_order_no': order_no,
            'platform_date': payload.get('platform_date'),
            'platform_status': payload.get('platform_status'),
            'buyer_name': payload.get('buyer_name'),
            'total_amount': payload.get('total_amount', 0.0),
            'currency_code': payload.get('currency_code') or 'THB',
            'payload_json': json.dumps(payload.get('raw', payload),
                                      ensure_ascii=False, default=str),
        }

        existing = self.sudo().search([
            ('api_config_id', '=', api_config.id),
            ('platform_order_no', '=', order_no),
        ], limit=1)
        if existing:
            existing.write({k: v for k, v in vals.items()
                            if k != 'api_config_id'})
            return existing
        return self.sudo().create(vals)

    # ────────────────────────────────────────────────────────────────────
    # Mapping to sale.order (stub — can be customised per platform)
    # ────────────────────────────────────────────────────────────────────
    def action_map_to_sale_order(self):
        """Create a sale.order from this platform order. Base implementation
        creates a minimal SO with no lines (since product mapping is
        platform-specific). Override in platform adapters."""
        for rec in self:
            if rec.sale_order_id:
                continue
            if not rec.buyer_name:
                rec.write({
                    'state': 'error',
                    'error_message': 'Missing buyer_name — cannot map.',
                })
                continue
            partner = rec._find_or_create_partner()
            so = rec.env['sale.order'].sudo().create({
                'partner_id': partner.id,
                'origin': rec.display_name,
                'company_id': rec.company_id.id,
            })
            rec.write({'sale_order_id': so.id, 'state': 'mapped'})
            rec.message_post(body=_(
                '🔗 Mapped to sale.order <b>%s</b>') % so.name)
        return True

    def _find_or_create_partner(self):
        self.ensure_one()
        if not self.buyer_name:
            return self.env.ref('base.public_partner')
        partner = self.env['res.partner'].sudo().search(
            [('name', '=', self.buyer_name)], limit=1)
        if partner:
            return partner
        return self.env['res.partner'].sudo().create({
            'name': self.buyer_name,
            'customer_rank': 1,
            'comment': _('Auto-created from %s platform order %s') % (
                self.platform or '', self.platform_order_no),
        })

    def action_open_sale_order(self):
        self.ensure_one()
        if not self.sale_order_id:
            raise UserError(_('No sale.order linked yet.'))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'view_mode': 'form',
            'res_id': self.sale_order_id.id,
        }
