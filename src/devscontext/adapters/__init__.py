"""Adapters for various context sources.

This package contains adapters for fetching context from different sources:
    - JiraAdapter: Jira tickets, comments, and linked issues
    - FirefliesAdapter: Meeting transcripts from Fireflies.ai
    - LocalDocsAdapter: Local markdown documentation

All adapters implement the Adapter base class interface.
"""

from devscontext.adapters.base import Adapter
from devscontext.adapters.fireflies import FirefliesAdapter
from devscontext.adapters.jira import JiraAdapter
from devscontext.adapters.local_docs import LocalDocsAdapter
from devscontext.models import ContextData

__all__ = [
    "Adapter",
    "ContextData",
    "FirefliesAdapter",
    "JiraAdapter",
    "LocalDocsAdapter",
]
