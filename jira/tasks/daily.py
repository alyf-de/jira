# Copyright (c) 2021, Alyf GmbH and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import now_datetime, get_datetime_str, flt
from jira.jira_client import JiraClient


def pull_issues_from_jira():
	jira_settings = frappe.get_single("Jira Settings")
	if not jira_settings.enabled:
		return

	jira_client = JiraClient(jira_settings.url, jira_settings.api_user, jira_settings.get_password(fieldname="api_key"))
	logs = {}

	for mapping in jira_settings.mappings:
		issues = jira_client.get_issues_for_project(mapping.jira_project_key)

		for issue in issues.get("issues", []):
			worklogs = jira_client.get_timelogs_by_issue(issue.get("id"), started_after=jira_settings.last_synced_on)

			for worklog in worklogs.get("worklogs", []):
				email_address = worklog.get("author", {}).get("emailAddress", None)
				jira_user_account_id = worklog.get("author", {}).get("accountId", None)

				if not logs.get(f"{mapping.jira_project_key}::{email_address}::{jira_user_account_id}", None):
					logs[f"{mapping.jira_project_key}::{email_address}::{jira_user_account_id}"] = []

				logs[f"{mapping.jira_project_key}::{email_address}::{jira_user_account_id}"].append(worklog)

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
		user_cost_map[user.user] = user.costing_rate

	return user_cost_map


def create_timesheets(jira_settings, worklogs):
	project_map = get_project_map(jira_settings)
	user_cost_map = get_user_costing(jira_settings)

	for worklog in worklogs:
		project, user, jira_user_account_id = worklog.split("::")
		employee = frappe.db.get_value("Employee", {"user_id": user})

		timesheet = frappe.new_doc("Timesheet")
		timesheet.employee = employee
		timesheet.jira_user_account_id = jira_user_account_id

		for log in worklogs[worklog]:
			base_billing_rate = flt(project_map.get(project, {}).get("billing_rate", 0)) * timesheet.exchange_rate
			base_costing_rate = flt(user_cost_map.get(user, 0)) * timesheet.exchange_rate

			billing_rate = project_map.get(project, {}).get("billing_rate", 0)
			costing_rate = user_cost_map.get(user, 0)

			billing_hours = log.get("timeSpentSeconds", 0) / 3600

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
