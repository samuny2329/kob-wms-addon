# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.exceptions import ValidationError


class WmsUserSetPassword(models.TransientModel):
    _name = 'kob.wms.user.set.password'
    _description = 'Set WMS User Password'

    user_id = fields.Many2one('kob.wms.user', required=True, readonly=True)
    new_password = fields.Char('New Password', required=True)
    confirm_password = fields.Char('Confirm Password', required=True)

    def action_confirm(self):
        self.ensure_one()
        if self.new_password != self.confirm_password:
            raise ValidationError('Passwords do not match.')
        self.user_id.set_password(self.new_password)
        return {'type': 'ir.actions.act_window_close'}


class WmsUserSetPin(models.TransientModel):
    _name = 'kob.wms.user.set.pin'
    _description = 'Set WMS User PIN'

    user_id = fields.Many2one('kob.wms.user', required=True, readonly=True)
    new_pin = fields.Char('New PIN (4-6 digits)', required=True)
    confirm_pin = fields.Char('Confirm PIN', required=True)

    def action_confirm(self):
        self.ensure_one()
        if self.new_pin != self.confirm_pin:
            raise ValidationError('PINs do not match.')
        self.user_id.set_pin(self.new_pin)
        return {'type': 'ir.actions.act_window_close'}
