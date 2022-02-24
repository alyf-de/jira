from urllib.parse import urljoin

class JiraIssue:
	def __init__(self, id: str, key: str, project: str, summary: str, url: str):
		self.id = id
		self.key = key
		self.project = project
		self.summary = summary
		self.url = url

	@staticmethod
	def from_dict(data: dict):
		return JiraIssue(
			id=data.get("id"),
			project=data.get("project"),
			key=data.get("key"),
			summary=data.get("fields", {}).get("summary"),
			url=urljoin(data.get("self"), f"/browse/{data.get('key')}"),
		)
