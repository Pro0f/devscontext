"""Context synthesis - combines and ranks context from multiple sources.

This module provides functions for synthesizing context from multiple
adapters into a coherent, ranked output suitable for LLM consumption.

In the future, this module will include LLM-based synthesis to intelligently
combine and summarize context from different sources.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from devscontext.models import ContextData


def synthesize_context(
    context_items: list[ContextData],
    max_items: int = 10,
) -> list[ContextData]:
    """Synthesize and rank context from multiple sources.

    Currently implements basic sorting by relevance score. Future versions
    will include:
        - Deduplication of similar content
        - LLM-based relevance scoring
        - Cross-source synthesis
        - Key information extraction

    Args:
        context_items: Raw context items from all adapters.
        max_items: Maximum number of items to return.

    Returns:
        Sorted and filtered context items.
    """
    # Sort by relevance score (highest first)
    sorted_items = sorted(
        context_items,
        key=lambda x: x.relevance_score,
        reverse=True,
    )

    return sorted_items[:max_items]


def format_context_for_llm(context_items: list[ContextData]) -> str:
    """Format context items into a string suitable for LLM consumption.

    Creates a markdown-formatted string with each context item as a section,
    separated by horizontal rules.

    Args:
        context_items: Context items to format.

    Returns:
        Formatted context string, or a message if no context found.
    """
    if not context_items:
        return "No context found for this task."

    sections: list[str] = []

    for item in context_items:
        section = f"""## {item.title}
**Source:** {item.source} ({item.source_type})

{item.content}
"""
        sections.append(section)

    return "\n---\n\n".join(sections)
