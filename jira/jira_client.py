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
		self.headers = {
			"Accept": "application/json"
		}


	def get_issues_for_project(self, project):
		url = f"{self.url}/rest/api/3/search"
		params = {
			"jql": f"project = {project}"
		}

		response = requests.request("GET", url, headers=self.headers, params=params, auth=self.auth)

		print(response.status_code, type(response.status_code), not response.status_code == 200)
		if not response.status_code == 200:
			self.handle_error(response)

		return response.json() if response else {}

	def get_issue(self, issue_id):
		url = f"{self.url}/rest/api/3/issue/{issue_id}"
		response = requests.request("GET", url, headers=self.headers, auth=self.auth)
		if not response.status_code == 200:
			self.handle_error(response)

		return response.json() if response else {}


	def get_issues_by_assignee(self, assignee):
		url = f"{self.url}/rest/api/3/search"
		assignee = assignee.replace("@", "\\u0040")
		params = {
			"jql": f"assignee = {assignee}"
		}

		response = requests.request("GET", url, headers=self.headers, params=params, auth=self.auth)
		if not response.status_code == 200:
			self.handle_error(response)

		return response.json() if response else {}


	def get_timelogs_by_issue(self, issue_id, started_after=None):
		url = f"{self.url}/rest/api/3/issue/{issue_id}/worklog"
		params = {}
		if started_after:
			params = {
				"startedAfter": started_after
			}

		response = requests.request("GET", url, headers=self.headers, params=params, auth=self.auth)
		if not response.status_code == 200:
			self.handle_error(response)

		return response.json() if response else {}


	def handle_error(self, response):
		response_dump = json.dumps(json.loads(response.text), sort_keys=True, indent=4, separators=(",", ": "))

		print(response_dump)
		if response.status_code == 400:
			frappe.log_error(message=f"Jira Settings Error: Returned if the JQL query is invalid. \n {response_dump}")
		elif response.status_code == 401:
			frappe.log_error(message=f"Jira Settings Error: Authentication credentials are invalid. \n {response_dump}")
		else:
			frappe.log_error(message=f"Jira Settings Error: Something went wrong with the request. \n {response_dump}")