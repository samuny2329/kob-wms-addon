/** @odoo-module **/
import { Component, useState, onWillStart, onPatched } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";

/**
 * WmsWorkerSystray — SAP HANA style badge.
 * Visible only inside the KOB WMS app.
 */
class WmsWorkerSystray extends Component {
    static template = "kob_wms.WmsWorkerSystray";
    static props    = {};

    setup() {
        this.action = useService("action");
        this.menu   = useService("menu");
        this.state  = useState({ inWms: false });

        try {
            this.worker = JSON.parse(
                localStorage.getItem("wms_worker") || "null"
            ) || {};
        } catch {
            this.worker = {};
        }

        const checkApp = () => {
            const app = this.menu.getCurrentApp();
            this.state.inWms = !!(app && app.xmlid === "kob_wms.menu_kob_wms_root");
        };
        onWillStart(checkApp);
        onPatched(checkApp);
    }

    get isLoggedIn()  { return !!this.worker.id; }
    get workerName()  { return this.worker.name  || ""; }
    get workerRole()  { return this.worker.role  || ""; }
    get initials() {
        return (this.workerName.match(/\b\w/g) || ["?"])
            .slice(0, 2).join("").toUpperCase();
    }
    get roleColor() {
        const map = { manager: "#0070F2", supervisor: "#0A6ED1", worker: "#5B738B" };
        return map[this.workerRole] || "#5B738B";
    }

    logout() {
        localStorage.removeItem("wms_worker");
        this.action.doAction("kob_wms.action_wms_login_screen");
    }
}

registry.category("systray").add(
    "wms_worker_systray",
    { Component: WmsWorkerSystray },
    { sequence: 1 }
);
