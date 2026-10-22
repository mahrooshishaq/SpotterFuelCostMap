import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


class GeocodingError(Exception):
    """Raised when a place name cannot be converted to coordinates."""


def geocode_place(place: str) -> tuple[float, float]:
    query = place.strip()
    if not query:
        raise GeocodingError("Enter a start and destination place.")

    params = urlencode(
        {
            "q": query,
            "format": "jsonv2",
            "limit": 1,
            "countrycodes": "us",
        }
    )
    request = Request(
        f"https://nominatim.openstreetmap.org/search?{params}",
        headers={"User-Agent": "FuelStopPlanner/1.0 assessment demo"},
    )
    try:
        with urlopen(request, timeout=10) as response:
            results = json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise GeocodingError("The place lookup service is temporarily unavailable.") from exc

    if not results:
        raise GeocodingError(f"No US location was found for '{query}'.")
    try:
        return float(results[0]["lon"]), float(results[0]["lat"])
    except (KeyError, TypeError, ValueError) as exc:
        raise GeocodingError("The place lookup returned invalid coordinates.") from exc
