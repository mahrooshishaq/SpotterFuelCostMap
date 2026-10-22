# Fuel Stop Planner

## Current milestone

Milestone 1 created the reproducible CSV outputs. Milestone 2, task 1
created the Django project (`config`) and application (`planner`).

## Development setup

Create or activate the virtual environment, then install dependencies:

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The Django dependency range accepts the latest stable Django release
supported by the project. PostgreSQL connectivity uses Psycopg 3.

## Database configuration

SQLite is the current development database for this assessment. It requires
no separate server and is already the default in the Django settings.

From the project directory:

```bat
cd /d D:\SpotterAssessment
.venv\Scripts\activate
python manage.py check
python manage.py migrate
```

This creates `db.sqlite3` locally. The database file is excluded from Git.

### Optional PostgreSQL configuration

PostgreSQL remains supported through environment variables if it is needed
later. In Command Prompt, set values for the current session:

```bat
set DJANGO_DEBUG=1
set DB_ENGINE=django.db.backends.postgresql
set DB_NAME=fuel_stop_planner
set DB_USER=postgres
set DB_PASSWORD=your-postgres-password
set DB_HOST=127.0.0.1
set DB_PORT=5432
```

Create the database once in PostgreSQL if it does not already exist:

```sql
CREATE DATABASE fuel_stop_planner;
```

Remove `DB_ENGINE` and the `DB_*` values to return to SQLite. Do not commit
passwords or other secrets; use `.env.example` as the configuration template.

## Django commands

The `FuelStation` model and import command are available now:

```bat
python manage.py check
python manage.py migrate
python manage.py import_fuel_stations
```

The import command reads
`data\processed\fuel_stations_cleaned.csv` by default. A different cleaned
CSV can be supplied with:

```bat
python manage.py import_fuel_stations --input path\to\cleaned.csv
```

It validates required columns, imports or updates records deterministically,
preserves existing geocoding fields, and reports imported, updated, unchanged,
and total counts. The planner URL namespace is available under `/api/`.

## Station geocoding sample

Run the one-time representative sample only after the database import:

```bat
python manage.py geocode_sample
```

This makes approximately 20 sequential Nominatim requests with a descriptive
User-Agent and at least one second between requests. It writes
`data\geocoding\geocoding_sample.csv` and
`data\geocoding\geocoding_report.json`. The command does not update database
coordinates: manually review each returned label and mark the CSV's
`manual_review` column as `station_level`, `ambiguous`, or `failed` first.
Never treat an automatic candidate status as validated station coordinates.

After filling the `manual_review` column, import only approved coordinates:

```bat
python manage.py import_geocoding_sample
```

Only rows marked `station_level` are imported. Rows marked `ambiguous` or
`failed`, and rows without that approval, remain without coordinates and are
excluded from route recommendations by the future matching service. The
command verifies both the Django database ID and OPIS ID before updating a
station.

### Larger targeted batch

After the sample decision, conventional street-address records can be
processed with the resumable batch command:

```bat
python manage.py geocode_batch --limit 100
```

Omit `--limit` to process all eligible conventional-address records. The
command reuses `data\geocoding\nominatim_cache.json`, so completed lookups
are not repeated. It writes `geocoding_batch.csv` and
`geocoding_batch_report.json`. The batch applies a conservative automatic
review: only fuel/convenience/service results with a shared station-name token
are marked `station_level`; all other results are excluded. Highway/exit
descriptions are intentionally excluded from this batch.

Import the automatically approved rows:

```bat
python manage.py import_geocoding_sample --input data\geocoding\geocoding_batch.csv
```

### OpenStreetMap station coordinates

The company CSV remains the price source. OpenStreetMap can provide station
coordinates through its Overpass API. The importer queries `amenity=fuel`
records by state, caches the responses, and performs conservative
state/city/name matching. It is a dry run by default:

```bat
python manage.py import_osm_stations --states AL,AR,AZ
```

Inspect the reported match counts first. Apply only unique high-confidence
matches with:

