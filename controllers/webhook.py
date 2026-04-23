"""Webhook endpoints for marketplace platform push notifications.

Each platform POSTs order events to /kob/webhook/<platform>. Signature is
validated against wms.api.config.webhook_secret using HMAC-SHA256.

Endpoints:
  POST /kob/webhook/shopee   — Shopee push (orders, logistics, etc.)
  POST /kob/webhook/lazada   — Lazada push
  POST /kob/webhook/tiktok   — TikTok Shop push

Each adapter should parse the platform's specific payload shape and call
`env['wms.platform.order'].register_from_payload(api_config, payload)`.
"""
import hmac
import hashlib
import json
import logging

from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


class KobWmsWebhook(http.Controller):

    def _verify_signature(self, platform, raw_body, signature_header):
        """Validate HMAC-SHA256 signature against webhook_secret."""
        api_config = request.env['wms.api.config'].sudo().search([
            ('platform', '=', platform),
            ('enabled', '=', True),
        ], limit=1)
        if not api_config:
            return None, 'Platform not configured or disabled'

        secret = api_config.webhook_secret
        if not secret:
            return None, 'No webhook_secret configured'

        if not signature_header:
            return None, 'Missing signature header'

        expected = hmac.new(
            secret.encode('utf-8'),
            raw_body,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected, signature_header):
            return None, 'Invalid signature'

        return api_config, None

    def _json_response(self, code, data):
        return Response(
            json.dumps(data, ensure_ascii=False),
            status=code,
            content_type='application/json',
        )

    def _handle_platform_webhook(self, platform, signature_header_name):
        """Common handler: validate signature, parse payload, register order."""
        raw_body = request.httprequest.get_data()
        signature = request.httprequest.headers.get(signature_header_name, '')

        api_config, err = self._verify_signature(platform, raw_body, signature)
        if err:
            _logger.warning('%s webhook rejected: %s', platform, err)
            return self._json_response(401, {'error': err})

        try:
            data = json.loads(raw_body.decode('utf-8') or '{}')
        except ValueError as e:
            return self._json_response(400, {'error': 'Invalid JSON: %s' % e})

        # Normalise payload per platform (implementers should fill these out
        # when wiring real platforms).
        payload = self._normalise_payload(platform, data)
        if not payload.get('platform_order_no'):
            return self._json_response(400, {'error': 'No platform_order_no in payload'})

        try:
            order = request.env['wms.platform.order'].sudo().register_from_payload(
                api_config, payload)
            return self._json_response(200, {
                'ok': True,
                'platform_order_id': order.id,
                'state': order.state,
            })
        except Exception as e:
            _logger.exception('%s webhook error', platform)
            return self._json_response(500, {'error': str(e)})

    def _normalise_payload(self, platform, data):
        """Extract common fields from platform-specific payload shapes.
        Override per platform as needed.
        """
        if platform == 'shopee':
            return {
                'platform_order_no': data.get('ordersn') or data.get('order_sn'),
                'platform_status': data.get('status'),
                'buyer_name': data.get('buyer_username'),
                'total_amount': data.get('total_amount'),
                'currency_code': data.get('currency'),
                'raw': data,
            }
        if platform == 'lazada':
            return {
                'platform_order_no': str(data.get('order_id') or ''),
                'platform_status': data.get('statuses', [None])[0] if data.get('statuses') else None,
                'buyer_name': data.get('customer_first_name', ''),
                'total_amount': data.get('price'),
                'currency_code': data.get('currency'),
                'raw': data,
            }
        if platform == 'tiktok':
            return {
                'platform_order_no': data.get('order_id'),
                'platform_status': data.get('order_status'),
                'buyer_name': data.get('buyer_name'),
                'total_amount': data.get('payment_info', {}).get('total_amount'),
                'currency_code': data.get('payment_info', {}).get('currency'),
                'raw': data,
            }
        return {'raw': data}

    # ── Routes ──────────────────────────────────────────────────────────
    @http.route('/kob/webhook/shopee', type='http', auth='public',
                methods=['POST'], csrf=False)
    def shopee_webhook(self, **kwargs):
        return self._handle_platform_webhook('shopee', 'Authorization')

    @http.route('/kob/webhook/lazada', type='http', auth='public',
                methods=['POST'], csrf=False)
    def lazada_webhook(self, **kwargs):
        return self._handle_platform_webhook('lazada', 'X-LAZOP-Signature')

    @http.route('/kob/webhook/tiktok', type='http', auth='public',
                methods=['POST'], csrf=False)
    def tiktok_webhook(self, **kwargs):
        return self._handle_platform_webhook('tiktok', 'X-TTS-Signature')
