"""Adapters for various context sources.

This package contains adapters for fetching context from different sources:
    - JiraAdapter: Jira tickets, comments, and linked issues
    - FirefliesAdapter: Meeting transcripts from Fireflies.ai
    - LocalDocsAdapter: Local markdown documentation

All adapters implement the Adapter interface from the plugins module.
"""

from devscontext.adapters.fireflies import FirefliesAdapter
from devscontext.adapters.jira import JiraAdapter
from devscontext.adapters.local_docs import LocalDocsAdapter
from devscontext.models import ContextData
from devscontext.plugins.base import Adapter

__all__ = [
    "Adapter",
    "ContextData",
    "FirefliesAdapter",
    "JiraAdapter",
    "LocalDocsAdapter",
]
