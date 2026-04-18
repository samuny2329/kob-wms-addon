/** @odoo-module **/
import { Component } from "@odoo/owl";

// ── Accent colours per mode ──────────────────────────────────────
export const MODE_ACCENT = {
    pick:     "#714B67",
    pack:     "#1C6EA4",
    outbound: "#C2500A",
    dispatch: "#1A9B38",
};

// ── Action tag per mode ──────────────────────────────────────────
export const MODE_ACTIONS = {
    pick:     "kob_wms.pick_screen",
    pack:     "kob_wms.pack_screen",
    outbound: "kob_wms.outbound_screen",
    dispatch: "kob_wms.dispatch_screen",
};

// ── Platform helpers ─────────────────────────────────────────────
const PLATFORM_MAP = {
    shopee:  { badge: "text-bg-warning",              icon: "fa-shopping-bag" },
    lazada:  { badge: "text-bg-primary",              icon: "fa-shopping-cart" },
    tiktok:  { badge: "text-bg-dark",                 icon: "fa-music" },
    pos:     { badge: "text-bg-info",                 icon: "fa-desktop" },
    odoo:    { badge: "text-bg-secondary",            icon: "fa-cog" },
    manual:  { badge: "text-bg-light text-dark",      icon: "fa-pencil" },
    all:     { badge: "text-bg-secondary",            icon: "fa-list" },
};

export function getSlaClass(order) {
    if (order.sla_status === "breached") return "badge text-bg-danger";
    if (order.sla_status === "at_risk")  return "badge text-bg-warning";
    return "badge text-bg-success";
}

export function getPlatformBadge(platform) {
    return "badge " + ((PLATFORM_MAP[platform] || PLATFORM_MAP.manual).badge);
}

export function getPlatformIcon(p) {
    return (PLATFORM_MAP[p] || PLATFORM_MAP.all).icon;
}

// ── WmsTopNav ────────────────────────────────────────────────────
export class WmsTopNav extends Component {
    static template = "kob_wms.WmsTopNav";
    static props = {
        activeMode:  String,
        accentColor: { type: String, optional: true },
        onNavigate:  Function,
        onBack:      Function,
    };
}

// ── WmsPickCard (shared between Pick and Pack screens) ───────────
export class WmsPickCard extends Component {
    static template = "kob_wms.WmsPickCard";
    static props = {
        line:        Object,
        imageUrl:    [String, Boolean],
        isFlashing:  Boolean,
        flashType:   { type: String, optional: true },
        isDone:      Boolean,
        accentColor: { type: String, optional: true },
        // which fields to show as "qty / total"
        qtyField:    { type: String, optional: true },
        totalField:  { type: String, optional: true },
    };

    get qty()   { return this.props.line[this.props.qtyField   || "picked_qty"]   ?? 0; }
    get total() { return this.props.line[this.props.totalField || "expected_qty"] ?? 0; }
}
