"""Loading tests: official data, the intentionally invalid file and broken files."""

import pytest

from busbidder.exceptions import DataFileError
from busbidder.loader import LoadReport, load_marketplace, load_profiles, read_csv_rows

HEADER = ("offer_id,company_id,destination_id,departure,arrival,duration_min,price_eur,transfers,"
          "luggage_kg,changeable,change_fee_eur,refundable,available_seats,rating,co2_kg\n")
VALID_ROW = "SOL-MAL-20260712-01,SOL,MAL,2026-07-12 10:30,2026-07-12 18:10,460,38.57,0,15,no,0,no,26,3.0,15.9\n"


def copy_reference_data(source, target):
    for name in ("companies.csv", "destinations.csv", "profiles.json"):
        (target / name).write_text((source / name).read_text(encoding="utf-8"), encoding="utf-8")


def test_official_data_loads_without_rejections(data_dir):
    marketplace, report = load_marketplace(data_dir)
    assert len(marketplace.companies) == 5
    assert len(marketplace.destinations) == 15
    assert len(marketplace.offers) > 75  # at least one offer per company-destination pair
    assert report.rejected == []
    pairs = {(o.company.company_id, o.destination.destination_id) for o in marketplace.all_offers()}
    assert len(pairs) == 75


def test_invalid_file_rejects_each_planted_error(data_dir):
    marketplace, report = load_marketplace(data_dir, [data_dir / "offers_invalid.csv"])
    reasons = {error.row_number: (error.field, error.reason) for error in report.rejected}
    assert "too short" in reasons[3][1]
    assert "real calendar date" in reasons[4][1]
    assert reasons[5][0] == "rating"                 # outside 1-5
    assert "unknown destination" in reasons[7][1]
    assert reasons[8][0] == "price_eur"              # negative price
    assert reasons[9][0] == "arrival"                # arrival before departure
    assert reasons[10][0] == "changeable"
    assert "missing" in reasons[11][1]
    assert reasons[12][0] == "available_seats"       # negative seats
    assert reasons[14][0] == "offer_id"              # malformed identifier
    assert "whole number" in reasons[15][1]
    assert "unknown company" in reasons[17][1]
    assert "does not match" in reasons[18][1]        # id does not match company
    assert "duplicate" in reasons[19][1]
    assert reasons[20][0] == "transfers"             # more than 3
    assert "non-changeable" in reasons[21][1]
    assert len(report.rejected) == 16


def test_invalid_file_corrections_and_set_aside(data_dir):
    marketplace, report = load_marketplace(data_dir, [data_dir / "offers_invalid.csv"])
    assert any("duration_min 240 replaced" in text for text in report.corrected)
    assert "SOL-ZAZ-20260717-01" in marketplace.offers            # spaces and case fixed
    assert marketplace.offers["CAM-VLC-20260718-01"].is_sold_out  # kept, but set aside
    assert marketplace.offers["CST-MAL-20260717-02"].co2_kg is None


def test_missing_file_raises_data_file_error(tmp_path):
    with pytest.raises(DataFileError, match="file not found"):
        list(read_csv_rows(tmp_path / "missing.csv", ["offer_id"]))


def test_missing_column_raises_data_file_error(tmp_path):
    path = tmp_path / "offers.csv"
    path.write_text("offer_id,company_id\nSOL-MAL-20260712-01,SOL\n", encoding="utf-8")
    with pytest.raises(DataFileError, match="missing column"):
        list(read_csv_rows(path, ["offer_id", "price_eur"]))


def test_empty_offer_file_loads_zero_offers(data_dir, tmp_path):
    copy_reference_data(data_dir, tmp_path)
    (tmp_path / "offers.csv").write_text(HEADER, encoding="utf-8")
    marketplace, report = load_marketplace(tmp_path)
    assert marketplace.offers == {}


def test_row_with_too_many_values_is_rejected(data_dir, tmp_path):
    copy_reference_data(data_dir, tmp_path)
    (tmp_path / "offers.csv").write_text(HEADER + VALID_ROW.rstrip("\n") + ",extra\n", encoding="utf-8")
    _, report = load_marketplace(tmp_path)
    assert "too many" in report.rejected[0].reason


def test_non_utf8_file_is_reported(data_dir, tmp_path):
    copy_reference_data(data_dir, tmp_path)
    (tmp_path / "offers.csv").write_bytes(HEADER.encode() + "SOL-MAL,Málaga\n".encode("latin-1"))
    with pytest.raises(DataFileError, match="UTF-8"):
        load_marketplace(tmp_path)


def test_report_files_are_written(data_dir, tmp_path):
    _, report = load_marketplace(data_dir, [data_dir / "offers_invalid.csv"])
    path = report.write(tmp_path)
    rejected = path.read_text(encoding="utf-8").splitlines()
    assert rejected[0] == "file\trow\tfield\treason"
    assert len(rejected) == 1 + len(report.rejected)


def test_profiles_load(data_dir):
    profiles = load_profiles(data_dir / "profiles.json")
    assert {"spec_example", "budget", "business"} <= set(profiles)


def test_broken_profiles_json(tmp_path):
    path = tmp_path / "profiles.json"
    path.write_text('{"journey": ', encoding="utf-8")
    with pytest.raises(DataFileError, match="invalid JSON"):
        load_profiles(path)


def test_report_starts_empty():
    report = LoadReport()
    assert report.rejected == [] and report.corrected == [] and report.set_aside == []
