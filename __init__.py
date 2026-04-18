from . import models
from . import wizards
from . import controllers


def post_init_hook(env):
    """Clean up orphaned data + drop stale NOT NULL constraints."""
    # Fix: wms_scan_wizard.order_id was required=True in v1, changed to
    # required=False in v2. The column constraint must be dropped manually
    # because Odoo doesn't always auto-drop NOT NULL on transient models.
    try:
        env.cr.execute("""
            ALTER TABLE wms_scan_wizard
            ALTER COLUMN order_id DROP NOT NULL
        """)
    except Exception:
        pass  # table might not exist yet on first install
    env.cr.execute(
        "DELETE FROM wms_courier WHERE id NOT IN ("
        "   SELECT res_id FROM ir_model_data"
        "   WHERE model = 'wms.courier' AND res_id IS NOT NULL)"
        " AND code IN ('EMS', 'FLS', 'JT', 'SPX', 'KISS')"
    )
    defaults = [
        ('EMS', 'Thailand Post', '#e11d48',
         'https://track.thailandpost.co.th/?trackNumber={barcode}'),
        ('FLS', 'Flash Express', '#f59e0b',
         'https://www.flashexpress.com/fle/tracking?se={barcode}'),
        ('JT', 'J&T Express', '#dc2626',
         'https://www.jtexpress.co.th/index/query/gzquery.html?bills={barcode}'),
        ('SPX', 'Shopee Express', '#f97316', ''),
        ('KISS', 'KISS Direct', '#3b82f6', ''),
    ]
    for code, name, color, tracking in defaults:
        existing = env['wms.courier'].search(
            [('code', '=', code)], limit=1)
        if not existing:
            env['wms.courier'].create({
                'code': code,
                'name': name,
                'color_hex': color,
                'tracking_url_template': tracking,
            })
    for platform in ('odoo', 'shopee', 'lazada', 'tiktok'):
        existing = env['wms.api.config'].search(
            [('platform', '=', platform)], limit=1)
        if not existing:
            env['wms.api.config'].create({
                'platform': platform,
                'enabled': platform == 'odoo',
            })
