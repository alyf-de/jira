from dateutil.parser import isoparse
from datetime import datetime

from .jira_author import JiraAuthor


class JiraWorklog:
	def __init__(
		self,
		id: str,
		author: JiraAuthor,
		from_time: datetime,
		time_spent_seconds: int,
		comment: str,
	):
		self.id = id
		self.author = author
		self.from_time = from_time
		self.time_spent_seconds = time_spent_seconds
		self.comment = comment

	@staticmethod
	def from_dict(data: dict):
		return JiraWorklog(
			id=data.get("id"),
			author=JiraAuthor.from_dict(data.get("author", {})),
			from_time=isoparse(data.get("started")),
			time_spent_seconds=data.get("timeSpentSeconds", 0),
			comment=parse_comments(data.get("comment")),
		)


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
