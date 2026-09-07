"""Typer CLI for read-only Swiggy Dineout workflows."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping
from typing import NoReturn, cast

import typer

from swiggy import __version__
from swiggy.client import SwiggyClient
from swiggy.location import Coordinates as LocationCoordinates
from swiggy.location import LocationResolver, LocationStore
from swiggy.models import VenueRecord
from swiggy.transport import SwiggyTransport

app = typer.Typer(add_completion=False, no_args_is_help=True)
location_app = typer.Typer(add_completion=False)
app.add_typer(location_app, name="location")

CLIENT_FACTORY: Callable[[], SwiggyClient] | None = None
STORE_FACTORY: Callable[[], LocationStore] | None = None
_DEFAULT_STORE: LocationStore | None = None
_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def get_client() -> SwiggyClient:
    if CLIENT_FACTORY is not None:
        return CLIENT_FACTORY()
    return SwiggyClient(transport=SwiggyTransport())  # type: ignore[arg-type]


def get_location_store() -> LocationStore:
    global _DEFAULT_STORE
    if STORE_FACTORY is not None:
        return STORE_FACTORY()
    if _DEFAULT_STORE is None:
        _DEFAULT_STORE = LocationStore()
    return _DEFAULT_STORE


def _json_value(value: object) -> object:
    if isinstance(value, Exception):
        return type(value).__name__
    if isinstance(value, LocationCoordinates):
        return {
            "latitude": value.latitude,
            "longitude": value.longitude,
            "source": value.source,
            "approval_timestamp": value.approval_timestamp.isoformat(),
        }
    if isinstance(value, VenueRecord):
        return value.model_dump(mode="json")
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def _emit(
    command: str,
    query: Mapping[str, object],
    results: Iterable[object],
    *,
    partial: bool = False,
    errors: Iterable[object] = (),
    as_json: bool = False,
) -> None:
    result_values = [_json_value(item) for item in results]
    error_values = [_json_value(item) for item in errors]
    if as_json:
        typer.echo(
            json.dumps(
                {
                    "schema_version": "1",
                    "query": {"command": command, **query},
                    "results": result_values,
                    "partial": partial,
                    "errors": error_values,
                },
                ensure_ascii=False,
                sort_keys=False,
            )
        )
        return
    for item in result_values:
        if isinstance(item, Mapping):
            label = item.get("name") or item.get("title") or item.get("text")
            if label is None and "rating" in item:
                label = f"rating: {item['rating']}"
            typer.echo(str(label or "result"))
            if "rating_count" in item:
                typer.echo(f"rating count: {item['rating_count']}")
            provenance = item.get("provenance")
            if isinstance(provenance, Mapping):
                typer.echo(f"evidence: {len(provenance)} sourced field(s)")
            else:
                typer.echo("evidence: unavailable")
            trend = item.get("trend")
            typer.echo(f"trend: {trend or 'insufficient evidence'}")
            reason = item.get("reason")
            if reason:
                typer.echo(f"reason: {reason}")
        else:
            typer.echo(str(item))
    for error in error_values:
        typer.echo(f"error: {error}")


def _fail(message: str) -> NoReturn:
    typer.echo(message)
    raise typer.Exit(code=2)


def _validate_positive(value: float, label: str) -> float:
    if value <= 0:
        _fail(f"{label} must be greater than zero")
    return value


def _validate_id(value: str) -> str:
    if not _ID_RE.fullmatch(value):
        _fail("id must contain only letters, numbers, underscores, or hyphens")
    return value


def _resolve_location(
    latitude: float | None, longitude: float | None
) -> LocationCoordinates:
    if (latitude is None) != (longitude is None):
        _fail("provide both latitude and longitude")
    if latitude is not None and longitude is not None:
        try:
            return LocationCoordinates(latitude, longitude, source="explicit")
        except Exception as error:
            _fail(str(error))
    try:
        return LocationResolver(store=get_location_store()).resolve(None, None)
    except Exception as error:
        _fail(str(error))


@app.callback(invoke_without_command=True)
def main(
    version: bool = typer.Option(
        False, "--version", help="Show the version and exit.", is_eager=True
    ),
) -> None:
    if version:
        typer.echo(f"swiggy-py {__version__}")


@app.command("restaurants")
def restaurants(
    radius: float | None = typer.Option(None, "--radius"),
    limit: int = typer.Option(100, "--limit"),
    latitude: float | None = typer.Option(None, "--latitude"),
    longitude: float | None = typer.Option(None, "--longitude"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    if radius is not None:
        _validate_positive(radius, "radius")
    if limit <= 0:
        _fail("limit must be greater than zero")
    resolved = _resolve_location(latitude, longitude)
    location_query = {"location_source": resolved.source}
    client = get_client()
    try:
        venues = client.search_nearby(
            max_results=limit,
            radius_km=radius,
            latitude=resolved.latitude,
            longitude=resolved.longitude,
        )
        _emit(
            "restaurants",
            {"radius_km": float(radius or 15), "limit": limit, **location_query},
            venues,
            partial=bool(client.enrichment_failures),
            errors=client.enrichment_failures,
            as_json=as_json,
        )
    finally:
        client.close()


def _id_command(
    command: str,
    value: str,
    *,
    as_json: bool,
    getter: Callable[[SwiggyClient, str], object],
) -> None:
    venue_id = _validate_id(value)
    client = get_client()
    try:
        result = getter(client, venue_id)
        results = result if isinstance(result, tuple) else (result,)
        _emit(command, {"id": venue_id}, results, as_json=as_json)
    finally:
        client.close()


@app.command("restaurant")
def restaurant(
    id: str = typer.Option(..., "--id"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    _id_command(
        "restaurant",
        id,
        as_json=as_json,
        getter=lambda client, venue_id: client.get_restaurant(venue_id),
    )


@app.command("offers")
def offers(
    id: str | None = typer.Option(None, "--id"),
    radius: float | None = typer.Option(None, "--radius"),
    latitude: float | None = typer.Option(None, "--latitude"),
    longitude: float | None = typer.Option(None, "--longitude"),
    limit: int = typer.Option(100, "--limit"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    if id is not None and radius is not None:
        _fail("--id and --radius are mutually exclusive")
    if id is None and radius is None:
        _fail("provide either --id or --radius")
    if limit <= 0:
        _fail("limit must be greater than zero")
    client = get_client()
    try:
        if id is not None:
            venue_id = _validate_id(id)
            result = client.get_offers(venue_id)
            query = {"id": venue_id, "limit": limit}
        else:
            distance = _validate_positive(radius or 0, "radius")
            resolved = _resolve_location(latitude, longitude)
            result = client.rank_nearby(
                "offers",
                radius_km=distance,
                latitude=resolved.latitude,
                longitude=resolved.longitude,
                limit=limit,
            )
            query = {
                "radius_km": float(distance),
                "limit": limit,
                "location_source": resolved.source,
            }
        _emit(
            "offers",
            query,
            result if isinstance(result, (list, tuple)) else (result,),
            as_json=as_json,
        )
    finally:
        client.close()


@app.command("reviews")
def reviews(
    id: str = typer.Option(..., "--id"),
    limit: int = typer.Option(30, "--limit"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    if limit <= 0:
        _fail("limit must be greater than zero")
    venue_id = _validate_id(id)
    client = get_client()
    try:
        result = client.get_reviews(venue_id, limit=limit)
        _emit("reviews", {"id": venue_id, "limit": limit}, result, as_json=as_json)
    finally:
        client.close()


def _ranking_command(
    mode: str,
    radius: float | None,
    limit: int,
    latitude: float | None,
    longitude: float | None,
    as_json: bool,
) -> None:
    if radius is not None:
        _validate_positive(radius, "radius")
    if limit <= 0:
        _fail("limit must be greater than zero")
    resolved = _resolve_location(latitude, longitude)
    location_query = {"location_source": resolved.source}
    client = get_client()
    try:
        result = client.rank_nearby(
            mode,
            radius_km=radius,
            latitude=resolved.latitude,
            longitude=resolved.longitude,
            limit=limit,
            max_workers=4,
        )
        _emit(
            mode,
            {"radius_km": float(radius or 15), "limit": limit, **location_query},
            result,
            as_json=as_json,
        )
    finally:
        client.close()


@app.command("trending")
def trending(
    radius: float | None = typer.Option(None, "--radius"),
    limit: int = typer.Option(100, "--limit"),
    latitude: float | None = typer.Option(None, "--latitude"),
    longitude: float | None = typer.Option(None, "--longitude"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    _ranking_command("trending", radius, limit, latitude, longitude, as_json)


@app.command("top-rated")
def top_rated(
    radius: float | None = typer.Option(None, "--radius"),
    limit: int = typer.Option(100, "--limit"),
    latitude: float | None = typer.Option(None, "--latitude"),
    longitude: float | None = typer.Option(None, "--longitude"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    _ranking_command("top-rated", radius, limit, latitude, longitude, as_json)


@app.command("new")
def new(
    radius: float | None = typer.Option(None, "--radius"),
    limit: int = typer.Option(100, "--limit"),
    latitude: float | None = typer.Option(None, "--latitude"),
    longitude: float | None = typer.Option(None, "--longitude"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    _ranking_command("new", radius, limit, latitude, longitude, as_json)


@app.command("nightlife")
def nightlife(
    radius: float | None = typer.Option(None, "--radius"),
    limit: int = typer.Option(100, "--limit"),
    latitude: float | None = typer.Option(None, "--latitude"),
    longitude: float | None = typer.Option(None, "--longitude"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    _ranking_command("nightlife", radius, limit, latitude, longitude, as_json)


@location_app.command("set")
def location_set(
    latitude: float | None = typer.Option(None, "--latitude"),
    longitude: float | None = typer.Option(None, "--longitude"),
) -> None:
    if (latitude is None) != (longitude is None):
        _fail("provide both latitude and longitude")
    if latitude is None or longitude is None:
        _fail("provide both latitude and longitude")
    assert latitude is not None and longitude is not None
    try:
        coordinates = LocationCoordinates(latitude, longitude, source="approved")
    except Exception as error:
        _fail(str(error))
    get_location_store().save(coordinates)
    typer.echo("saved approved location")


@location_app.command("show")
def location_show(
    reveal: bool = typer.Option(False, "--reveal"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    location = get_location_store().load()
    if location is None:
        data: dict[str, object] = {"available": False}
    elif reveal:
        data = cast(dict[str, object], _json_value(location))
    else:
        data = {"available": True, "source": location.source}
    if as_json:
        typer.echo(json.dumps(data, ensure_ascii=False, sort_keys=False))
    elif not data.get("available"):
        typer.echo("No saved location available")
    elif reveal:
        typer.echo(
            f"Saved location ({data['source']}): "
            f"latitude={data['latitude']}, longitude={data['longitude']}"
        )
    else:
        typer.echo(f"Saved location available (source: {data['source']})")


@location_app.command("clear")
def location_clear() -> None:
    store = get_location_store()
    try:
        store.path.unlink()
    except FileNotFoundError:
        pass
    typer.echo("cleared saved location")


@location_app.command("detect")
def location_detect() -> None:
    store = get_location_store()
    location = LocationResolver(store=store).resolve(None, None)
    store.save(location)
    typer.echo("detected and saved location")


__all__ = [
    "LocationCoordinates",
    "LocationStore",
    "app",
    "get_client",
    "get_location_store",
]