```bat
python manage.py import_osm_stations --states AL,AR,AZ --apply
```

The Overpass cache is stored in
`data\geocoding\overpass_fuel_stations.json`. Existing manually verified
coordinates are preserved. Cached states are reused and the command waits
between uncached state requests.

The importer queries small geographic tiles instead of one whole-state
request, retries temporary Overpass gateway/rate-limit failures, and falls
back to a second public endpoint. Each completed tile is cached independently.
A failed request does not create a cache entry, so rerunning safely retries
that tile. Use `--tile-size 1` for smaller requests if needed.
If a public endpoint remains unavailable for a tile, add `--allow-partial`;
the command will keep completed tiles, report failed tiles, and still produce
a match report.

## Routing service

Milestone 4A provides `planner.services.routing.get_route`. It sends one
OSRM driving request per uncached origin/destination pair, requests full
GeoJSON geometry, validates the response, converts metres to miles and
seconds to minutes, and caches successful normalized results. It never
substitutes a straight line for a failed driving route.

Run the focused routing tests with:

```bat
python manage.py test planner.test_routing
```

Milestone 4B provides
`planner.services.station_matching.match_stations_to_route`. It scans
coordinate-backed stations locally, excludes missing coordinates and centroid
fallbacks, includes stations within five straight-line miles of the route,
and orders matches by cumulative route position.

## Route-plan API

The integrated endpoint is:

```text
POST /api/v1/route-plan/
```

It currently accepts coordinates so route behavior can be tested without
requiring a location-geocoding service:

```json
{
  "start": {"longitude": -86.0, "latitude": 33.0},
  "destination": {"longitude": -85.0, "latitude": 33.0}
}
```

The response contains validated OSRM GeoJSON geometry, route distance and
duration, selected stops, provided prices, route positions, gallons purchased,
per-stop estimated purchase costs, total route fuel, total purchased fuel, and
total purchase cost. Only matched station-level coordinates are considered.
Routing failures return `502`; an infeasible fuel plan returns `422` with code
`NO_FEASIBLE_FUEL_PLAN`.

Milestone 4C provides `planner.services.fuel_planning.plan_fuel_stops`.
It uses the agreed full-tank/full-refill model, enforces the 500-mile range,
charges the next station based on gallons needed since the previous full tank,
and uses route-ordered dynamic programming rather than a greedy choice.
It reports route fuel consumption separately from purchased gallons and
purchase cost.

Run the focused planning tests with:

```bat
python manage.py test planner.test_fuel_planning
```

## Swagger and map

Install the current dependencies after this phase:

```bat
python -m pip install -r requirements.txt
```

Start the development server:

```bat
python manage.py runserver
```

Open:

- Map: `http://127.0.0.1:8000/`
- Swagger UI: `http://127.0.0.1:8000/api/docs/`
- OpenAPI schema: `http://127.0.0.1:8000/api/schema/`
- Route API: `POST http://127.0.0.1:8000/api/v1/route-plan/`

The Leaflet page uses Esri World Street Map tiles with attribution. Users enter
US place names; the page resolves them through the place-lookup endpoint and
then submits longitude/latitude coordinates to the route API. It draws the
returned OSRM GeoJSON route and displays numbered optimized stops and the cost
summary. The map uses distinct markers for the start, destination, and selected
refueling stops, and lists each selected stop's route position, provided price,
gallons purchased, and estimated cost below the map. The coordinate-based route
endpoint remains available for API clients.

The vehicle starts with 50 gallons under the 500-mile/10-MPG assumptions, so
the initial tank cost is excluded. The UI separately explains total route fuel
consumed and fuel purchased during the trip. Duplicate station records at the
same route position are reduced to the cheapest candidate before optimization.

The demonstration currently uses coordinate-backed station records only.
The supplied CSV prices are described as provided dataset values, not live
prices, and station detour miles are excluded from the v1 fuel calculation.

## Assessment assumptions and limitations

