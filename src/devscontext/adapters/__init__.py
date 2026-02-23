"""Adapters for various context sources."""

from devscontext.adapters.base import Adapter, ContextData
from devscontext.adapters.fireflies import FirefliesAdapter
from devscontext.adapters.jira import JiraAdapter
from devscontext.adapters.local_docs import LocalDocsAdapter

__all__ = [
    "Adapter",
    "ContextData",
    "JiraAdapter",
    "FirefliesAdapter",
    "LocalDocsAdapter",
]
