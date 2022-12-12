Jira Integration for ERPNext

### Jira User

Used to map the email address of a Jira user to a costing rate.

Existing **Employees** are matched automatically during sync, based on their _Company Email_.

### Jira Settings

Used to Specify settings for a Jira cloud site.

Allows you to ...

- specify a _Site URL_, _API User_ and _API Key_,
- map Jira project keys to existing **Projects** in ERPNext, and specify a billing rate for each project,
- specify the **Jira Users** for whom **Timesheets** shall be created in ERPNext.

**Jira Settings** contains a button to start a sync run immediately. Otherwise, sync runs every night.
