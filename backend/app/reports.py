"""Durable storage for abuse/harassment reports (TASKS.md #16).

SCOPE.md's "part that isn't just an engineering decision" names "some way
to handle harassment/abuse reports" as needed before this goes live to
real people. Deliberately minimal, per that task's own acceptance wording:
a report just needs to not be lost -- no moderation workflow or admin UI
is built here, and nothing in this module is ever read back out through a
public response (app/router.py's POST /requests/{id}/report writes and
forgets; there's no matching GET).
"""

from app.models import AbuseReportORM
from app.schemas import AbuseReport
from sqlalchemy.orm import sessionmaker


def _to_orm(report: AbuseReport) -> AbuseReportORM:
    return AbuseReportORM(
        id=report.id,
        reported_request_id=report.reported_request_id,
        reporter_request_id=report.reporter_request_id,
        reason=report.reason,
        created_at=report.created_at,
    )


class ReportStore:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def add(self, report: AbuseReport) -> None:
        with self._session_factory() as session:
            session.add(_to_orm(report))
            session.commit()
