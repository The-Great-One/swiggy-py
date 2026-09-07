"""Pure parsing of Swiggy Dineout offers into normalized models."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

from pydantic import ValidationError

from swiggy.errors import ProviderResponseError, SchemaDriftError
from swiggy.models import Offer
from swiggy.provenance import SourceEvidence

_PERCENT_KEYS = ("discount_percent", "discount_percentage", "percentage", "percent")
_MINIMUM_KEYS = (
    "minimum_bill",
    "minimum_order",
    "minimum_order_value",
    "min_bill",
    "min_order_value",
)
_STATUS_KEYS = ("is_active", "active", "enabled", "available", "is_usable", "usable")
_UNUSABLE_STATUSES = {
    "disabled",
    "expired",
    "excluded",
    "inactive",
    "invalid",
    "not applicable",
    "not_applicable",
    "unavailable",
}


def _schema_error(evidence: SourceEvidence, detail: str) -> SchemaDriftError:
    return SchemaDriftError(f"{evidence.endpoint_id} offers: {detail}")


def _as_mapping(
    value: object, evidence: SourceEvidence, detail: str
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _schema_error(evidence, detail)
    return value


def _text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:[,.]\d+)*", value.replace(",", ""))
        if match:
            return float(match.group(0))
    return None


def _numeric_field(
    mapping: Mapping[str, object],
    keys: Sequence[str],
    evidence: SourceEvidence,
    field_name: str,
) -> float | None:
    raw = _first(mapping, keys)
    if raw is None:
        return None
    parsed = _number(raw)
    if parsed is None:
        raise _schema_error(evidence, f"invalid {field_name}")
    return parsed


def _date_field(
    value: object | None, evidence: SourceEvidence, field_name: str
) -> date | None:
    if value is None:
        return None
    parsed = _date_value(value)
    if parsed is None:
        raise _schema_error(evidence, f"invalid {field_name}")
    return parsed


def _first(mapping: Mapping[str, object], keys: Sequence[str]) -> object | None:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _date_value(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text_value = _text(value)
    if text_value is None:
        return None
    text_value = re.sub(r"\bSept\b", "Sep", text_value, flags=re.IGNORECASE)
    normalized = text_value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        pass
    for format_string in ("%d/%m/%Y", "%d-%m-%Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(text_value, format_string).date()
        except ValueError:
            continue
    return None


def _date_from_text(value: str) -> date | None:
    match = re.search(
        r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|"
        r"September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|"
        r"Sep|Sept|Oct|Nov|Dec)\s+(\d{4})\b",
        value,
        re.IGNORECASE,
    )
    if match is None:
        return None
    return _date_value(" ".join(match.groups()))


def _texts(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        result: list[str] = []
        for item in value:
            result.extend(_texts(item))
        return tuple(result)
    return ()


def _add_unique(items: list[str], values: Sequence[str]) -> None:
    for value in values:
        cleaned = value.strip()
        if cleaned and cleaned not in items:
            items.append(cleaned)


def _discount_details(
    item: Mapping[str, object], evidence: SourceEvidence
) -> tuple[float | None, float | None, float | None]:
    """Return percentage, flat amount, and maximum discount amount."""

    percentage = _numeric_field(item, _PERCENT_KEYS, evidence, "discount_percent")
    flat_amount = _numeric_field(
        item,
        ("flat_discount", "flat_amount", "discount_amount"),
        evidence,
        "flat discount",
    )
    cap = _numeric_field(
        item,
        ("cap", "maximum_discount", "maximum_amount", "max_amount"),
        evidence,
        "maximum discount",
    )

    nested = item.get("discount")
    if isinstance(nested, Mapping):
        kind = (_text(_first(nested, ("type", "kind", "unit"))) or "").casefold()
        value = _numeric_field(
            nested, ("value", "amount", "discount"), evidence, "discount"
        )
        if "percent" in kind or "%" in kind:
            percentage = value
        elif "flat" in kind or "fixed" in kind or "cash" in kind or "amount" in kind:
            flat_amount = value
        elif value is not None and percentage is None and flat_amount is None:
            percentage = value
        cap = cap or _numeric_field(
            nested,
            ("cap", "maximum_discount", "maximum_amount", "max_amount"),
            evidence,
            "maximum discount",
        )
    elif nested is not None and percentage is None and flat_amount is None:
        percentage = _number(nested)
        if percentage is None:
            raise _schema_error(evidence, "invalid discount")

    return percentage, flat_amount, cap


def _validity(
    item: Mapping[str, object], raw_text: str | None, evidence: SourceEvidence
) -> tuple[date | None, date | None, str | None]:
    nested = item.get("validity")
    validity = nested if isinstance(nested, Mapping) else {}
    start_raw = _first(
        item,
        ("valid_from", "start_date", "starts_at", "from_date"),
    )
    end_raw = _first(
        item, ("valid_until", "valid_to", "end_date", "ends_at", "to_date")
    )
    start_raw = (
        start_raw
        if start_raw is not None
        else _first(validity, ("from", "start", "valid_from"))
    )
    end_raw = (
        end_raw
        if end_raw is not None
        else _first(validity, ("until", "to", "end", "valid_until"))
    )
    valid_from = _date_field(start_raw, evidence, "valid_from")
    valid_until = _date_field(end_raw, evidence, "valid_until")
    time_window = _text(
        _first(
            item,
            ("time_window", "applicable_time", "applicable_times", "valid_times"),
        )
    ) or _text(_first(validity, ("time_window", "time", "hours")))
    if raw_text is not None:
        remainder = raw_text
        from_match = re.search(r"from\s+([^,;]+?)\s+to\s+", raw_text, re.IGNORECASE)
        if from_match is not None:
            if valid_from is None:
                valid_from = _date_value(from_match.group(1).strip())
            remainder = raw_text[from_match.end() :]
        if valid_until is None:
            valid_until = _date_from_text(remainder)
    return valid_from, valid_until, time_window


def _has_structured_terms(item: Mapping[str, object]) -> bool:
    keys = set(item)
    return bool(
        keys
        & {
            "discount",
            *_PERCENT_KEYS,
            "flat_discount",
            "flat_amount",
            "discount_amount",
            *_MINIMUM_KEYS,
            "validity",
            "valid_from",
            "valid_until",
            "valid_to",
            "start_date",
            "end_date",
            "restrictions",
            "terms",
            "conditions",
            "payment",
            "payment_methods",
            "eligible_payment_methods",
            "excluded_payment_methods",
            "exclusions",
            "code",
            "cap",
            "maximum_discount",
            "maximum_amount",
        }
    )


def _is_unusable(
    item: Mapping[str, object], valid_until: date | None, today: date
) -> bool:
    for key in ("expired", "is_expired", "excluded"):
        if item.get(key) is True:
            return True
    for key in _STATUS_KEYS:
        value = item.get(key)
        if isinstance(value, bool) and not value:
            return True
    status = _text(item.get("status"))
    if status is not None and status.casefold().replace("-", "_") in _UNUSABLE_STATUSES:
        return True
    return valid_until is not None and valid_until < today


def _parse_offer(item: Mapping[str, object], evidence: SourceEvidence) -> Offer | None:
    percentage, flat_amount, cap = _discount_details(item, evidence)
    raw_text = _text(_first(item, ("text", "description", "offer_text")))
    structured = _has_structured_terms(item)
    if not structured and raw_text is not None:
        percent_match = re.search(r"(\d+(?:\.\d+)?)\s*%", raw_text)
        if percentage is None and percent_match is not None:
            percentage = _number(percent_match.group(1))
    valid_from, valid_until, time_window = _validity(
        item, raw_text if not structured else None, evidence
    )
    if _is_unusable(item, valid_until, evidence.retrieved_at.date()):
        return None

    title = _text(_first(item, ("title", "name", "label")))
    if title is None and not structured:
        title = raw_text
    if title is None and percentage is not None:
        title = f"{percentage:g}% off"
    if title is None and flat_amount is not None:
        title = f"₹{flat_amount:g} off"
    if title is None:
        raise _schema_error(evidence, "offer is missing a title or text")

    restrictions: list[str] = []
    _add_unique(
        restrictions, _texts(_first(item, ("restrictions", "terms", "conditions")))
    )
    _add_unique(restrictions, _texts(item.get("exclusions")))

    payment = item.get("payment")
    if isinstance(payment, Mapping):
        _add_unique(
            restrictions,
            _texts(_first(payment, ("methods", "eligible_methods", "payment_methods"))),
        )
        _add_unique(
            restrictions,
            _texts(
                _first(
                    payment,
                    ("excluded_methods", "exclusions", "excluded_payment_methods"),
                )
            ),
        )
        _add_unique(restrictions, _texts(payment.get("constraints")))
    _add_unique(
        restrictions,
        _texts(
            _first(
                item,
                ("payment_methods", "eligible_payment_methods", "eligible_methods"),
            )
        ),
    )
    _add_unique(
        restrictions,
        _texts(_first(item, ("excluded_payment_methods", "excluded_methods"))),
    )
    code = _text(item.get("code"))
    if code is not None:
        restrictions.append(f"Code: {code}")

    description_parts: list[str] = []
    minimum_bill = _numeric_field(item, _MINIMUM_KEYS, evidence, "minimum_bill")
    if structured:
        if flat_amount is not None:
            description_parts.append(f"Flat discount: ₹{flat_amount:g}")
        if minimum_bill is not None:
            description_parts.append(f"Minimum bill: ₹{minimum_bill:g}")
        if cap is not None:
            description_parts.append(f"Maximum discount: ₹{cap:g}")
        if time_window is not None:
            description_parts.append(f"Applicable time: {time_window}")
        description = "; ".join(description_parts) or None
    else:
        description = raw_text

    values: dict[str, Any] = {
        "title": title,
        "description": description,
        "discount_percent": percentage,
        "minimum_bill": minimum_bill,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "restrictions": tuple(restrictions),
        "source": evidence,
    }
    try:
        return Offer(**values)
    except (TypeError, ValueError, ValidationError):
        raise _schema_error(
            evidence, "offer contains invalid normalized terms"
        ) from None


def parse_offers(
    payload: Mapping[str, object], evidence: SourceEvidence
) -> tuple[Offer, ...]:
    """Parse provider offer data without retaining the raw response."""

    root = _as_mapping(payload, evidence, "payload must be an object")
    status = _text(root.get("status")) or _text(root.get("status_message"))
    if status is not None and status.casefold() not in {"success", "ok", "active"}:
        raise ProviderResponseError(f"{evidence.endpoint_id} returned a provider error")
    if root.get("error") is not None:
        raise ProviderResponseError(f"{evidence.endpoint_id} returned a provider error")
    raw_offers = root.get("offers")
    if raw_offers is None:
        raw_offers = root.get("items")
    if not isinstance(raw_offers, Sequence) or isinstance(raw_offers, (str, bytes)):
        raise _schema_error(evidence, "offers must be a sequence")

    parsed: list[Offer] = []
    for raw_offer in raw_offers:
        offer = _parse_offer(
            _as_mapping(raw_offer, evidence, "offer must be an object"), evidence
        )
        if offer is not None:
            parsed.append(offer)
    return tuple(parsed)


__all__ = ["parse_offers"]
