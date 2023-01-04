# Copyright (c) 2021, ALYF GmbH and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class JiraSettings(Document):
	def get_user_cost(self) -> "dict[str, float]":
		return {user.email: user.costing_rate for user in self.billing}

	@frappe.whitelist()
	def start_snyc(self) -> None:
		"""Starts the sync process for Jira and ERPNext"""
		from jira.tasks.daily import sync_work_logs_from_jira

		frappe.has_permission("Jira Settings", throw=True)
		frappe.has_permission("Timesheet", "create", throw=True)

		frappe.enqueue(
			sync_work_logs_from_jira, queue="long", jira_settings_name=self.name
		)
