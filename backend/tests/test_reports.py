"""TASKS.md #16: a rider can report a problem with a specific request, the
report is stored durably (not just logged to stdout), and never surfaced
in any public response.
"""

from datetime import datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.db import make_session_factory
from app.main import app
from app.models import AbuseReportORM
from app.reports import ReportStore
from app.schemas import AbuseReport

FAIRFAX = (38.8462, -77.3064)
ALDIE = (38.9757, -77.6122)


def _one_off_payload(rider_id, contact):
    earliest = datetime.utcnow() + timedelta(hours=2)
    return {
        "rider_id": rider_id,
        "origin": {"lat": FAIRFAX[0], "lng": FAIRFAX[1]},
        "destination": {"lat": ALDIE[0], "lng": ALDIE[1]},
        "schedule": {
            "earliest_departure": earliest.isoformat(),
            "latest_departure": (earliest + timedelta(minutes=30)).isoformat(),
        },
        "seats_needed": 1,
        "contact": contact,
    }


def _row_count(session_factory: sessionmaker, reported_request_id) -> int:
    with session_factory() as session:
        return (
            session.query(AbuseReportORM)
            .filter(AbuseReportORM.reported_request_id == reported_request_id)
            .count()
        )


def test_report_store_add_persists_across_a_simulated_restart():
    report = AbuseReport(
        reported_request_id=uuid4(), reason="posted a home address in the open thread"
    )

    ReportStore(make_session_factory()).add(report)

    # A brand-new session factory -- nothing shares a Python object with
    # the store above, so this only passes if Postgres actually persisted
    # the row (mirrors tests/test_store_persistence.py's own pattern).
    assert _row_count(make_session_factory(), report.reported_request_id) == 1


def test_post_report_on_an_existing_request_is_stored_durably():
    payload = _one_off_payload("rider-report-target", contact="555-0601")

    with TestClient(app) as client:
        created = client.post("/requests", json=payload).json()
        response = client.post(
            f"/requests/{created['id']}/report",
            json={"reason": "showed up with three strangers, not one"},
        )

    assert response.status_code == 201
    assert response.json() == {"status": "received"}
    assert _row_count(make_session_factory(), created["id"]) == 1


def test_post_report_includes_reporter_request_id_when_given():
    payload_a = _one_off_payload("rider-report-reporter-a", contact="555-0602")

    with TestClient(app) as client:
        created = client.post("/requests", json=payload_a).json()
        reporter_id = str(uuid4())
        client.post(
            f"/requests/{created['id']}/report",
            json={"reason": "no-show", "reporter_request_id": reporter_id},
        )

    with make_session_factory()() as session:
        row = (
            session.query(AbuseReportORM)
            .filter(AbuseReportORM.reported_request_id == created["id"])
            .one()
        )
        assert str(row.reporter_request_id) == reporter_id


def test_post_report_on_unknown_request_returns_404_and_stores_nothing():
    unknown_id = uuid4()

    with TestClient(app) as client:
        response = client.post(f"/requests/{unknown_id}/report", json={"reason": "spam"})

    assert response.status_code == 404
    assert _row_count(make_session_factory(), unknown_id) == 0


def test_post_report_with_empty_reason_is_rejected():
    payload = _one_off_payload("rider-report-empty-reason", contact="555-0603")

    with TestClient(app) as client:
        created = client.post("/requests", json=payload).json()
        response = client.post(f"/requests/{created['id']}/report", json={"reason": ""})

    assert response.status_code == 422
    assert _row_count(make_session_factory(), created["id"]) == 0


def test_report_never_appears_in_any_public_response():
    payload = _one_off_payload("rider-report-privacy", contact="555-0604")
    secret_reason = "very-specific-harassment-detail-xyz"

    with TestClient(app) as client:
        created = client.post("/requests", json=payload).json()
        client.post(f"/requests/{created['id']}/report", json={"reason": secret_reason})

        detail = client.get(f"/requests/{created['id']}")
        listing = client.get("/requests")

    assert secret_reason not in detail.text
    assert secret_reason not in listing.text
    assert "report" not in detail.json()
