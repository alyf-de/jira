# Copyright (c) 2021, Alyf GmbH and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import now_datetime, get_datetime, get_datetime_str, flt, getdate
from jira.jira_client import JiraClient


@frappe.whitelist()
def sync_work_logs_from_jira(project=None):
	filters = {"enabled": 1}

	if project:
		filters["name"] = project

	for jira in frappe.get_all("Jira Settings", filters=filters):
		jira_settings = frappe.get_doc("Jira Settings", jira.name)
		JiraWorkspace(jira_settings).sync_work_logs()
		jira_settings.last_synced_on = now_datetime()
		jira_settings.save()


class JiraWorkspace:
	def __init__(self, jira_settings):
		self.jira_settings = jira_settings
		self.user_list = [user.email for user in self.jira_settings.billing]
		self.jira_client = JiraClient(
			jira_settings.url,
			jira_settings.api_user,
			jira_settings.get_password(fieldname="api_key"),
		)
		self.issues = {}
		self.worklogs = {}
		self._init_project_map()
		self._init_user_costing()

	def _init_project_map(self):
		self.project_map = {}

		for project in self.jira_settings.mappings:
			self.project_map[project.jira_project_key] = {
				"erpnext_project": project.erpnext_project,
				"billing_rate": project.billing_rate,
				"sync_after": getdate(project.sync_after)
				if project.sync_after
				else None,
			}

	def _init_user_costing(self):
		self.user_cost_map = {}

		for user in self.jira_settings.billing:
			self.user_cost_map[user.email] = user.costing_rate

	def sync_work_logs(self):
		self.pull_issues()
		self.pull_worklogs()
		self.process_worklogs()

	def pull_issues(self):
		for mapping in self.jira_settings.mappings:
			project_key = mapping.jira_project_key

			for issue in self.jira_client.get_issues_for_project(project_key):
				self.issues[issue.get("id")] = {
					"project_key": project_key,
					"issue_key": issue.get("key"),
					"summary": issue.get("fields", {}).get("summary"),
				}

	def pull_worklogs(self):
		for issue_id in self.issues.keys():
			for worklog in self.jira_client.get_timelogs_by_issue(issue_id).get(
				"worklogs"
			):
				started = get_datetime(get_datetime_str(worklog.get("started")))
				if not self.is_worklog_created_after_sync_date(issue_id, started):
					continue

				self.worklogs[worklog.get("id")] = {
					"jira_issue": issue_id,
					"jira_issue_url": f"{self.jira_settings.url}/browse/{self.issues[issue_id].get('issue_key')}",
					"account_id": worklog.get("author", {}).get("accountId"),
					"email": worklog.get("author", {}).get("emailAddress", None),
					"from_time": started,
					"time_spend_seconds": worklog.get("timeSpentSeconds"),
					"comment": parse_comments(worklog.get("comment")),
				}

	def is_worklog_created_after_sync_date(self, issue_id, worklog_start_date):
		project_key = self.issues.get(issue_id, {}).get("project_key")
		sync_after = self.project_map.get(project_key, {}).get("sync_after")

		if not sync_after or getdate(worklog_start_date) >= getdate(sync_after):
			return True

		return False

	def process_worklogs(self):
		for worklog_id, worklog in self.worklogs.items():
			if not worklog.get("email") in self.user_list:
				continue

			timesheet = self.get_timesheet(worklog_id, worklog)
			issue = self.issues[worklog.get("jira_issue")]
			billing_rate = self.project_map.get(issue.get("project_key"), {}).get(
				"billing_rate", 0
			)
			costing_rate = self.user_cost_map.get(worklog.get("email"), 0)
			billing_hours = worklog.get("time_spend_seconds", 0) / 3600
			description = f"{issue.get('summary')} ({issue.get('issue_key')})"

			if worklog.get("comment"):
				description += f":\n{worklog.get('comment')}"

			log = {
				"activity_type": self.jira_settings.activity_type,
				"from_time": worklog.get("from_time"),
				"hours": billing_hours,
				"project": timesheet.parent_project,
				"is_billable": True,
				"description": description,
				"billing_hours": billing_hours,
				"base_billing_rate": billing_rate,
				"billing_rate": billing_rate,
				"costing_rate": costing_rate,
				"base_costing_rate": costing_rate,
				"billing_amount": flt(billing_hours) * flt(billing_rate),
				"base_billing_amount": flt(billing_hours) * flt(billing_rate),
				"costing_amount": flt(billing_hours) * flt(costing_rate),
				"base_costing_amount": flt(billing_hours) * flt(costing_rate),
				"jira_issue": worklog.get("jira_issue"),
				"jira_issue_url": worklog.get("jira_issue_url"),
				"jira_worklog": worklog_id,
			}

			worklog_exists = timesheet.get(
				key="time_logs", filters={"jira_worklog": worklog_id}
			)

			if worklog_exists:
				worklog_exists[0].update(log)
			else:
				timesheet.append("time_logs", log)

			timesheet.save()

	def get_timesheet(self, worklog_id, worklog):
		erpnext_project = self.project_map[
			self.issues[worklog.get("jira_issue")].get("project_key")
		].get("erpnext_project")

		timesheet_detail = frappe.db.exists(
			"Timesheet Detail",
			{
				"jira_issue_url": worklog.get("jira_issue_url"),
				"jira_issue": worklog.get("jira_issue"),
				"jira_worklog": worklog_id,
				"docstatus": 0,
			},
		)

		timesheet = frappe.db.exists(
			"Timesheet",
			{
				"jira_user_account_id": worklog.get("account_id"),
				"start_date": worklog.get("from_time"),
				"parent_project": erpnext_project,
				"docstatus": 0,
			},
		)

		if timesheet_detail:
			return frappe.get_doc(
				"Timesheet",
				frappe.db.get_value("Timesheet Detail", timesheet_detail, "parent"),
			)
		elif timesheet:
			return frappe.get_doc("Timesheet", timesheet)
		else:
			return frappe.get_doc(
				{
					"doctype": "Timesheet",
					"jira_user_account_id": worklog.get("account_id"),
					"employee": frappe.db.get_value(
						"Employee", {"company_email": worklog.get("email")}
					),
					"parent_project": erpnext_project,
					"start_date": worklog.get("date"),
				}
			)


