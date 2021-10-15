# Copyright (c) 2021, Alyf GmbH and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import now_datetime, get_datetime_str, flt, get_date_str
from jira.jira_client import JiraClient

@frappe.whitelist()
def pull_issues_from_jira(project=None):
	"""
		Creates a dictionary with date as key and corresponding logs
		{
			"date": {
				"project_key + email_address + account_id": [worklogs]
			}
		}
	"""
	filters = {"enabled": 1}
	if project:
		filters.update({"name": project})

	for jira in frappe.get_all("Jira Settings", filters=filters):
		jira_settings = frappe.get_doc("Jira Settings", jira.name)
		user_list = [user.email for user in jira_settings.billing]
		jira_client = JiraClient(jira_settings.url, jira_settings.api_user, jira_settings.get_password(fieldname="api_key"))
		logs = {}

		for mapping in jira_settings.mappings:
			issues = jira_client.get_issues_for_project(mapping.jira_project_key)

			for issue in issues.get("issues", []):
				_issue = jira_client.get_issue(issue.get("id"))
				worklogs = jira_client.get_timelogs_by_issue(issue.get("id"), started_after=jira_settings.last_synced_on)

				for worklog in worklogs.get("worklogs", []):
					date = get_date_str(worklog.get("started"))
					email_address = worklog.get("author", {}).get("emailAddress", None)
					if not email_address in user_list:
						continue

					jira_user_account_id = worklog.get("author", {}).get("accountId", None)
					worklog.update({
						"_issueKey": _issue.get('key'),
						"issueURL": f"{jira_settings.url}/browse/{_issue.get('key')}",
						"issueDescription": _issue.get("fields", {}).get("summary")
					})

					if not logs.get(date):
						logs[date] = {}

					if not logs.get(date).get(f"{mapping.jira_project_key}::{email_address}::{jira_user_account_id}", None):
						logs[date][f"{mapping.jira_project_key}::{email_address}::{jira_user_account_id}"] = []

					logs[date][f"{mapping.jira_project_key}::{email_address}::{jira_user_account_id}"].append(worklog)

		create_timesheets(jira_settings, logs)
		jira_settings.last_synced_on = now_datetime()
		jira_settings.save()


def get_project_map(jira_settings):
	project_map = {}

	for project in jira_settings.mappings:
		project_map[project.jira_project_key] = {
			"erpnext_project": project.erpnext_project,
			"billing_rate": project.billing_rate
		}

	return project_map


def get_user_costing(jira_settings):
	user_cost_map = {}

	for user in jira_settings.billing:
		user_cost_map[user.email] = user.costing_rate

	return user_cost_map


def create_timesheets(jira_settings, worklogs):
	project_map = get_project_map(jira_settings)
	user_cost_map = get_user_costing(jira_settings)

	for worklog_date in worklogs:
		for worklog in worklogs[worklog_date]:

			project, user, jira_user_account_id = worklog.split("::")
			employee = frappe.db.get_value("Employee", {"user_id": user})

			timesheet = frappe.new_doc("Timesheet")
			timesheet.employee = employee
			timesheet.jira_user_account_id = jira_user_account_id

			for log in worklogs[worklog_date][worklog]:
				base_billing_rate = flt(project_map.get(project, {}).get("billing_rate", 0)) * timesheet.exchange_rate
				base_costing_rate = flt(user_cost_map.get(user, 0)) * timesheet.exchange_rate

				billing_rate = project_map.get(project, {}).get("billing_rate", 0)
				costing_rate = user_cost_map.get(user, 0)

				billing_hours = log.get("timeSpentSeconds", 0) / 3600

				description = f"{log.get('_issueKey')}: {log.get('issueDescription')}\n"
				for comment in log.get("comment", {}).get("content", []):
					for comm in comment.get("content", []):
						description += comm.get("text", "") + " "

				timesheet.append("time_logs", {
					"from_time": get_datetime_str(log.get("started")),
					"hours": billing_hours,
					"project": project_map.get(project, {}).get("erpnext_project", project),
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
					"jira_worklog": log.get("id")
				})

			timesheet.insert(ignore_mandatory=True, ignore_links=True, ignore_permissions=True)
