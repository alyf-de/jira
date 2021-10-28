# Copyright (c) 2021, Alyf GmbH and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import now_datetime, get_datetime_str, flt, get_date_str
from jira.jira_client import JiraClient


@frappe.whitelist()
def pull_issues_from_jira(project=None):
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
		self.init_project_map()
		self.init_user_costing()

	def init_project_map(self):
		self.project_map = {}

		for project in self.jira_settings.mappings:
			self.project_map[project.jira_project_key] = {
				"erpnext_project": project.erpnext_project,
				"billing_rate": project.billing_rate,
			}

	def init_user_costing(self):
		self.user_cost_map = {}

		for user in self.jira_settings.billing:
			self.user_cost_map[user.email] = user.costing_rate

	def sync_work_logs(self):
		self.pull_issues()
		self.pull_worklogs()
		self.process_worklogs()
		self.create_timesheets()

	def pull_issues(self):
		self.issues = {}

		for mapping in self.jira_settings.mappings:
			key = mapping.jira_project_key
			self.issues[key] = self.jira_client.get_issues_for_project(key)

	def pull_worklogs(self):
		self.worklogs = {}

		for project_key, issues in self.issues.items():
			for issue in issues.get("issues", []):
				issue_id = issue.get("id")
				key = f"{project_key}::{issue_id}"
				self.worklogs[key] = self.jira_client.get_timelogs_by_issue(
					issue_id, started_after=self.jira_settings.last_synced_on
				)

	def process_worklogs(self):
		self.worklogs_processed = {}

		for key, worklogs in self.worklogs.items():
			for worklog in worklogs.get("worklogs", []):
				email = worklog.get("author", {}).get("emailAddress", None)

				if email in self.user_list:
					self.process_worklog(worklog, key)

	def process_worklog(self, worklog, key):
		project_key, issue_id = key.split("::")
		issue = self.jira_client.get_issue(issue_id)
		date = get_date_str(worklog.get("started"))
		email = worklog.get("author", {}).get("emailAddress", None)
		jira_user_account_id = worklog.get("author", {}).get("accountId", None)
		key = f"{project_key}::{email}::{jira_user_account_id}"

		worklog.update(
			{
				"_issueKey": issue.get("key"),
				"issueURL": f"{self.jira_settings.url}/browse/{issue.get('key')}",
				"issueDescription": issue.get("fields", {}).get("summary"),
			}
		)

		self.append_worklog(date, key, worklog)

	def append_worklog(self, date, key, worklog):
		if not self.worklogs_processed.get(date):
			self.worklogs_processed[date] = {}

		if not self.worklogs_processed.get(date).get(key, None):
			self.worklogs_processed[date][key] = []

		self.worklogs_processed[date][key].append(worklog)

	def create_timesheets(self):
		for date in self.worklogs_processed:
			for worklog in self.worklogs_processed[date]:
				self.create_timesheet(date, worklog)

	def create_timesheet(self, date, worklog):
		project, user, jira_user_account_id = worklog.split("::")
		employee = frappe.db.get_value("Employee", {"user_id": user})
		erpnext_project = self.project_map.get(project, {}).get(
			"erpnext_project", project
		)
		billing_rate = self.project_map.get(project, {}).get("billing_rate", 0)
		costing_rate = self.user_cost_map.get(user, 0)

		timesheet = frappe.new_doc("Timesheet")
		timesheet.employee = employee
		timesheet.parent_project = erpnext_project
		timesheet.jira_user_account_id = jira_user_account_id

		for log in self.worklogs_processed[date][worklog]:
			self.append_time_log(timesheet, log, billing_rate, costing_rate)

		timesheet.insert(
			ignore_mandatory=True, ignore_links=True, ignore_permissions=True
		)

	def append_time_log(self, timesheet, log, billing_rate, costing_rate):
		base_billing_rate = flt(billing_rate) * timesheet.exchange_rate
		base_costing_rate = flt(costing_rate) * timesheet.exchange_rate
		billing_hours = log.get("timeSpentSeconds", 0) / 3600
		description = parse_description(log)

		timesheet.append(
			"time_logs",
			{
				"activity_type": self.jira_settings.activity_type,
				"from_time": get_datetime_str(log.get("started")),
				"hours": billing_hours,
				"project": timesheet.parent_project,
				"is_billable": True,
				"description": description,
				"billing_hours": billing_hours,
				"base_billing_rate": base_billing_rate,
				"billing_rate": billing_rate,
				"base_costing_rate": base_costing_rate,
				"costing_rate": costing_rate,
				"base_billing_amount": flt(billing_hours) * flt(base_billing_rate),
				"billing_amount": flt(billing_hours) * flt(billing_rate),
				"costing_amount": flt(costing_rate) * flt(billing_hours),
				"jira_issue": log.get("issueId"),
				"jira_issue_url": log.get("issueURL"),
				"jira_worklog": log.get("id"),
			},
		)


def parse_description(log):
	description = f"{log.get('issueDescription')} ({log.get('_issueKey')})"
	line_break = ":\n"

	for comment in log.get("comment", {}).get("content", []):
		if line_break not in description:
			description += line_break

		for comm in comment.get("content", []):
			description += comm.get("text", "") + " "

	return description