The planner follows the assessment model rather than live vehicle behavior:

- The vehicle starts with a full 50-gallon tank.
- Maximum range is 500 miles.
- Fuel economy is fixed at 10 MPG.
- Selected stations refill the tank fully.
- The initial tank purchase cost is unknown and excluded.
- Fuel consumed on the route is reported separately from fuel purchased during
  the trip.
- The destination is not a refueling stop.
- Station detour miles are excluded from the v1 fuel calculation.
- Prices are the supplied dataset values and are not live market prices.
- Only stations with station-level coordinates are eligible.
- Candidate stations must be within five straight-line miles of the route.
- The optimizer minimizes total estimated purchase cost subject to the range
  constraint; it is not a greedy “cheapest station” lookup.
- An infeasible route returns `NO_FEASIBLE_FUEL_PLAN` rather than inventing a
  station or silently violating the range constraint.

The repository intentionally excludes the supplied company CSV, cleaned
outputs, geocoding caches, generated reports, SQLite data, virtual
environments, and secrets. The CSV remains preserved locally as the source of
truth and is reproducibly cleaned/imported using the scripts and management
commands documented above.

## Three-minute demonstration scenarios

Use the browser page at `http://127.0.0.1:8000/` after starting Django.
The public Nominatim place lookup and OSRM route request require internet
access.

### Scenario 1: route requiring a purchase

```text
Start: Decatur, Alabama
Destination: Jacksonville, Florida
```

This route is approximately 506 miles. It is just beyond the 500-mile range,
so the result demonstrates the full-tank model, selected refueling stops,
provided station prices, purchased gallons, and total purchase cost. Explain
that the route consumes about 50.61 gallons, starts with 50 gallons, and may
purchase more than the net 0.61-gallon deficit because selected stops refill
the tank fully and the vehicle can arrive with fuel remaining.

### Scenario 2: route within the initial range

```text
Start: Birmingham, Alabama
Destination: Atlanta, Georgia
```

This is a shorter route and normally needs no refueling purchase. It
demonstrates that the planner does not add an unnecessary stop when the full
starting tank can reach the destination.

### Scenario 3: another short route

```text
Start: Birmingham, Alabama
Destination: Montgomery, Alabama
```

This also normally completes within the initial range. Use it to show the
route map, zero selected stops, and zero purchase cost while fuel consumption
is still reported separately.

The live map distinguishes the blue `S` start marker, red `D` destination
marker, and green numbered selected-refuel markers. The stop cards below the
map show each selected station, route position, provided price, gallons
purchased, and estimated cost.

## Five-minute Loom outline

1. **0:00–0:30 — Goal:** “This Django application plans a driving route and
   selects the least-cost feasible fuel stops using supplied station prices.”
2. **0:30–1:10 — Data:** Show `scripts\prepare_fuel_data.py` and explain that
   the original company CSV is preserved, Canadian rows and invalid records
   are excluded, duplicates are resolved, and the cleaned records are
   imported into SQLite.
3. **1:10–1:45 — Backend:** Show `planner\models.py` and
   `planner\services\station_matching.py`. Explain that prices come from the
   company CSV while station coordinates come from validated coordinate
   enrichment, and only stations within the route corridor are eligible.
4. **1:45–2:25 — Optimization:** Show
   `planner\services\fuel_planning.py`. Explain the 500-mile range, 10 MPG,
   50-gallon starting tank, full-refill model, and route-ordered dynamic
   programming that compares feasible station sequences by total purchase cost.
5. **2:25–4:25 — Demo:** Run the three scenarios above. For the long route,
   point out the S/D markers, green numbered stops, per-stop gallons/cost, and
   total purchase cost. For the short routes, point out zero selected stops
   and zero purchase cost.
6. **4:25–5:00 — API/tests/limitations:** Briefly show `/api/docs/`, mention
   OSRM supplies driving geometry, and state that prices are provided dataset
   values and coordinate coverage is limited to validated station records.
