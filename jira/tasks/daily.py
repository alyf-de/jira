# Copyright (c) 2021, Alyf GmbH and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import now_datetime, get_datetime_str
from jira.jira_client import JiraClient


def pull_issues_from_jira():
	jira_settings = frappe.get_single("Jira Settings")
	jira_client = JiraClient(jira_settings.url, jira_settings.api_user, jira_settings.api_key)
	logs = {}

	for user_details in jira_settings.billing:
		issues = jira_client.get_issues_by_assignee(user_details.user)

		for issue in issues.get("issues", []):
			issue = jira_client.get_issue(issue.get("id"))
			project = issue.get("fields", {}).get("project", {}).get("name")

			worklogs = jira_client.get_timelogs_by_issue(issue.get("id"))

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
		timesheet = {
			"doctype" :"Timesheet",
			"employee": employee,
			"time_logs": []
		}

		for log in worklogs[worklog]:
			timesheet.get("time_logs").append({
				"doctype": "Timesheet Detail",
				"from_time": get_datetime_str(log.get("started")),
				"hours": log.get("timeSpentSeconds", 0) / 3600,
				"project": project_map.get(project, {}).get("erpnext_project", None) or project,
				"is_billable": True,
				"billing_hours": log.get("timeSpentSeconds", 0) / 3600,
				"billing_rate": project_map.get(project, {}).get("billing_rate", None),
				"costing_rate": user_cost_map.get(user, None),
				"jira_issue": log.get("issueId"),
				"jira_worklog": log.get("id")
			})

		frappe.get_doc(timesheet).insert(ignore_mandatory=True, ignore_links=True, ignore_permissions=True)