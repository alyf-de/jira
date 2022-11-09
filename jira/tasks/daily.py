# Copyright (c) 2021, ALYF GmbH and contributors
# For license information, please see license.txt

from datetime import date

import frappe
from frappe.utils import now_datetime, flt, get_datetime_str, get_date_str

from erpnext.projects.doctype.timesheet.timesheet import Timesheet

from jira.jira_client import JiraClient
from jira.jira_issue import JiraIssue
from jira.jira_worklog import JiraWorklog


@frappe.whitelist()
def sync_work_logs_from_jira(jira_settings_name=None):
	filters = {"enabled": 1}

	if jira_settings_name:
		filters["name"] = jira_settings_name

	for name in frappe.get_all("Jira Settings", filters=filters, pluck="name"):
		jira_settings = frappe.get_doc("Jira Settings", name)
		jira_client = JiraClient(
			jira_settings.url,
			jira_settings.api_user,
			jira_settings.get_password("api_key"),
		)
		for project_map in jira_settings.mappings:
			sync_work_logs(
				jira_client=jira_client,
				activity_type=jira_settings.activity_type,
				user_cost_map=jira_settings.get_user_cost(),
				jira_project=project_map.jira_project_key,
				erpnext_project=project_map.erpnext_project,
				billing_rate=project_map.billing_rate,
				sync_after=project_map.sync_after,
			)

		jira_settings.last_synced_on = now_datetime()
		jira_settings.save()


def sync_work_logs(
	jira_client: JiraClient,
	activity_type: str,
	user_cost_map: "dict[str, float]",
	jira_project: str,
	erpnext_project: str,
	billing_rate: float,
	sync_after: date = None,
):
	for issue in jira_client.get_issues(jira_project):
		for worklog in jira_client.get_worklogs(issue.id):
			if sync_after and worklog.from_time.date() < sync_after:
				continue

			if worklog.author.email_address not in user_cost_map:
				continue

			timesheet = get_timesheet(issue.url, worklog, erpnext_project)
			if not timesheet:
				continue

			time_log = get_time_log(
				worklog=worklog,
				issue=issue,
				activity_type=activity_type,
				project=erpnext_project,
				billing_rate=billing_rate,
				costing_rate=user_cost_map.get(worklog.author.email_address, 0),
			)

			existing_timelog = timesheet.get(
				key="time_logs", filters={"jira_worklog": worklog.id}
			)

			if existing_timelog:
				time_log["is_billable"] = existing_timelog[0].get("is_billable", True)
				existing_timelog[0].update(time_log)
			else:
				timesheet.append("time_logs", time_log)

			try:
				timesheet.save()
			except frappe.exceptions.ValidationError:
				frappe.log_error(frappe.get_traceback())


def get_timesheet(
	issue_url: str, worklog: JiraWorklog, erpnext_project: str
) -> Timesheet:
	ts_detail_filters = {
		"jira_issue_url": issue_url,
		"jira_worklog": worklog.id,
	}

	ts_detail_filters.update({"docstatus": (">", 0)})
	if frappe.db.exists("Timesheet Detail", ts_detail_filters):
		# a timesheet for this worklog has already been submitted
		return None

	ts_detail_filters.update({"docstatus": 0})
	existing_draft_ts_detail = frappe.db.exists("Timesheet Detail", ts_detail_filters)
	if existing_draft_ts_detail:
		return frappe.get_doc(
			"Timesheet",
			frappe.db.get_value("Timesheet Detail", existing_draft_ts_detail, "parent"),
		)

	existing_draft_timesheet = frappe.db.exists(
		"Timesheet",
		{
			"jira_user_account_id": worklog.author.account_id,
			"start_date": worklog.from_time,
			"parent_project": erpnext_project,
			"docstatus": 0,
		},
	)
	if existing_draft_timesheet:
		return frappe.get_doc("Timesheet", existing_draft_timesheet)

	new_timesheet = frappe.get_doc(
		{
			"doctype": "Timesheet",
			"jira_user_account_id": worklog.author.account_id,
			"employee": frappe.db.get_value(
				"Employee", {"company_email": worklog.author.email_address}
			),
			"parent_project": erpnext_project,
			"customer": frappe.db.get_value("Project", erpnext_project, "customer"),
			"start_date": get_date_str(worklog.from_time),
		}
	)
	return new_timesheet


def get_time_log(
	worklog: JiraWorklog,
	issue: JiraIssue,
	activity_type: str,
	project: str,
	billing_rate: float,
	costing_rate: float,
):
	billing_hours = worklog.time_spent_seconds / 3600
	description = f"{issue.summary} ({issue.key})"

	if worklog.comment:
		description += f":\n{worklog.comment}"

	billing_amount = flt(billing_hours * billing_rate, precision=2)
	costing_amount = flt(billing_hours * costing_rate, precision=2)

	return {
		"activity_type": activity_type,
		"from_time": get_datetime_str(worklog.from_time),
		"hours": flt(billing_hours, precision=3),
		"project": project,
		"is_billable": True,
		"description": description,
		"billing_hours": billing_hours,
		"base_billing_rate": billing_rate,
		"billing_rate": billing_rate,
		"costing_rate": costing_rate,
		"base_costing_rate": costing_rate,
		"billing_amount": billing_amount,
		"base_billing_amount": billing_amount,
		"costing_amount": costing_amount,
		"base_costing_amount": costing_amount,
		"jira_issue": issue.id,
		"jira_issue_url": issue.url,
		"jira_worklog": worklog.id,
	}
