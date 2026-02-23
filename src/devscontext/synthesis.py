"""Context synthesis - combines and ranks context from multiple sources."""

from devscontext.adapters.base import ContextData


def synthesize_context(
    context_items: list[ContextData],
    max_items: int = 10,
) -> list[ContextData]:
    """Synthesize and rank context from multiple sources.

    Args:
        context_items: Raw context items from all adapters.
        max_items: Maximum number of items to return.

    Returns:
        Sorted and filtered context items.
    """
    # TODO: Implement intelligent synthesis
    # - Deduplicate similar content
    # - Rank by relevance
    # - Consider recency
    # - Extract key information

    # For now, just sort by relevance score and limit
    sorted_items = sorted(
        context_items,
        key=lambda x: x.relevance_score,
        reverse=True,
    )

    return sorted_items[:max_items]


def format_context_for_llm(context_items: list[ContextData]) -> str:
    """Format context items into a string suitable for LLM consumption.

    Args:
        context_items: Context items to format.

    Returns:
        Formatted context string.
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
