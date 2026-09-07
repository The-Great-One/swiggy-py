from pathlib import Path

import pytest

from scripts.sanitize_capture import sanitize_capture, write_sanitized_capture

PRIVATE_CAPTURE = {
    "log": {
        "entries": [
            {
                "request": {
                    "method": "GET",
                    "url": "https://api.example.invalid/v1/dineout?token=TEST_VALUE_123",
                    "headers": [
                        {"name": "Authorization", "value": "Bearer TEST_VALUE_123"},
                        {"name": "X-Device-Id", "value": "DEVICE_TEST_123"},
                    ],
                    "postData": {"text": "phone=9999999999&lat=28.6139&lng=77.2090"},
                },
                "response": {"content": {"text": "private response body"}},
            }
        ]
    }
}


def test_sanitize_capture_emits_only_redacted_route_structure() -> None:
    result = sanitize_capture(PRIVATE_CAPTURE)

    assert result == {
        "routes": [
            {
                "method": "GET",
                "host": "api.example.invalid",
                "path": "/v1/dineout",
                "in_scope": True,
                "evidence_state": "CAPTURED",
            }
        ]
    }
    serialized = repr(result)
    for private_value in (
        "TEST_VALUE_123",
        "DEVICE_TEST_123",
        "9999999999",
        "28.6139",
        "77.2090",
        "private response body",
    ):
        assert private_value not in serialized


def test_write_sanitized_capture_refuses_input_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "capture.json"
    source.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="different from input"):
        write_sanitized_capture(PRIVATE_CAPTURE, source, source)
