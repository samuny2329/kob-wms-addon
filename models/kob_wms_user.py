# -*- coding: utf-8 -*-
import hashlib
import logging
import secrets
from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class KobWmsUser(models.Model):
    """
    WMS Employee — the single user concept for all warehouse operations.
    Login via /kob/login.  No Odoo license required.
    """
    _name = 'kob.wms.user'
    _description = 'WMS Employee'
    _order = 'name'

    # ── Identity ──
    name = fields.Char('Full Name', required=True)
    position = fields.Char(
        'Position', help='Job title shown everywhere in WMS (e.g. Senior Picker, Packer, Team Lead)')
    username = fields.Char('Username', required=True, index=True, copy=False)
    password_hash = fields.Char('Password Hash', copy=False)
    pin = fields.Char('PIN (4-6 digits)', help='Quick login PIN for handheld devices')

    # ── Odoo Account Bridge (optional) ──
    res_user_id = fields.Many2one(
        'res.users', string='Odoo Account', ondelete='set null',
        help='Optional: link to an Odoo user so this employee can access KPI and backend views.')

    # ── System Role (controls screen access) ──
    role = fields.Selection([
        ('admin', 'Admin'),
        ('supervisor', 'Supervisor'),
        ('picker', 'Picker'),
        ('packer', 'Packer'),
        ('outbound', 'Outbound'),
        ('coordinator', 'Coordinator'),
        ('viewer', 'Viewer'),
    ], string='System Role', default='viewer', required=True,
       help='Controls which WMS screens this employee can access.')
    is_active = fields.Boolean('Active', default=True)

    # ── Session ──
    token = fields.Char('Session Token', index=True, copy=False)
    token_expiry = fields.Datetime('Token Expiry', copy=False)
    last_login = fields.Datetime('Last Login', readonly=True)
    login_count = fields.Integer('Login Count', default=0, readonly=True)

    # ── Audit ──
    failed_login_count = fields.Integer('Failed Logins', default=0)
    locked_until = fields.Datetime('Locked Until')

    has_pin = fields.Boolean(string='Has PIN', compute='_compute_has_pin', store=False)

    _sql_constraints = [
        ('username_uniq', 'unique(username)', 'Username must be unique!'),
    ]

    def name_get(self):
        """Show  'Name (Position)'  in dropdowns when position is set."""
        result = []
        for emp in self:
            label = emp.name
            if emp.position:
                label = f"{emp.name} ({emp.position})"
            result.append((emp.id, label))
        return result

    @api.depends('pin')
    def _compute_has_pin(self):
        for user in self:
            user.has_pin = bool(user.pin)

    # ── Password Hashing (PBKDF2-SHA256, used for full passwords) ──

    @staticmethod
    def _hash_password(password):
        salt = secrets.token_hex(16)
        dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100_000)
        return f"{salt}${dk.hex()}"

    @staticmethod
    def _verify_password(password, password_hash):
        if not password_hash or '$' not in password_hash:
            return False
        salt, stored_hash = password_hash.split('$', 1)
        dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100_000)
        return secrets.compare_digest(dk.hex(), stored_hash)

    # ── PIN Hashing (SHA256 + app-level salt, deterministic) ──
    _PIN_SALT = "kob_wms_pin_2025"

    @classmethod
    def _hash_pin(cls, pin):
        """SHA256 with a fixed app salt — deterministic, easy to verify."""
        raw = (cls._PIN_SALT + str(pin)).encode('utf-8')
        return hashlib.sha256(raw).hexdigest()

    @classmethod
    def _verify_pin(cls, pin, stored):
        """Verify PIN against SHA256 hash. Falls back to PBKDF2 for old hashes."""
        if not stored:
            return False
        expected = cls._hash_pin(pin)
        if secrets.compare_digest(expected, stored):
            return True
        # Legacy fallback: old PBKDF2 hash (contains '$')
        if '$' in stored:
            return cls._verify_password(str(pin), stored)
        return False

    # ── Public API ──

    def set_password(self, password):
        self.ensure_one()
        if len(password) < 6:
            raise ValidationError('Password must be at least 6 characters.')
        self.password_hash = self._hash_password(password)

    def set_pin(self, pin):
        self.ensure_one()
        pin = str(pin).strip()
        if not pin.isdigit() or len(pin) < 4 or len(pin) > 6:
            raise ValidationError('PIN must be 4-6 digits.')
        self.pin = self._hash_pin(pin)

    @api.model
    def authenticate(self, username, password):
        user = self.sudo().search([
            ('username', '=', username),
            ('is_active', '=', True),
        ], limit=1)
        if not user:
            return False

        # Lockout: 5 failed → 15 min lock
        if user.locked_until and user.locked_until > fields.Datetime.now():
            return False

        if not self._verify_password(password, user.password_hash):
            user.sudo().write({
                'failed_login_count': user.failed_login_count + 1,
                'locked_until': (
                    fields.Datetime.add(fields.Datetime.now(), minutes=15)
                    if user.failed_login_count + 1 >= 5 else False
                ),
            })
            return False

        token = secrets.token_urlsafe(32)
        user.sudo().write({
            'token': token,
            'token_expiry': fields.Datetime.add(fields.Datetime.now(), hours=8),
            'last_login': fields.Datetime.now(),
            'login_count': user.login_count + 1,
            'failed_login_count': 0,
            'locked_until': False,
        })
        return {'token': token, 'user_id': user.id, 'name': user.name, 'role': user.role}

    @api.model
    def authenticate_pin(self, username, pin):
        try:
            from datetime import timedelta
            pin_str = str(pin).strip()
            user = self.sudo().search([
                ('username', '=', username),
                ('is_active', '=', True),
            ], limit=1)

            if not user:
                return {'ok': False, 'reason': 'user_not_found'}

            # Read pin fresh (bypass ORM cache)
            user.invalidate_recordset(['pin'])
            stored = user.pin

            _logger.info("authenticate_pin: user=%s stored_len=%s",
                         username, len(stored) if stored else 0)

            if not stored:
                return {'ok': False, 'reason': 'no_pin'}

            PIN_SALT = 'kob_wms_pin_2025'
            ok = False

            # 1. Plain text
            if stored == pin_str:
                ok = True

            # 2. SHA256 with app salt
            if not ok:
                expected = hashlib.sha256(
                    (PIN_SALT + pin_str).encode('utf-8')).hexdigest()
                if secrets.compare_digest(stored, expected):
                    ok = True

            # 3. PBKDF2 legacy (salt$hash)
            if not ok and '$' in stored:
                try:
                    salt, old_hash = stored.split('$', 1)
                    dk = hashlib.pbkdf2_hmac(
                        'sha256', pin_str.encode('utf-8'),
                        salt.encode('utf-8'), 100_000)
                    ok = secrets.compare_digest(dk.hex(), old_hash)
                except Exception:
                    pass

            _logger.info("authenticate_pin: user=%s ok=%s", username, ok)

            if not ok:
                return {'ok': False, 'reason': 'wrong_pin'}

            token = secrets.token_urlsafe(32)
            now = fields.Datetime.now()
            user.sudo().write({
                'token':        token,
                'token_expiry': now + timedelta(hours=8),
                'last_login':   now,
                'login_count':  user.login_count + 1,
            })
            return {'ok': True, 'token': token, 'user_id': user.id,
                    'name': user.name, 'role': user.role}

        except Exception as e:
            _logger.exception("authenticate_pin CRASH for %s: %s", username, e)
            return {'ok': False, 'reason': 'server_error', 'message': str(e)}

    @api.model
    def verify_token(self, token):
        if not token:
            return False
        user = self.sudo().search([('token', '=', token), ('is_active', '=', True)], limit=1)
        if not user or not user.token_expiry:
            return False
        if user.token_expiry < fields.Datetime.now():
            user.sudo().write({'token': False, 'token_expiry': False})
            return False
        return user

    def logout(self):
        self.sudo().write({'token': False, 'token_expiry': False})

    def has_permission(self, permission):
        self.ensure_one()
        role_perms = {
            'admin': {'pick', 'pack', 'scan', 'dispatch', 'inventory', 'recon', 'kpi', 'users', 'settings'},
            'supervisor': {'pick', 'pack', 'scan', 'dispatch', 'inventory', 'recon', 'kpi'},
            'picker': {'pick', 'inventory'},
            'packer': {'pack'},
            'outbound': {'scan', 'dispatch'},
            'coordinator': {'recon', 'kpi'},
            'viewer': {'kpi'},
        }
        return permission in role_perms.get(self.role, set())

    # ── Init (called from data XML on module install) ──

    @api.model
    def _init_default_passwords(self):
        users = self.sudo().search([('password_hash', '=', False)])
        for user in users:
            user.set_password('123456')

    @api.model
    def _init_default_pins(self):
        """Reset ALL active users to PIN 1234 (plain text for now)."""
        users = self.sudo().search([('is_active', '=', True)])
        users.write({'pin': '1234'})
        _logger.info("_init_default_pins: set PIN=1234 (plain) for %s users", len(users))

    # ── Backend Actions (form buttons) ──

    def action_set_password(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Set Password',
            'res_model': 'kob.wms.user.set.password',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_user_id': self.id},
        }

    def action_set_pin(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Set PIN',
            'res_model': 'kob.wms.user.set.pin',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_user_id': self.id},
        }

    def action_unlock(self):
        self.write({'locked_until': False, 'failed_login_count': 0})

    def action_force_logout(self):
        self.logout()
