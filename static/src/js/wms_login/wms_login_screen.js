/** @odoo-module **/
import { registry }  from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t }         from "@web/core/l10n/translation";
import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

export class WmsLoginScreen extends Component {
    static template = "kob_wms.WmsLoginScreen";
    static props    = { ...standardActionServiceProps };

    setup() {
        this.orm           = useService("orm");
        this.actionService = useService("action");
        this.notification  = useService("notification");

        this.state = useState({
            workers:        [],
            loading:        true,
            selected:       null,
            pin:            "",
            error:          "",
            authenticating: false,
        });

        this._keyHandler = this._onKey.bind(this);

        onMounted(() => {
            this.loadWorkers();
            document.addEventListener("keydown", this._keyHandler);
        });
        onWillUnmount(() => {
            document.removeEventListener("keydown", this._keyHandler);
        });
    }

    // ── Keyboard ─────────────────────────────────────────────────
    _onKey(ev) {
        if (this.state.authenticating) return;
        if (!this.state.selected) return;
        if (ev.ctrlKey || ev.altKey || ev.metaKey) return;

        if (ev.key >= "0" && ev.key <= "9") {
            ev.preventDefault();
            this.pressDigit(ev.key);
        } else if (ev.key === "Backspace") {
            ev.preventDefault();
            this.pressBackspace();
        } else if (ev.key === "Enter") {
            ev.preventDefault();
            this.submitPin();
        } else if (ev.key === "Escape") {
            ev.preventDefault();
            this.back();
        }
    }

    // ── Ripple effect ─────────────────────────────────────────────
    _createRipple(btn, ev) {
        const rect   = btn.getBoundingClientRect();
        const size   = Math.max(rect.width, rect.height);
        const x      = (ev.clientX - rect.left) - size / 2;
        const y      = (ev.clientY - rect.top)  - size / 2;
        const ripple = document.createElement("span");
        ripple.className  = "wms-ripple";
        ripple.style.cssText = `width:${size}px;height:${size}px;left:${x}px;top:${y}px`;
        btn.appendChild(ripple);
        ripple.addEventListener("animationend", () => ripple.remove(), { once: true });
    }

    // ── Data ──────────────────────────────────────────────────────
    async loadWorkers() {
        this.state.workers = await this.orm.searchRead(
            "kob.wms.user",
            [["is_active", "=", true]],
            ["id", "name", "username", "role", "has_pin", "position"],
            { order: "name asc", limit: 50 }
        );
        this.state.loading = false;
    }

    // ── Worker selection ──────────────────────────────────────────
    selectWorker(worker, ev) {
        if (ev) this._createRipple(ev.currentTarget, ev);
        this.state.selected = worker;
        this.state.pin      = "";
        this.state.error    = "";
    }

    back() {
        this.state.selected = null;
        this.state.pin      = "";
        this.state.error    = "";
    }

    // ── PIN pad ───────────────────────────────────────────────────
    pressDigit(d) {
        if (this.state.authenticating) return;
        if (this.state.pin.length >= 6) return;
        this.state.pin  += String(d);
        this.state.error = "";
        if (this.state.pin.length === 6) this.submitPin();
    }

    pressDigitWithRipple(d, ev) {
        this._createRipple(ev.currentTarget, ev);
        this.pressDigit(d);
    }

    pressBackspace() {
        if (this.state.authenticating) return;
        this.state.pin = this.state.pin.slice(0, -1);
    }

    pressBackspaceWithRipple(ev) {
        this._createRipple(ev.currentTarget, ev);
        this.pressBackspace();
    }

    pressConfirmWithRipple(ev) {
        this._createRipple(ev.currentTarget, ev);
        this.submitPin();
    }

    // ── Submit ────────────────────────────────────────────────────
    async submitPin() {
        const { selected, pin } = this.state;
        if (!selected || pin.length < 4 || this.state.authenticating) return;
        this.state.authenticating = true;

        let result = false;
        try {
            const resp = await fetch("/kob/api/pin", {
                method:  "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    jsonrpc: "2.0", method: "call", id: Date.now(),
                    params: { username: selected.username, pin },
                }),
            });
            const json = await resp.json();
            result = json.result || false;
        } catch (err) {
            console.error("pin auth error:", err);
        }

        if (result && result.ok && result.token) {
            localStorage.setItem("wms_worker", JSON.stringify({
                id:    result.user_id,
                name:  result.name,
                role:  result.role,
                token: result.token,
            }));
            this.notification.add(_t("Welcome, %s!", result.name), { type: "success" });
            this.actionService.doAction("kob_wms.action_wms_dashboard");
        } else {
            const reason = result && result.reason;
            if      (reason === "no_pin")        this.state.error = _t("No PIN set — contact supervisor.");
            else if (reason === "user_not_found") this.state.error = _t("Employee account not found.");
            else if (reason === "server_error")   this.state.error = (result.message || "Server error") + " [contact admin]";
            else                                  this.state.error = _t("Incorrect PIN. Please try again.");
            this.state.pin = "";
        }
        this.state.authenticating = false;
    }

    // ── Helpers ───────────────────────────────────────────────────
    get initials() {
        if (!this.state.selected) return "";
        return this.state.selected.name
            .split(" ").map(w => w[0]).join("").toUpperCase().slice(0, 2);
    }

    getWorkerInitials(worker) {
        return worker.name.split(" ").map(w => w[0]).join("").toUpperCase().slice(0, 2);
    }

    getAvatarClass(role) {
        return {
            admin:       "wms-av-admin",
            supervisor:  "wms-av-supervisor",
            picker:      "wms-av-picker",
            packer:      "wms-av-packer",
            outbound:    "wms-av-outbound",
            coordinator: "wms-av-coordinator",
        }[role] || "wms-av-default";
    }

    getRoleBadgeClass(role) {
        return {
            admin:       "wms-rb-admin",
            supervisor:  "wms-rb-supervisor",
            picker:      "wms-rb-picker",
            packer:      "wms-rb-packer",
            outbound:    "wms-rb-outbound",
            coordinator: "wms-rb-coordinator",
        }[role] || "wms-rb-default";
    }

    // old compat — kept so any external refs still resolve
    getRoleBadge(role) { return "badge " + this.getRoleBadgeClass(role); }

    get pinDots() {
        return Array.from({ length: 6 }, (_, i) => i < this.state.pin.length);
    }
}

registry.category("actions").add("kob_wms.wms_login_screen", WmsLoginScreen);
