import io
import base64
from datetime import datetime
from odoo import models, fields, tools, _


class WmsProductBoxAnalytics(models.Model):
    """Product vs Box analytics SQL view.

    Joins wms.sales.order.line → wms.sales.order → wms.box.size so we can see:
    - Which product ships in which box
    - How much fill % that product generates
    - Bubble wrap + tape + total packaging cost per product×box combo
    """
    _name        = 'wms.product.box.analytics'
    _description = 'Product vs Box Analytics'
    _auto        = False
    _order       = 'order_count desc'

    # ── Dimensions ───────────────────────────────────────────
    product_id     = fields.Many2one('product.product', string='Product',   readonly=True)
    actual_box_id  = fields.Many2one('wms.box.size',    string='Box Used',  readonly=True)
    platform       = fields.Selection([
        ('odoo', 'Odoo'), ('shopee', 'Shopee'), ('lazada', 'Lazada'),
        ('tiktok', 'TikTok'), ('pos', 'POS'), ('manual', 'Manual'),
    ], string='Platform', readonly=True)

    # ── Volume comparison ────────────────────────────────────
    product_vol_m3 = fields.Float(
        string='Product Vol (m³)', readonly=True, digits=(12, 6),
        help='Volume from product.template (L×W×H in m³)')
    box_vol_m3     = fields.Float(
        string='Box Vol (m³)',     readonly=True, digits=(12, 6),
        help='Volume of the box used')
    avg_fill_pct   = fields.Float(
        string='Avg Fill %',      readonly=True, digits=(5, 1),
        help='Average box fill % for orders containing this product in this box')

    # ── Usage counters ───────────────────────────────────────
    order_count  = fields.Integer(string='Orders',        readonly=True)
    total_qty    = fields.Float(  string='Total Qty',     readonly=True, digits=(12, 2))
    avg_qty      = fields.Float(  string='Avg Qty/Order', readonly=True, digits=(8, 2))

    # ── Cost breakdown ────────────────────────────────────────
    avg_box_cost    = fields.Float(string='Box/Order (฿)',    readonly=True, digits=(10, 2))
    avg_tape_cost   = fields.Float(string='Tape/Order (฿)',   readonly=True, digits=(10, 2))
    avg_bubble_cost = fields.Float(string='Bubble/Order (฿)', readonly=True, digits=(10, 2))
    avg_pack_cost   = fields.Float(string='Total Mat/Order (฿)', readonly=True, digits=(10, 2))
    total_pack_cost = fields.Float(string='Total Mat Cost (฿)',  readonly=True, digits=(12, 2))

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW wms_product_box_analytics AS
            SELECT
                row_number() OVER ()        AS id,
                l.product_id,
                o.actual_box_id,
                o.platform,

                -- Product volume (from product.template via product.product)
                COALESCE(pt.volume, 0)      AS product_vol_m3,

                -- Box volume (from wms_box_size, stored in m³)
                COALESCE(bs.volume, 0)      AS box_vol_m3,

                -- Avg fill % for orders containing this product in this box
                ROUND(COALESCE(AVG(o.box_fill_pct), 0)::numeric, 1)  AS avg_fill_pct,

                -- Usage
                COUNT(DISTINCT o.id)        AS order_count,
                COALESCE(SUM(l.picked_qty), 0)  AS total_qty,
                ROUND(COALESCE(AVG(l.picked_qty), 0)::numeric, 2) AS avg_qty,

                -- Costs (from order level — one cost set per order regardless of line count)
                ROUND(COALESCE(AVG(o.box_cost_est),    0)::numeric, 2) AS avg_box_cost,
                ROUND(COALESCE(AVG(o.tape_cost_est),   0)::numeric, 2) AS avg_tape_cost,
                ROUND(COALESCE(AVG(o.bubble_cost_est), 0)::numeric, 2) AS avg_bubble_cost,
                ROUND(COALESCE(AVG(o.total_pack_cost), 0)::numeric, 2) AS avg_pack_cost,
                ROUND(COALESCE(SUM(o.total_pack_cost), 0)::numeric, 2) AS total_pack_cost

            FROM wms_sales_order_line l
            JOIN wms_sales_order o
                ON o.id = l.order_id
               AND o.actual_box_id IS NOT NULL
               AND o.status IN ('packed', 'shipped')
            JOIN product_product pp
                ON pp.id = l.product_id
            JOIN product_template pt
                ON pt.id = pp.product_tmpl_id
            JOIN wms_box_size bs
                ON bs.id = o.actual_box_id
            WHERE l.product_id IS NOT NULL
              AND COALESCE(l.picked_qty, 0) > 0
            GROUP BY
                l.product_id,
                o.actual_box_id,
                o.platform,
                pt.volume,
                bs.volume
        """)

    # ── Excel Export ──────────────────────────────────────────

    def action_export_xlsx(self):
        """Generate Product vs Box Excel report and return as download."""
        try:
            import xlsxwriter
        except ImportError:
            from odoo.exceptions import UserError
            raise UserError(_('xlsxwriter not installed. Run: pip install xlsxwriter'))

        records = self.search([], order='order_count desc')

        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output, {'in_memory': True})
        ws = wb.add_worksheet('Product vs Box')

        # ── Styles ──────────────────────────────────────────
        hdr = wb.add_format({
            'bold': True, 'bg_color': '#1F2937', 'font_color': '#FFFFFF',
            'border': 1, 'align': 'center', 'valign': 'vcenter',
            'text_wrap': True,
        })
        title_fmt = wb.add_format({
            'bold': True, 'font_size': 14, 'font_color': '#1F2937'
        })
        sub_fmt = wb.add_format({
            'italic': True, 'font_color': '#6B7280', 'font_size': 9
        })
        num2  = wb.add_format({'num_format': '#,##0.00', 'border': 1})
        num6  = wb.add_format({'num_format': '0.000000', 'border': 1})
        pct   = wb.add_format({'num_format': '0.0"%"', 'border': 1})
        int_f = wb.add_format({'num_format': '#,##0',   'border': 1})
        txt   = wb.add_format({'border': 1})
        # Fill % conditional colours
        pct_red   = wb.add_format({'num_format': '0.0"%"', 'border': 1,
                                   'bg_color': '#FEE2E2', 'font_color': '#991B1B'})
        pct_yel   = wb.add_format({'num_format': '0.0"%"', 'border': 1,
                                   'bg_color': '#FEF9C3', 'font_color': '#854D0E'})
        pct_grn   = wb.add_format({'num_format': '0.0"%"', 'border': 1,
                                   'bg_color': '#DCFCE7', 'font_color': '#166534'})

        # ── Title block ──────────────────────────────────────
        ws.merge_range('A1:N1', 'KOB WMS — Product vs Box Analytics', title_fmt)
        ws.write('A2', f'Generated: {datetime.now().strftime("%d/%m/%Y %H:%M")}', sub_fmt)
        ws.write('B2', f'Total rows: {len(records)}', sub_fmt)

        # ── Header row ───────────────────────────────────────
        headers = [
            'Product', 'SKU / Internal Ref', 'Box Used',
            'Orders', 'Total Qty', 'Avg Qty/Order',
            'Product Vol (m³)', 'Box Vol (m³)', 'Fill %',
            'Box/Order (฿)', 'Tape/Order (฿)', 'Bubble/Order (฿)',
            'Total Mat/Order (฿)', 'Total Mat Cost (฿)',
        ]
        ws.set_row(2, 32, None)
        for col, h in enumerate(headers):
            ws.write(2, col, h, hdr)

        # ── Column widths ────────────────────────────────────
        widths = [32, 18, 16, 8, 10, 12, 16, 14, 8, 14, 14, 16, 18, 18]
        for col, w in enumerate(widths):
            ws.set_column(col, col, w)

        # ── Data rows ────────────────────────────────────────
        row = 3
        for rec in records:
            fill = rec.avg_fill_pct
            fill_fmt = pct_red if fill < 40 else (pct_yel if fill < 60 else pct_grn)

            ws.write(row, 0,  rec.product_id.display_name or '',       txt)
            ws.write(row, 1,  rec.product_id.default_code or '',        txt)
            ws.write(row, 2,  rec.actual_box_id.label or
                               rec.actual_box_id.code or '',             txt)
            ws.write(row, 3,  rec.order_count,                          int_f)
            ws.write(row, 4,  rec.total_qty,                            num2)
            ws.write(row, 5,  rec.avg_qty,                              num2)
            ws.write(row, 6,  rec.product_vol_m3,                       num6)
            ws.write(row, 7,  rec.box_vol_m3,                           num6)
            ws.write(row, 8,  rec.avg_fill_pct,                         fill_fmt)
            ws.write(row, 9,  rec.avg_box_cost,                         num2)
            ws.write(row, 10, rec.avg_tape_cost,                        num2)
            ws.write(row, 11, rec.avg_bubble_cost,                      num2)
            ws.write(row, 12, rec.avg_pack_cost,                        num2)
            ws.write(row, 13, rec.total_pack_cost,                      num2)
            row += 1

        # ── Totals row ───────────────────────────────────────
        tot_fmt = wb.add_format({
            'bold': True, 'bg_color': '#F3F4F6', 'border': 1,
            'num_format': '#,##0.00',
        })
        tot_int = wb.add_format({
            'bold': True, 'bg_color': '#F3F4F6', 'border': 1,
            'num_format': '#,##0',
        })
        tot_txt = wb.add_format({
            'bold': True, 'bg_color': '#F3F4F6', 'border': 1,
        })
        ws.write(row, 0,  'TOTAL', tot_txt)
        ws.write(row, 1,  '', tot_txt)
        ws.write(row, 2,  '', tot_txt)
        ws.write(row, 3,  sum(r.order_count  for r in records), tot_int)
        ws.write(row, 4,  sum(r.total_qty    for r in records), tot_fmt)
        for c in range(5, 13):
            ws.write(row, c, '', tot_txt)
        ws.write(row, 13, sum(r.total_pack_cost for r in records), tot_fmt)

        wb.close()
        xlsx_data = output.getvalue()

        # ── Save as attachment & return download URL ──────────
        fname = f'product_box_analytics_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx'
        att = self.env['ir.attachment'].create({
            'name': fname,
            'type': 'binary',
            'datas': base64.b64encode(xlsx_data),
            'mimetype': (
                'application/vnd.openxmlformats-officedocument'
                '.spreadsheetml.sheet'
            ),
            'res_model': self._name,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{att.id}?download=true',
            'target': 'self',
        }