def parse_comments(comments, list_indent=None):
	"""
	The structure of the comment content is as per the Atlassian Document Format (ADF)
	https://developer.atlassian.com/cloud/jira/platform/apis/document/structure/

	To extract the text content, the function is run recursively to get the text
	extracted from the nested dictionary.

	The list structure for bulletList, orderedList is preserved by adding a hyphen
	to preserve the list structure.

	The structure has a nested dict structure
	https://developer.atlassian.com/cloud/jira/platform/apis/document/structure/#json-structure

	Parameters:
	comments (dict, list): This is either the dict of the comment or just the content of the comment structure
	list_indent (int): This is used to indent the content if the text is a part of bulletList, orderedList and to add hyphen before rendering the text

	Returns:
	description (string): Parsed text comment from ADF fromat.
	"""
	if not comments:
		return

	if not list_indent:
		list_indent = 0

	description = ""

	if isinstance(comments, dict):
		comments = comments.get("content", [])

	for content in comments:
		if content.get("text"):
			# if list starts, the list_index will be set to 1, but while rendering, we do not want the indent
			# to be visible, hence substracting 1 will give us the correct indent while displaying
			description += f"\n{(list_indent - 1) * '	' if list_indent else ''}{'- ' if list_indent else ''}{content.get('text')}"
		elif content.get("content"):
			if content.get("type") in ["bulletList", "orderedList"]:
				list_indent += 1

			description += parse_comments(content.get("content"), list_indent)
		else:
			description += "\n"

	return description
