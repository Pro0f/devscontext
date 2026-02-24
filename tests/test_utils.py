"""Tests for utility functions."""

from devscontext.utils import extract_keywords, format_duration, truncate_text


class TestExtractKeywords:
    """Tests for extract_keywords function."""

    def test_basic_extraction(self):
        """Extract keywords from typical ticket title."""
        result = extract_keywords("Add retry logic to payment webhook handler")
        # Sorted by length (desc), then alphabetically
        assert result == ["handler", "payment", "webhook", "logic", "retry"]

    def test_filters_stop_words(self):
        """Stop words should be removed."""
        result = extract_keywords("the user is not able to see the dashboard")
        assert "the" not in result
        assert "is" not in result
        assert "not" not in result
        assert "to" not in result
        assert "user" in result
        assert "dashboard" in result

    def test_filters_action_verbs(self):
        """Common action verbs should be removed."""
        result = extract_keywords("implement add fix update refactor database connection")
        assert "implement" not in result
        assert "add" not in result
        assert "fix" not in result
        assert "update" not in result
        assert "refactor" not in result
        assert "database" in result
        assert "connection" in result

    def test_filters_short_words(self):
        """Words shorter than 3 chars should be removed."""
        result = extract_keywords("API v2 is up and running on VM")
        assert "v2" not in result
        assert "up" not in result
        assert "on" not in result
        assert "api" in result
        assert "running" in result

    def test_deduplication(self):
        """Duplicate words should be removed."""
        result = extract_keywords("error error error handling error recovery")
        assert result.count("error") == 1
        assert "handling" in result
        assert "recovery" in result

    def test_returns_longest_first(self):
        """Keywords should be sorted by length, longest first."""
        result = extract_keywords("api authentication authorization middleware")
        assert result[0] == "authentication"
        assert result[1] == "authorization"
        assert result[2] == "middleware"
        assert result[3] == "api"

    def test_max_10_keywords(self):
        """Should return at most 10 keywords."""
        text = (
            "database connection pooling timeout retry backoff "
            "authentication authorization middleware logging "
            "monitoring metrics tracing observability"
        )
        result = extract_keywords(text)
        assert len(result) <= 10

    def test_empty_input(self):
        """Empty string should return empty list."""
        assert extract_keywords("") == []

    def test_none_like_input(self):
        """None-like input should return empty list."""
        assert extract_keywords("") == []

    def test_only_stop_words(self):
        """Text with only stop words should return empty list."""
        result = extract_keywords("the and or but in on at to for of")
        assert result == []

    def test_case_insensitive(self):
        """Extraction should be case insensitive."""
        result = extract_keywords("API Authentication WEBHOOK Handler")
        assert "api" in result
        assert "authentication" in result
        assert "webhook" in result
        assert "handler" in result

    def test_handles_punctuation(self):
        """Should handle punctuation properly."""
        result = extract_keywords("Fix: user's payment-webhook isn't working!")
        assert "user" in result
        assert "payment" in result
        assert "webhook" in result
        assert "working" in result

    def test_preserves_numbers_in_words(self):
        """Should preserve numbers within words."""
        result = extract_keywords("Update oauth2 authentication for v3 api")
        assert "oauth2" in result
        assert "authentication" in result
        assert "api" in result


class TestTruncateText:
    """Tests for truncate_text function."""

    def test_no_truncation_needed(self):
        """Text within limit should be returned unchanged."""
        text = "Short text."
        result = truncate_text(text, 100)
        assert result == text

    def test_exact_limit(self):
        """Text exactly at limit should be returned unchanged."""
        text = "Exact."
        result = truncate_text(text, 6)
        assert result == text

    def test_truncates_at_sentence_boundary(self):
        """Should prefer truncating at sentence boundary."""
        text = "First sentence. Second sentence. Third sentence."
        result = truncate_text(text, 40)
        assert result.endswith("... [truncated]")
        assert "First sentence." in result

    def test_truncates_at_word_boundary(self):
        """Should break at word boundary if no sentence boundary."""
        text = "This is a long sentence without any periods until the very end"
        result = truncate_text(text, 30)
        assert result.endswith("... [truncated]")
        assert not result[: -len("... [truncated]")].endswith(" ")  # No trailing space

    def test_hard_cut_for_long_words(self):
        """Falls back to hard cut if no good boundary."""
        text = "Supercalifragilisticexpialidocious"
        result = truncate_text(text, 25)
        assert len(result) <= 25

    def test_empty_input(self):
        """Empty string should return empty string."""
        assert truncate_text("", 100) == ""

    def test_very_small_limit(self):
        """Very small limit should still work."""
        text = "Hello world"
        result = truncate_text(text, 5)
        assert len(result) <= 5

    def test_sentence_with_exclamation(self):
        """Should recognize ! as sentence boundary."""
        text = "Alert! This is important. More text here."
        result = truncate_text(text, 35)
        assert "Alert!" in result

    def test_sentence_with_question(self):
        """Should recognize ? as sentence boundary."""
        text = "What happened? Let me explain. More details follow."
        result = truncate_text(text, 40)
        assert "?" in result or "." in result

    def test_preserves_content_before_suffix(self):
        """Truncated text should have meaningful content."""
        text = "This is the first sentence. This is the second sentence."
        result = truncate_text(text, 50)
        # Should have first sentence plus suffix
        assert "first sentence" in result
        assert result.endswith("... [truncated]")


class TestFormatDuration:
    """Tests for format_duration function."""

    def test_milliseconds(self):
        """Sub-second durations shown as milliseconds."""
        assert format_duration(0) == "0ms"
        assert format_duration(1) == "1ms"
        assert format_duration(150) == "150ms"
        assert format_duration(999) == "999ms"

    def test_exact_seconds(self):
        """Exact seconds without decimals."""
        assert format_duration(1000) == "1s"
        assert format_duration(5000) == "5s"
        assert format_duration(59000) == "59s"

    def test_fractional_seconds(self):
        """Fractional seconds with one decimal place."""
        assert format_duration(1500) == "1.5s"
        assert format_duration(2500) == "2.5s"
        assert format_duration(1100) == "1.1s"

    def test_removes_trailing_zero(self):
        """Should not show .0 for whole seconds."""
        assert format_duration(3000) == "3s"
        assert "." not in format_duration(10000)

    def test_minutes_only(self):
        """Exact minutes without seconds."""
        assert format_duration(60000) == "1m"
        assert format_duration(120000) == "2m"
        assert format_duration(300000) == "5m"

    def test_minutes_and_seconds(self):
        """Minutes with remaining seconds."""
        assert format_duration(65000) == "1m 5s"
        assert format_duration(90000) == "1m 30s"
        assert format_duration(125000) == "2m 5s"

    def test_large_values(self):
        """Large durations in minutes."""
        assert format_duration(600000) == "10m"
        assert format_duration(3600000) == "60m"

    def test_negative_values(self):
        """Negative values should return 0ms."""
        assert format_duration(-100) == "0ms"
        assert format_duration(-1) == "0ms"

    def test_edge_cases(self):
        """Edge cases around boundaries."""
        assert format_duration(999) == "999ms"
        assert format_duration(1000) == "1s"
        assert format_duration(59900) == "59.9s"  # 59.9s exactly
        assert format_duration(60000) == "1m"
