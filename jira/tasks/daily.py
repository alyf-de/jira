# Copyright (c) 2021, Alyf GmbH and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import now_datetime, get_datetime_str, flt
from jira.jira_client import JiraClient


def pull_issues_from_jira():
	jira_settings = frappe.get_single("Jira Settings")
	if not jira_settings.enabled:
		return

	jira_client = JiraClient(jira_settings.url, jira_settings.api_user, jira_settings.api_key)
	logs = {}

	for user_details in jira_settings.billing:
		issues = jira_client.get_issues_by_assignee(user_details.user)

		for issue in issues.get("issues", []):
			issue = jira_client.get_issue(issue.get("id"))
			project = issue.get("fields", {}).get("project", {}).get("name")

			worklogs = jira_client.get_timelogs_by_issue(issue.get("id"), started_after=jira_settings.last_synced_on)

			for worklog in worklogs.get("worklogs", []):
				if not logs.get(f"{project}::{user_details.user}", None):
					logs[f"{project}::{user_details.user}"] = []

				logs[f"{project}::{user_details.user}"].append(worklog)

	create_timesheets(jira_settings, logs)
	jira_settings.last_synced_on = now_datetime()
	jira_settings.save()


def get_project_map(jira_settings):
	project_map = {}

	for project in jira_settings.mappings:
		project_map[project.jira_project] = {
			"erpnext_project": project.erpnext_project,
			"billing_rate": project.billing_rate
		}

	return project_map


def get_user_costing(jira_settings):
	user_cost_map = {}

	for user in jira_settings.billing:
		user_cost_map[user.user] = user.costing_rate

	return user_cost_map


def create_timesheets(jira_settings, worklogs):
	project_map = get_project_map(jira_settings)
	user_cost_map = get_user_costing(jira_settings)

	for worklog in worklogs:
		details = worklog.split("::")
		project = details[0]
		user = details[1]

		employee = frappe.db.get_value("Employee", {"user_id": user}) or user
		timesheet = frappe.new_doc("Timesheet")
		timesheet.employee = employee

		for log in worklogs[worklog]:
			base_billing_rate =  flt(project_map.get(project, {}).get("billing_rate", 0)) * timesheet.exchange_rate
			base_costing_rate =  flt(user_cost_map.get(user, 0)) * timesheet.exchange_rate

			billing_rate =  project_map.get(project, {}).get("billing_rate", 0)
			costing_rate =  user_cost_map.get(user, 0)

			billing_hours  =  log.get("timeSpentSeconds", 0) / 3600

			timesheet.append("time_logs", {
				"from_time": get_datetime_str(log.get("started")),
				"hours": billing_hours,
				"project": project_map.get(project, {}).get("erpnext_project", project),
				"is_billable": True,
				"billing_hours": billing_hours,
				"base_billing_rate": base_billing_rate,
				"billing_rate": billing_rate,
				"base_costing_rate": base_costing_rate,
				"costing_rate": costing_rate,
				"base_billing_amount": flt(billing_hours) * flt(base_billing_rate),
				"billing_amount": flt(billing_hours) * flt(billing_rate),
				"costing_amount": flt(costing_rate) * flt(billing_hours),
				"jira_issue": log.get("issueId"),
				"jira_worklog": log.get("id")
			})

		timesheet.insert(ignore_mandatory=True, ignore_links=True, ignore_permissions=True)
