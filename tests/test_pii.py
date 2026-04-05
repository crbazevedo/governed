"""Tests for PII redaction utilities."""

from __future__ import annotations

from governed_agents.pii import PII_FIELDS, redact_payload


class TestRedactPayload:
    def test_email_redacted(self):
        payload = {"message": "Contact user@example.com for info"}
        result = redact_payload(payload)
        assert "user@example.com" not in result["message"]
        assert "[EMAIL]" in result["message"]

    def test_phone_redacted(self):
        payload = {"message": "Call 555-123-4567 now"}
        result = redact_payload(payload)
        assert "555-123-4567" not in result["message"]
        assert "[PHONE]" in result["message"]

    def test_known_pii_field_redacted(self):
        payload = {"email": "user@example.com", "data": "safe"}
        result = redact_payload(payload)
        assert result["email"] == "[REDACTED]"
        assert result["data"] == "safe"

    def test_nested_dict_redacted(self):
        payload = {
            "contact": {
                "email": "user@example.com",
                "notes": "Reached via 555-123-4567",
            }
        }
        result = redact_payload(payload)
        assert result["contact"]["email"] == "[REDACTED]"
        assert "[PHONE]" in result["contact"]["notes"]

    def test_list_redacted(self):
        payload = {"emails": ["a@b.com", "c@d.com"]}
        result = redact_payload(payload)
        for item in result["emails"]:
            assert "@" not in item

    def test_original_not_mutated(self):
        original = {"email": "user@example.com"}
        redact_payload(original)
        assert original["email"] == "user@example.com"

    def test_non_string_scalars_pass_through(self):
        payload = {"count": 42, "active": True, "value": None}
        result = redact_payload(payload)
        assert result == {"count": 42, "active": True, "value": None}

    def test_known_pii_list_field(self):
        payload = {"stakeholders": ["Alice", "Bob"]}
        result = redact_payload(payload)
        assert result["stakeholders"] == ["[REDACTED]", "[REDACTED]"]

    def test_pii_fields_set(self):
        assert "email" in PII_FIELDS
        assert "phone" in PII_FIELDS
        assert "name" in PII_FIELDS
        assert "owner" in PII_FIELDS

    def test_international_phone(self):
        payload = {"msg": "Reach me at +1-555-123-4567 anytime"}
        result = redact_payload(payload)
        assert "+1-555-123-4567" not in result["msg"]
