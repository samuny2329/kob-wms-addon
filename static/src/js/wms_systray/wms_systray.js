/** @odoo-module **/
import { Component } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";

/**
 * WmsWorkerSystray — shows the currently-logged-in kob.wms.user
 * (read from localStorage) in Odoo's top-right systray bar.
 * Clicking Logout clears the WMS session and redirects to the
 * PIN login screen.
 */
class WmsWorkerSystray extends Component {
    static template = "kob_wms.WmsWorkerSystray";
    static props    = {};

    setup() {
        this.action = useService("action");
        try {
            this.worker = JSON.parse(
                localStorage.getItem("wms_worker") || "null"
            ) || {};
        } catch {
            this.worker = {};
        }
    }

    get isLoggedIn()  { return !!this.worker.id; }
    get workerName()  { return this.worker.name || ""; }
    get initials() {
        return (this.workerName.match(/\b\w/g) || ["?"])
            .slice(0, 2).join("").toUpperCase();
    }

    logout() {
        localStorage.removeItem("wms_worker");
        this.action.doAction("kob_wms.action_wms_login_screen");
    }
}

registry.category("systray").add(
    "wms_worker_systray",
    { Component: WmsWorkerSystray },
    { sequence: 1 }   // appears near the left of the systray (low = left)
);
