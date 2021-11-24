# Copyright (c) 2021, Alyf GmbH and contributors
# For license information, please see license.txt

import requests
import frappe
import json
from requests.auth import HTTPBasicAuth


class JiraClient:
	def __init__(self, url, user, api_key) -> None:
		self.url = url
		self.auth = HTTPBasicAuth(user, api_key)
		self.headers = {"Accept": "application/json"}

	def get_issues_for_project(self, project):
		url = f"{self.url}/rest/api/3/search"
		results = []
		params = {
			"jql": f"project = {project}",
			"fields": "summary,description",
			"startAt": 0,
			"maxResults": 100,
		}

		while True:
			response = requests.request(
				"GET", url, headers=self.headers, params=params, auth=self.auth
			)

			if not response.status_code == 200:
				self.handle_error(response)
				break

			response = response.json()
			params["startAt"] += params["maxResults"]
			results.extend(response.get("issues"))

			if response.get("total") < params["startAt"]:
				break

		return results

	def get_timelogs_by_issue(self, issue_id, started_after=None):
		url = f"{self.url}/rest/api/3/issue/{issue_id}/worklog"
		params = {}
		if started_after:
			params = {"startedAfter": started_after}

		response = requests.request(
			"GET", url, headers=self.headers, params=params, auth=self.auth
		)
		if not response.status_code == 200:
			self.handle_error(response)

		return response.json() if response else {}

	def handle_error(self, response):
		response_dump = json.dumps(
			json.loads(response.text or "{}"),
			sort_keys=True,
			indent=4,
			separators=(",", ": "),
		)

		if response.status_code == 400:
			frappe.log_error(
				message=f"Jira Settings Error: Returned if the JQL query is invalid. \n {response_dump}"
			)
		elif response.status_code == 401:
			frappe.log_error(
				message=f"Jira Settings Error: Authentication credentials are invalid. \n {response_dump}"
			)
		else:
			frappe.log_error(
				message=f"Jira Settings Error: Something went wrong with the request. \n {response_dump}"
			)
