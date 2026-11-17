# BusBidder Spain

Final project in ACIT4420 Problem-solving with scripting, OsloMet 2026.

The program finds bus offers from Madrid for a traveller. It removes offers that break the traveller's requirements, ranks the rest with a weighted score and explains the top result. The traveller can then make a simulated booking.

## Requirements

- Python 3.10 or newer (tested on 3.12 on Windows and 3.13 on Linux)
- Only the standard library is used
- pytest for the tests

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python3 -m pip install -e ".[test]"
```

On Windows, use `python` instead of `python3`.

## How to run

Run all commands from the project root.

The entry point is `src/busbidder/__main__.py`, which is run with `python3 -m busbidder`.

```bash
python3 -m busbidder                                   # interactive menu
python3 -m busbidder validate                          # check the data
python3 -m busbidder rank --profile spec_example       # rank offers for one profile
python3 -m busbidder rank --profile spec_example --show-removed
python3 -m busbidder compare                           # compare all profiles
python3 -m busbidder book --profile business --offer CAM-MAL-20260714-01 --traveller "Emma Olsen"
python3 -m busbidder bookings
python3 -m busbidder cancel BB-2026-XXXXXX
```

To test validation with the invalid file:

```bash
python3 -m busbidder --offers data/offers.csv --offers data/offers_invalid.csv validate
```

## Tests

```bash
python3 -m pytest
```

## Input files

All input files are in `data/`:

- `companies.csv`: the 5 bus companies
- `destinations.csv`: the 15 destinations
- `offers.csv`: 882 offers, made by `scripts/generate_offers.py` (fixed seed, so the same data every time)
- `offers_invalid.csv`: rows with errors on purpose, for testing validation
- `profiles.json`: the journey and the five traveller profiles

## Output files

These are written to `output/`:

- `busbidder.log`: the log
- `rejected_records.txt`: rows that were rejected, and why
- `profile_comparison.csv`: top 3 offers for each profile
- `bookings.json`: saved bookings (delete it to reset the seats)

Example output used in the report is in `examples/`.

## Project structure

```
data/            input files
scripts/         data generator
src/busbidder/   the program
tests/           tests
examples/        example output
```
