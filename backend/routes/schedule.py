"""
routes/schedule.py
------------------
GET  /api/schedule                   — faculty's own schedule (active semester)
GET  /api/schedule/<faculty_id>      — chairperson: any faculty's schedule
POST /api/schedule/publish           — chairperson: persist generated schedule to DB
"""

from __future__ import annotations

import re

from flask import Blueprint, jsonify, request

from database import db
from models import Room, Schedule, Semester, User
from routes.auth import current_user, login_required, role_required

schedule_bp = Blueprint("schedule", __name__, url_prefix="/api/schedule")

# Longest-match-first so "Th" isn't misread as "T" + "h", and "Sat" isn't
# misread as "S" + "at".
_DAY_TOKEN_RE = re.compile(r"Th|Sat|M|T|W|F|S")
_DAY_NAMES = {
    "M": "Monday", "T": "Tuesday", "W": "Wednesday",
    "Th": "Thursday", "F": "Friday", "Sat": "Saturday", "S": "Saturday",
}


def _expand_days(preferred_days: str) -> list[str]:
    """'MWF' -> ['Monday','Wednesday','Friday'], 'TTh' -> ['Tuesday','Thursday']."""
    tokens = _DAY_TOKEN_RE.findall(preferred_days or "")
    days = [_DAY_NAMES[t] for t in tokens if t in _DAY_NAMES]
    return days or ["Monday"]   # never silently drop a section entirely


def _active_semester() -> Semester | None:
    return Semester.query.filter_by(is_active=True).first()


# ── Faculty: own schedule ─────────────────────
@schedule_bp.get("")
@login_required
def get_my_schedule():
    user = current_user()
    sem  = _active_semester()
    if not sem:
        return jsonify({"schedule": [], "message": "No active semester."}), 200

    entries = (
        Schedule.query
        .filter_by(faculty_id=user.id, semester_id=sem.id)
        .order_by(Schedule.day, Schedule.time_start)
        .all()
    )

    return jsonify({
        "faculty":  user.to_dict(),
        "semester": sem.to_dict(),
        "schedule": [e.to_dict() for e in entries],
    }), 200


# ── Chairperson: any faculty's schedule ──────
@schedule_bp.get("/<int:faculty_id>")
@login_required
@role_required("chairperson")
def get_faculty_schedule(faculty_id: int):
    faculty = db.session.get(User, faculty_id)
    if not faculty:
        return jsonify({"error": "Faculty not found."}), 404

    sem = _active_semester()
    if not sem:
        return jsonify({"schedule": [], "message": "No active semester."}), 200

    entries = (
        Schedule.query
        .filter_by(faculty_id=faculty_id, semester_id=sem.id)
        .order_by(Schedule.day, Schedule.time_start)
        .all()
    )

    return jsonify({
        "faculty":  faculty.to_dict(),
        "semester": sem.to_dict(),
        "schedule": [e.to_dict() for e in entries],
    }), 200


# ── Chairperson: persist a generated schedule ─
@schedule_bp.post("/publish")
@login_required
@role_required("chairperson")
def publish_schedule():
    """
    Called after the CP-SAT solver runs. Accepts the raw `assignments` array
    exactly as returned by POST /api/generate — pass it straight through,
    no reshaping needed on the frontend.

    Clears previous schedule for the active semester and inserts the new
    one. Each assignment covers a whole section's meeting pattern (e.g.
    preferred_days="MWF"), which gets expanded into one Schedule row per
    individual day. Room label and class_type (Lecture/Laboratory) are
    resolved server-side from room_id via the real Room table.

    Body:
    {
      "assignments": [
        {
          "faculty_id":       101,
          "course_code":      "COMP 016",
          "course_title":     "Web Development",
          "section_name":     "BSIT 3-3",
          "preferred_days":   "MWF",
          "time_start":       "07:30:00",
          "time_end":         "09:00:00",
          "room_id":          301,
          "units":            3
        },
        ...
      ]
    }
    """
    sem = _active_semester()
    if not sem:
        return jsonify({"error": "No active semester found."}), 400

    body        = request.get_json(silent=True) or {}
    assignments = body.get("assignments") or []

    if not assignments:
        return jsonify({"error": "No assignments provided."}), 400

    # Pre-fetch rooms once so we're not hitting the DB per-assignment
    rooms_by_id = {r.id: r for r in Room.query.all()}

    # Wipe existing schedule for this semester
    Schedule.query.filter_by(semester_id=sem.id).delete()

    inserted = 0
    for a in assignments:
        faculty_id = a.get("faculty_id")
        if not faculty_id:
            continue

        room = rooms_by_id.get(a.get("room_id"))
        room_label = f"{room.room_code} ({room.building})" if room else "TBA"
        class_type = room.room_type if room else "Lecture"

        # One assignment covers a whole section's meeting pattern (e.g. "MWF")
        # — Schedule stores one row per single meeting day, so expand it here.
        days = _expand_days(a.get("preferred_days", ""))

        for day in days:
            entry = Schedule(
                faculty_id   = faculty_id,
                semester_id  = sem.id,
                course_code  = a.get("course_code",  ""),
                course_title = a.get("course_title", ""),
                section_name = a.get("section_name", ""),
                class_type   = class_type,
                day          = day,
                time_start   = a.get("time_start", "07:30:00"),
                time_end     = a.get("time_end",   "09:00:00"),
                room         = room_label,
                units        = int(a.get("units", 3)),
            )
            db.session.add(entry)
            inserted += 1

    db.session.commit()
    return jsonify({
        "message":  f"Schedule published — {inserted} entries saved.",
        "semester": sem.to_dict(),
    }), 201
