"""Background agents for DevsContext.

This package contains the background pre-processing agent that watches Jira
for tickets moving to "Ready for Development" and pre-builds rich context
before anyone picks them up.

Components:
    JiraWatcher: Polls Jira for tickets in target status
    PreprocessingPipeline: Builds rich context with multi-pass synthesis

Example:
    from devscontext.agents import JiraWatcher, PreprocessingPipeline
    from devscontext.storage import PrebuiltContextStorage

    storage = PrebuiltContextStorage(".devscontext/cache.db")
    await storage.initialize()

    pipeline = PreprocessingPipeline(config, storage)
    watcher = JiraWatcher(config, pipeline)

    # Run the polling loop
    await watcher.run()
"""

from devscontext.agents.preprocessor import PreprocessingPipeline
from devscontext.agents.watcher import JiraWatcher

__all__ = ["JiraWatcher", "PreprocessingPipeline"]
