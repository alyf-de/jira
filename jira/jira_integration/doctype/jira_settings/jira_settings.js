// Copyright (c) 2021, Alyf GmbH and contributors
// For license information, please see license.txt

frappe.ui.form.on("Jira Settings", {
	refresh: function (frm) {
		if (!frm.is_new() && frm.doc.enabled) {
			frm.add_custom_button(__("Sync"), function () {
				frm.call("start_snyc", {}, (r) => {
					frappe.show_alert({
						message: __("Sync enqueued"),
						indicator: "green",
					});
				});
			});
		}
	},
});
