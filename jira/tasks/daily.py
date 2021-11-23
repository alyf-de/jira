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
		self.jira_id_map = {}
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
		self.pull_issues_and_worklogs()
		self.create_or_update_timesheets()

	def pull_issues_and_worklogs(self):
		"""
		Syncs Issues and worklogs and creates a dict

		self.issues = {
			project: {
				issueId: {
					user : {
						date: [
							worklog 1,
							worklog 2
						]
					}
				}
			}
		}
		"""

		for mapping in self.jira_settings.mappings:
			project = mapping.jira_project_key

			if not self.project_exists(project):
				self.create_project(project)

			self._sync_issues(project)

	def _sync_issues(self, project):
		for issue in self.jira_client.get_issues_for_project(project):
			if not self.issue_exists(project, issue.get("id")):
				self.create_issue(project, issue)

			self._sync_worklogs(project, issue)

	def _sync_worklogs(self, project, issue):
		for worklog in self.pull_worklogs(issue.get("id")):
			email = worklog.get("author", {}).get("emailAddress", None)
			worklog_date = get_date_str(worklog.get("started"))

			self._add_jira_id(email, worklog)
			self._check_if_user_log_exists(project, issue, email)
			self._check_if_worklog_date_exists(project, issue, email, worklog_date)
			self._add_worklog_to_date(worklog, issue, project, email, worklog_date)

	def _check_if_user_log_exists(self, project, issue, email):
		if not self.user_log_exists(project, issue.get("id"), email):
			self.create_user_log(project, issue.get("id"), email)

	def _check_if_worklog_date_exists(self, project, issue, email, worklog_date):
		if not self.worklog_date_exists(project, issue.get("id"), email, worklog_date):
			self.create_worklog_date(project, issue.get("id"), email, worklog_date)

	def _add_worklog_to_date(self, worklog, issue, project, email, worklog_date):
		worklog.update(
			{
				"_issueKey": issue.get("key"),
				"issueURL": f"{self.jira_settings.url}/browse/{issue.get('key')}",
				"issueDescription": issue.get("fields", {}).get("summary"),
			}
		)

		self.add_worklog(project, issue.get("id"), email, worklog_date, worklog)

	def _add_jira_id(self, email, worklog):
		self.jira_id_map.update(
			{email: worklog.get("author", {}).get("accountId", None)}
		)

	def project_exists(self, project):
		return self.issues.get(project)

	def create_project(self, project):
		self.issues.update({project: {}})

	def issue_exists(self, project, issue):
		return self.issues.get(project, {}).get(issue)

	def create_issue(self, project, issue):
		self.issues.get(project, {}).update(
			{
				issue.get("id"): {
					"id": issue.get("id"),
					"summary": issue.get("summary"),
					"worklogs": {},
				}
			}
		)

	def user_log_exists(self, project, issue, email):
		return (
			self.issues.get(project, {}).get(issue, {}).get("worklogs", {}).get(email)
		)

	def create_user_log(self, project, issue, email):
		self.issues.get(project, {}).get(issue, {}).get("worklogs", {}).update(
			{email: {}}
		)

	def worklog_date_exists(self, project, issue, email, date):
		return (
			self.issues.get(project, {})
			.get(issue, {})
			.get("worklogs", {})
			.get(email, {})
			.get(date, None)
		)

	def create_worklog_date(self, project, issue, email, date):
		self.issues.get(project, {}).get(issue, {}).get("worklogs", {}).get(
			email, {}
		).update({date: []})

	def add_worklog(self, project, issue, email, date, worklog):
		self.issues.get(project, {}).get(issue, {}).get("worklogs", {}).get(
			email, {}
		).get(date, []).append(worklog)

	def pull_worklogs(self, issue):
		worklogs = self.jira_client.get_timelogs_by_issue(issue_id=issue)
		return worklogs.get("worklogs")

	def create_or_update_timesheets(self):
		for project_name, projects in self.issues.items():
			for issues in projects.values():
				for user, worklogs in issues.get("worklogs").items():
					if not user in self.user_list:
						continue

					for date, logs in worklogs.items():
						self._create_or_update_timesheet(project_name, user, date, logs)

	def _create_or_update_timesheet(self, project, user, date, logs):
		"""
		Handles multiple scenarios
		- If timesheet log exists for a worklog, the timesheet log is updated if the timesheet is not submitted
		- If new worklog is fetched, and if timesheet is submitted, it creates a new timesheet for the same date
		- If new worklog is fetched, and if timesheet is not submitted, it'll append it to timesheet logs
		- If timesheet is submitted, doesnt update the timesheet log
		"""
		jira_user_account_id = self.jira_id_map.get(user, None)
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

		for log in logs:
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
