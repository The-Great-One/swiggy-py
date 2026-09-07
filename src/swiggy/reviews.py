"""Pure parsing of provider review pages into immutable samples."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from pydantic import ValidationError

from swiggy.errors import ProviderResponseError, SchemaDriftError
from swiggy.models import ReviewSample
from swiggy.provenance import SourceEvidence


@dataclass(frozen=True, slots=True)
class ReviewPage:
    """A parsed review page and its optional provider pagination token."""

    reviews: tuple[ReviewSample, ...]
    next_cursor: str | None = None
    review_ids: tuple[str, ...] = ()


def _schema_error(evidence: SourceEvidence, detail: str) -> SchemaDriftError:
    return SchemaDriftError(f"{evidence.endpoint_id} reviews: {detail}")


def _as_mapping(value: object, evidence: SourceEvidence) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _schema_error(evidence, "payload must be an object")
    return value


def _cursor(payload: Mapping[str, object]) -> str | None:
    candidates: list[object] = [
        payload.get("next_cursor"),
        payload.get("nextCursor"),
        payload.get("next_offset"),
    ]
    pagination = payload.get("pagination")
    if isinstance(pagination, Mapping):
        candidates.extend(
            (
                pagination.get("next_cursor"),
                pagination.get("nextCursor"),
                pagination.get("next_offset"),
                pagination.get("cursor"),
            )
        )
    page_offset = payload.get("page_offset")
    if isinstance(page_offset, Mapping):
        candidates.append(page_offset.get("next_offset"))
    for value in candidates:
        if value is not None and not isinstance(value, bool):
            return str(value)
    return None


def _review_items(
    payload: Mapping[str, object], evidence: SourceEvidence
) -> Sequence[object]:
    for key in ("reviews", "review_list", "reviewList", "items"):
        value = payload.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return value
        if value is not None:
            raise _schema_error(evidence, f"{key} must be a sequence")

    data = payload.get("data")
    if isinstance(data, Sequence) and not isinstance(data, (str, bytes)):
        return data
    if isinstance(data, Mapping):
        for key in ("reviews", "review_list", "reviewList", "items"):
            value = data.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                return value
            if value is not None:
                raise _schema_error(evidence, f"data.{key} must be a sequence")
    raise _schema_error(evidence, "reviews must be a sequence")


def _first_value(review: Mapping[str, object], *names: str) -> tuple[bool, object]:
    for name in names:
        if name in review:
            return True, review[name]
    return False, None


def _rating(review: Mapping[str, object], evidence: SourceEvidence) -> float:
    present, raw = _first_value(
        review, "rating", "review_rating", "reviewRating", "stars"
    )
    if not present or raw is None or isinstance(raw, bool):
        raise _schema_error(evidence, "review is missing rating")
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise _schema_error(evidence, "review has invalid rating") from None
    return value


def _reviewed_at(
    review: Mapping[str, object], evidence: SourceEvidence
) -> datetime | None:
    present, raw = _first_value(
        review,
        "reviewed_at",
        "reviewedAt",
        "created_at",
        "createdAt",
        "review_date",
        "reviewDate",
        "timestamp",
    )
    if not present or raw is None:
        return None
    if isinstance(raw, datetime):
        value = raw
    elif isinstance(raw, str):
        text = raw.strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            value = datetime.fromisoformat(text)
        except ValueError:
            raise _schema_error(evidence, "review has invalid timestamp") from None
    else:
        raise _schema_error(evidence, "review has invalid timestamp")
    if value.tzinfo is None or value.utcoffset() is None:
        raise _schema_error(evidence, "review timestamp must include timezone")
    return value


def _text(review: Mapping[str, object], evidence: SourceEvidence) -> str | None:
    present, raw = _first_value(
        review, "text", "review_text", "reviewText", "comment", "content", "excerpt"
    )
    if not present or raw is None:
        return None
    if not isinstance(raw, str):
        raise _schema_error(evidence, "review text must be a string")
    return raw


def _review_id(review: Mapping[str, object], evidence: SourceEvidence) -> str | None:
    present, raw = _first_value(review, "review_id", "reviewId", "id")
    if not present or raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (str, int)):
        raise _schema_error(evidence, "review has invalid id")
    value = str(raw).strip()
    if not value:
        raise _schema_error(evidence, "review has invalid id")
    return value


def _review_from_mapping(
    review: Mapping[str, object], evidence: SourceEvidence
) -> tuple[ReviewSample, str | None]:
    try:
        sample = ReviewSample(
            rating=_rating(review, evidence),
            text=_text(review, evidence),
            reviewed_at=_reviewed_at(review, evidence),
            source=evidence,
        )
    except SchemaDriftError:
        raise
    except ValidationError:
        raise _schema_error(
            evidence, "review contains invalid normalized values"
        ) from None
    return sample, _review_id(review, evidence)


def parse_reviews(
    payload: Mapping[str, object], evidence: SourceEvidence
) -> ReviewPage:
    """Parse one provider review payload without I/O or raw-payload retention."""

    root = _as_mapping(payload, evidence)
    status = root.get("status_message", "success")
    if status != "success" or root.get("error") is not None:
        raise ProviderResponseError(f"{evidence.endpoint_id} returned a provider error")

    reviews: list[ReviewSample] = []
    review_ids: list[str] = []
    for raw_review in _review_items(root, evidence):
        review = _as_mapping(raw_review, evidence)
        sample, review_id = _review_from_mapping(review, evidence)
        reviews.append(sample)
        if review_id is not None:
            review_ids.append(review_id)
    return ReviewPage(
        reviews=tuple(reviews),
        next_cursor=_cursor(root),
        review_ids=tuple(review_ids),
    )


__all__ = ["ReviewPage", "parse_reviews"]
