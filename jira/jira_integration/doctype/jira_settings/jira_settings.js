// Copyright (c) 2021, Alyf GmbH and contributors
// For license information, please see license.txt

frappe.ui.form.on('Jira Settings', {
	refresh: function (frm) {
		if (!frm.is_new() && frm.doc.enabled) {
			frm.add_custom_button(__('Sync'), function () {
				frappe.show_alert({ message: __("Syncing"), indicator: 'blue' });
				frappe.call({
					method: "jira.tasks.daily.sync_work_logs_from_jira",
					args: {
						project: frm.doc.name
					},
					callback: function (r) {
						frappe.show_alert({ message: __("Synced"), indicator: 'green' });
					}
				});
			});
		}
	}
});
