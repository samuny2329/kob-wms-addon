from odoo import models, fields, api, _
from odoo.exceptions import UserError


class PosConfig(models.Model):
    _inherit = 'pos.config'

    wms_fulfillment_mode = fields.Selection(
        [
            ('disabled', 'Disabled (no WMS sync)'),
            ('immediate', 'Immediate — take home (auto-packed)'),
            ('pick_pack', 'Pick / Pack / Ship via WMS'),
        ],
        string='WMS Fulfillment Mode',
        default='immediate',
        help='Controls how POS orders flow into the KOB WMS pick/pack/ship '
             'pipeline.\n'
             '* Disabled: POS orders are NOT mirrored to WMS.\n'
             '* Immediate: POS orders create WMS orders at status "packed" '
             'so workers only have to dispatch them.\n'
             '* Pick / Pack / Ship: POS orders create WMS orders at status '
             '"pending" so workers pick from the warehouse, pack into a box '
             'and dispatch via courier. Useful for preorders, ship-from-store '
             'and back-warehouse items.',
    )

    wms_default_courier_id = fields.Many2one(
        'wms.courier', string='Default WMS Courier',
        help='Courier auto-assigned to WMS orders coming from this POS.',
    )

    # ------------------------------------------------------------------
    # Launcher for dedicated WMS POS stations
    # ------------------------------------------------------------------
    _wms_station_map = {
        'pick': ('KOB WMS - Pick (F1)', 'pick_pack'),
        'pack': ('KOB WMS - Pack (F2)', 'pick_pack'),
        'out':  ('KOB WMS - Outbound (F3)', 'immediate'),
    }

    @api.model
    def _get_or_create_wms_pos(self, mode):
        """Return (creating if needed) the dedicated POS config for a WMS
        station. Copies from the first existing pos.config so all required
        fields are inherited."""
        name, fulfillment = self._wms_station_map.get(mode, (None, None))
        if not name:
            raise UserError(_('Unknown WMS POS mode: %s') % mode)

        existing = self.search([('name', '=', name)], limit=1)
        if existing:
            return existing

        # Need a template to copy (Odoo POS requires many fields to be set)
        template = self.search([], limit=1)
        if not template:
            raise UserError(_(
                'No POS configuration exists yet.\n'
                'Please open Point of Sale app and create at least one Shop '
                'before launching a WMS station.'
            ))
        new_config = template.copy({
            'name': name,
            'wms_fulfillment_mode': fulfillment,
        })
        new_config.message_post(body=_(
            'Auto-created by KOB WMS for the "%s" station.'
        ) % mode.upper())
        return new_config

    @api.model
    def action_open_kob_wms_pos(self, mode='pick'):
        """Launch the standard Odoo POS UI for a dedicated WMS station."""
        config = self._get_or_create_wms_pos(mode)
        return config.open_ui()
