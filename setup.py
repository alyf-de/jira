from setuptools import setup, find_packages

with open("requirements.txt") as f:
	install_requires = f.read().strip().split("\n")

# get version from __version__ variable in jira/__init__.py
from jira import __version__ as version

setup(
	name="jira",
	version=version,
	description="Jira Integration for ERPNext",
	author="Alyf GmbH",
	author_email="hallo@alyf.de",
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
	install_requires=install_requires
)
