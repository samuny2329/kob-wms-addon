/** @odoo-module **/
import { Navbar } from "@point_of_sale/app/navbar/navbar";
import { patch } from "@web/core/utils/patch";

// Add Pick button to POS navbar
patch(Navbar.prototype, {
    onClickPick() {
        this.pos.showScreen("WmsPickScreen");
    },
});
