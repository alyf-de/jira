# Copyright (c) 2021, Alyf GmbH and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import now_datetime, get_datetime_str, flt, get_date_str
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
		self.worklogs_processed = {}
		self._init_project_map()
		self._init_user_costing()

	def _init_project_map(self):
		self.project_map = {}

		for project in self.jira_settings.mappings:
			self.project_map[project.jira_project_key] = {
				"erpnext_project": project.erpnext_project,
				"billing_rate": project.billing_rate,
			}

	def _init_user_costing(self):
		self.user_cost_map = {}

		for user in self.jira_settings.billing:
			self.user_cost_map[user.email] = user.costing_rate

	def sync_work_logs(self):
		self.pull_issues()
		self.pull_worklogs()
		self.process_worklogs()
		self.create_or_update_timesheets()

	def pull_issues(self):
		self.issues = {}

		for mapping in self.jira_settings.mappings:
			key = mapping.jira_project_key
			self.issues[key] = self.jira_client.get_issues_for_project(key)

	def pull_worklogs(self):
		self.worklogs = {}
		# TODO
		# Enable startAfter for syncing the JIRA issues
		# started_after = None
		#
		# if self.jira_settings.sync_last and self.jira_settings.last_synced_on:
		#	started_after = add_days(self.jira_settings.last_synced_on, -1 * self.jira_settings.sync_last)

		for project_key, issues in self.issues.items():
			for issue in issues.get("issues", []):
				issue_id = issue.get("id")
				key = f"{project_key}::{issue_id}"
				self.worklogs[key] = self.jira_client.get_timelogs_by_issue(
					issue_id=issue_id
				)

	def process_worklogs(self):
		self.worklogs_processed = {}

		for key, worklogs in self.worklogs.items():
			for worklog in worklogs.get("worklogs", []):
				email = worklog.get("author", {}).get("emailAddress", None)

				if email in self.user_list:
					self._process_worklog(worklog, key)

	def _process_worklog(self, worklog, key):
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

		self._append_worklog(date, key, worklog)

	def _append_worklog(self, date, key, worklog):
		if not self.worklogs_processed.get(date):
			self.worklogs_processed[date] = {}

		if not self.worklogs_processed.get(date).get(key, None):
			self.worklogs_processed[date][key] = []

		self.worklogs_processed[date][key].append(worklog)

	def create_or_update_timesheets(self):
		for date in self.worklogs_processed:
			for worklog in self.worklogs_processed[date]:
				self._create_or_update_timesheet(date, worklog)

	def _create_or_update_timesheet(self, date, worklog):
		"""
		Handles multiple scenarios
		- If timesheet log exists for a worklog, the timesheet log is updated if the timesheet is not submitted
		- If new worklog is fetched, and if timesheet is submitted, it creates a new timesheet for the same date
		- If new worklog is fetched, and if timesheet is not submitted, it'll append it to timesheet logs
		- If timesheet is submitted, doesnt update the timesheet log
		"""
		project, user, jira_user_account_id = worklog.split("::")
		employee = frappe.db.get_value("Employee", {"user_id": user})
		erpnext_project = self.project_map.get(project, {}).get(
			"erpnext_project", project
		)
		billing_rate = self.project_map.get(project, {}).get("billing_rate", 0)
		costing_rate = self.user_cost_map.get(user, 0)

		timesheet = _get_timesheet(jira_user_account_id, date, erpnext_project)
		timesheet.employee = employee
		timesheet.parent_project = erpnext_project
		timesheet.jira_user_account_id = jira_user_account_id
		timesheet.start_date = date

		for log in self.worklogs_processed[date][worklog]:
			self._append_or_update_time_log(timesheet, log, billing_rate, costing_rate)

		if timesheet.get("time_logs"):
			timesheet.flags.ignore_mandatory = True
			timesheet.flags.ignore_links = True
			timesheet.flags.ignore_permissions = True
			timesheet.save()

	def _append_or_update_time_log(self, timesheet, log, billing_rate, costing_rate):
		"""
		Updates the existing timesheet log if already present in Timesheet, if not, adds a new
		log in Timesheet.
		"""
		base_billing_rate = flt(billing_rate) * timesheet.exchange_rate
		base_costing_rate = flt(costing_rate) * timesheet.exchange_rate
		billing_hours = log.get("timeSpentSeconds", 0) / 3600
		description = f"{log.get('issueDescription')} ({log.get('_issueKey')})"
		comments = parse_comments(log.get("comment"))

		if comments:
			description += f":\n{comments}"

		_log = {
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
		}

		# Check if a worklog exists in the current timesheet document and updates it
		_worklog_exists = timesheet.get(
			key="time_logs", filters={"jira_worklog": log.get("id")}
		)
		if _worklog_exists:
			_worklog_exists[0].update(_log)
			return

		# Check if a worklog exists in all the timesheets and if not, inserts it.
		_worklog_exists = frappe.db.exists(
			{"doctype": "Timesheet Detail", "jira_worklog": log.get("id")}
		)
		if not _worklog_exists:
			timesheet.append("time_logs", _log)


def _get_timesheet(jira_user_account_id, date, erpnext_project):
	"""
	Checks for the timesheet based off the employee and date and the docstatus
	If timesheet exists and it is still in draft state, it'll return the timesheet else will return a new timesheet doc
	"""
	_timesheet = frappe.db.exists(
		{
			"doctype": "Timesheet",
			"jira_user_account_id": jira_user_account_id,
			"start_date": date,
			"parent_project": erpnext_project,
			"docstatus": 0,
		}
	)

	if _timesheet:
		return frappe.get_doc("Timesheet", _timesheet[0][0])

	return frappe.new_doc("Timesheet")


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
