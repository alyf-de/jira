# Copyright (c) 2021, ALYF GmbH and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document

class JiraSettings(Document):
	def get_user_cost(self) -> "dict[str, float]":
		return {user.email: user.costing_rate for user in self.billing}
