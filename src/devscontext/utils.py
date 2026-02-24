"""Utility functions for text processing and formatting."""

import re

# Common English stop words
STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "been",
    "be", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "must", "shall", "can", "need",
    "it", "its", "this", "that", "these", "those", "i", "you", "he",
    "she", "we", "they", "what", "which", "who", "when", "where", "why",
    "how", "all", "each", "every", "both", "few", "more", "most", "other",
    "some", "such", "no", "nor", "not", "only", "own", "same", "so",
    "than", "too", "very", "just", "also", "now", "here", "there", "then",
    "if", "else", "because", "about", "into", "through", "during", "before",
    "after", "above", "below", "between", "under", "again", "further",
    "once", "any", "out", "up", "down", "off", "over", "our", "your",
})

# Common ticket action verbs to filter out
ACTION_VERBS = frozenset({
    "add", "fix", "update", "implement", "create", "remove", "delete",
    "change", "modify", "refactor", "improve", "enhance", "optimize",
    "handle", "support", "enable", "disable", "configure", "setup",
    "make", "get", "set", "use", "move", "rename", "replace", "resolve",
    "ensure", "allow", "prevent", "check", "verify", "validate", "test",
    "debug", "investigate", "review", "clean", "cleanup", "simplify",
})


def extract_keywords(text: str) -> list[str]:
    """
    Extract meaningful keywords from text for document matching.

    Removes stop words, common action verbs, short words (<3 chars),
    and deduplicates. Returns top 10 keywords, longest first.

    Args:
        text: Input text (typically ticket title + description).

    Returns:
        List of up to 10 keywords, ordered by length (most specific first).

    Example:
        >>> extract_keywords("Add retry logic to payment webhook handler")
        ['webhook', 'payment', 'handler', 'retry', 'logic']
    """
    if not text:
        return []

    # Convert to lowercase and extract words (alphanumeric only)
    words = re.findall(r"[a-z0-9]+", text.lower())

    # Filter out stop words, action verbs, and short words
    keywords = []
    seen = set()
    for word in words:
        if (
            len(word) >= 3
            and word not in STOP_WORDS
            and word not in ACTION_VERBS
            and word not in seen
        ):
            keywords.append(word)
            seen.add(word)

    # Sort by length (longest/most specific first), then alphabetically for stability
    keywords.sort(key=lambda w: (-len(w), w))

    # Return top 10
    return keywords[:10]


def truncate_text(text: str, max_chars: int) -> str:
    """
    Truncate text to max_chars, breaking at sentence boundary if possible.

    Appends "... [truncated]" if text was cut.

    Args:
        text: Input text to truncate.
        max_chars: Maximum character limit.

    Returns:
        Truncated text with suffix if cut, or original if within limit.
    """
    if not text or len(text) <= max_chars:
        return text

    suffix = "... [truncated]"
    suffix_len = len(suffix)

    # Need at least some content before suffix
    if max_chars <= suffix_len:
        return text[:max_chars]

    available = max_chars - suffix_len

    # Try to find sentence boundary (. ! ?) within the available space
    # Look for the last sentence end before the cutoff
    truncated = text[:available]

    # Find last sentence-ending punctuation followed by space or end
    sentence_end = -1
    for i in range(len(truncated) - 1, -1, -1):
        if truncated[i] in ".!?":
            # Check if it's likely a sentence end (followed by space, end, or quote)
            if i == len(truncated) - 1 or truncated[i + 1] in " \n\t\"'":
                sentence_end = i + 1
                break

    # Use sentence boundary if it captures at least 50% of available space
    if sentence_end > available * 0.5:
        return truncated[:sentence_end].rstrip() + suffix

    # Otherwise, try to break at word boundary
    last_space = truncated.rfind(" ")
    if last_space > available * 0.5:
        return truncated[:last_space].rstrip() + suffix

    # Fall back to hard cut
    return truncated + suffix


def format_duration(ms: int) -> str:
    """
    Format milliseconds to human-readable duration.

    Args:
        ms: Duration in milliseconds.

    Returns:
        Formatted string: "150ms", "2.5s", "1m 5s", etc.

    Examples:
        >>> format_duration(150)
        '150ms'
        >>> format_duration(2500)
        '2.5s'
        >>> format_duration(65000)
        '1m 5s'
    """
    if ms < 0:
        return "0ms"

    if ms < 1000:
        return f"{ms}ms"

    seconds = ms / 1000

    if seconds < 60:
        # Format as seconds, remove trailing zeros
        if seconds == int(seconds):
            return f"{int(seconds)}s"
        formatted = f"{seconds:.1f}".rstrip("0").rstrip(".")
        return f"{formatted}s"

    minutes = int(seconds // 60)
    remaining_seconds = int(seconds % 60)

    if remaining_seconds == 0:
        return f"{minutes}m"

    return f"{minutes}m {remaining_seconds}s"
