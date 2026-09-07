from __future__ import annotations

from swiggy.redaction import redact, redact_text


def test_redact_text_masks_sensitive_values_and_local_paths() -> None:
    text = (
        "Authorization: Bearer secret-token-value; "
        "email=sahil@example.com phone=+91-9876543210 "
        "coords=28.123456,77.654321 path=/Users/jane/private/file.har"
    )

    result = redact_text(text)

    assert "Authorization: Bearer [REDACTED]" in result
    assert "secret" not in result
    assert "sahil@example.com" not in result
    assert "+91-9876543210" not in result
    assert "28.123456" not in result
    assert "/Users/jane/private/file.har" not in result
    assert "[REDACTED]" in result


def test_redact_recurses_without_changing_safe_shape() -> None:
    value = {"safe": "value", "nested": ["Bearer secret-token-value"]}

    result = redact(value)

    assert result["safe"] == "value"
    assert result["nested"][0] == "Bearer [REDACTED]"


def test_redact_masks_isolated_sensitive_mapping_values() -> None:
    result = redact({"access_token": "actual-token", "x-device-id": "device-123"})

    assert result == {"access_token": "[REDACTED]", "x-device-id": "[REDACTED]"}


def test_redact_preserves_context_and_masks_spaced_paths() -> None:
    result = redact_text(
        "Authorization: Bearer actual-token /Users/jane doe/private file.har"
    )

    assert "Authorization: Bearer [REDACTED]" in result
    assert "actual-token" not in result
    assert "/Users/jane doe" not in result


def test_redact_masks_quoted_json_values_without_overmatching_context() -> None:
    result = redact_text(
        '{"password": "actual-secret"} Error at /Users/dev/file during runtime'
    )

    assert '"password": "[REDACTED]"' in result
    assert "actual-secret" not in result
    assert "during runtime" in result


def test_redact_handles_inner_quotes_and_query_delimiters() -> None:
    result = redact_text(
        'password="O\'Connor secret"?access_token=actual-secret&user=admin'
    )

    assert "actual-secret" not in result
    assert "user=admin" in result
