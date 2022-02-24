class JiraAuthor:
	def __init__(self, account_id: str, email_address: str):
		self.account_id = account_id
		self.email_address = email_address

	@staticmethod
	def from_dict(data: dict):
		return JiraAuthor(
			account_id=data.get("accountId"),
			email_address=data.get("emailAddress"),
		)
