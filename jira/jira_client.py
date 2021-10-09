# Copyright (c) 2021, Alyf GmbH and contributors
# For license information, please see license.txt

import requests
from requests.auth import HTTPBasicAuth

class JiraClient:
	def __init__(self, url, user, api_key) -> None:
		self.url = url
		self.auth = HTTPBasicAuth(user, api_key)
		self.headers = {
			"Accept": "application/json"
		}


	def get_issue(self, issue_id):
		url = f"{self.url}/rest/api/3/issue/{issue_id}"
		response = requests.request("GET", url, headers=self.headers, auth=self.auth)
		return response.json() if response else {}


	def get_issues_by_assignee(self, assignee):
		url = f"{self.url}/rest/api/3/search"
		assignee = assignee.replace("@", "\\u0040")
		jql = {
			"jql": f"assignee = {assignee}"
		}

		response = requests.request("GET", url, headers=self.headers, params=jql, auth=self.auth)
		return response.json() if response else {}


	def get_timelogs_by_issue(self, issue_id, started_after=None):
		url = f"{self.url}/rest/api/3/issue/{issue_id}/worklog"
		params = {}
		if started_after:
			params = {
				"startedAfter": started_after
			}

		response = requests.request("GET", url, headers=self.headers, params=params, auth=self.auth)
		return response.json() if response else {}