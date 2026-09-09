"""
routes/courses.py
------------------
Course/Room/Section/Semester management — chairperson-only writes, both
roles can read.

GET    /api/manage/courses          — list all courses
POST   /api/manage/courses          — add a course                (chairperson)
PUT    /api/manage/courses/<id>     — edit a course                (chairperson)
DELETE /api/manage/courses/<id>     — delete a course              (chairperson)

GET    /api/manage/rooms            — list all rooms

GET    /api/manage/sections?course_id=<id>  — list sections (optionally filtered by course)
POST   /api/manage/sections         — add a section                (chairperson)
PUT    /api/manage/sections/<id>    — edit a section                (chairperson)
DELETE /api/manage/sections/<id>    — delete a section              (chairperson)

GET    /api/manage/semesters        — list semesters (for dropdowns)
"""

from __future__ import annotations

from datetime import datetime

from flask import Blueprint, jsonify, request

from database import db
from models import Course, Room, Section, Semester
from routes.auth import login_required, role_required

courses_bp = Blueprint("courses", __name__, url_prefix="/api/manage")


def _parse_time(val):
    """Accept 'HH:MM' or 'HH:MM:SS' from the frontend; return a time object."""
    if not val:
        return None
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(str(val).strip(), fmt).time()
        except ValueError:
            continue
    return None


# ── Courses ────────────────────────────────────────────────
@courses_bp.get("/courses")
@login_required
def list_courses():
    courses = Course.query.order_by(Course.course_code).all()
    return jsonify([c.to_dict() for c in courses]), 200


@courses_bp.post("/courses")
@login_required
@role_required("chairperson")
def add_course():
    body = request.get_json(silent=True) or {}
    code  = (body.get("code")  or "").strip()
    title = (body.get("title") or "").strip()

    if not code or not title:
        return jsonify({"error": "Course code and title are required."}), 400

    if Course.query.filter_by(course_code=code).first():
        return jsonify({"error": f"Course code '{code}' already exists."}), 409

    course = Course(
        course_code    = code,
        course_title   = title,
        units          = body.get("units") or 3,
        year_level     = body.get("yearLevel"),
        classification = body.get("classification"),
        description    = body.get("description"),
    )
    db.session.add(course)
    db.session.commit()
    return jsonify({"message": "Course added.", "course": course.to_dict()}), 201


@courses_bp.put("/courses/<int:course_id>")
@login_required
@role_required("chairperson")
def edit_course(course_id: int):
    course = db.session.get(Course, course_id)
    if not course:
        return jsonify({"error": "Course not found."}), 404

    body = request.get_json(silent=True) or {}
    code  = (body.get("code")  or "").strip()
    title = (body.get("title") or "").strip()

    if not code or not title:
        return jsonify({"error": "Course code and title are required."}), 400

    dupe = Course.query.filter(Course.course_code == code, Course.id != course_id).first()
    if dupe:
        return jsonify({"error": f"Course code '{code}' already exists."}), 409

    course.course_code    = code
    course.course_title   = title
    course.units          = body.get("units") or course.units
    course.year_level     = body.get("yearLevel", course.year_level)
    course.classification = body.get("classification", course.classification)
    course.description    = body.get("description", course.description)

    db.session.commit()
    return jsonify({"message": "Course updated.", "course": course.to_dict()}), 200


@courses_bp.delete("/courses/<int:course_id>")
@login_required
@role_required("chairperson")
def delete_course(course_id: int):
    course = db.session.get(Course, course_id)
    if not course:
        return jsonify({"error": "Course not found."}), 404

    db.session.delete(course)
    db.session.commit()
    return jsonify({"message": "Course removed."}), 200


# ── Rooms (read-only for now) ────────────────────────────────
@courses_bp.get("/rooms")
@login_required
def list_rooms():
    rooms = Room.query.order_by(Room.room_code).all()
    return jsonify([r.to_dict() for r in rooms]), 200


# ── Sections ──────────────────────────────────────────────
@courses_bp.get("/sections")
@login_required
def list_sections():
    course_id = request.args.get("course_id", type=int)
    query = Section.query
    if course_id:
        query = query.filter_by(course_id=course_id)
    sections = query.order_by(Section.section_name).all()
    return jsonify([s.to_dict() for s in sections]), 200


@courses_bp.post("/sections")
@login_required
@role_required("chairperson")
def add_section():
    body = request.get_json(silent=True) or {}
    course_id   = body.get("course_id")
    section_name = (body.get("section_name") or "").strip()
    semester_id = body.get("semester_id")

    if not course_id or not section_name or not semester_id:
        return jsonify({"error": "course_id, section_name, and semester_id are required."}), 400

    if not db.session.get(Course, course_id):
        return jsonify({"error": "Course not found."}), 404
    if not db.session.get(Semester, semester_id):
        return jsonify({"error": "Semester not found."}), 404

    room_id = body.get("room_id") or None
    if room_id and not db.session.get(Room, room_id):
        return jsonify({"error": "Room not found."}), 404

    section = Section(
        course_id            = course_id,
        section_name         = section_name,
        preferred_days       = body.get("preferred_days", ""),
        preferred_time_start = _parse_time(body.get("preferred_time_start")),
        preferred_time_end   = _parse_time(body.get("preferred_time_end")),
        room_id              = room_id,
        semester_id          = semester_id,
        status               = body.get("status", "open"),
    )
    db.session.add(section)
    db.session.commit()
    return jsonify({"message": "Section added.", "section": section.to_dict()}), 201


@courses_bp.put("/sections/<int:section_id>")
@login_required
@role_required("chairperson")
def edit_section(section_id: int):
    section = db.session.get(Section, section_id)
    if not section:
        return jsonify({"error": "Section not found."}), 404

    body = request.get_json(silent=True) or {}
    section_name = (body.get("section_name") or "").strip()
    if not section_name:
        return jsonify({"error": "section_name is required."}), 400

    room_id = body.get("room_id") or None
    if room_id and not db.session.get(Room, room_id):
        return jsonify({"error": "Room not found."}), 404

    semester_id = body.get("semester_id")
    if semester_id and not db.session.get(Semester, semester_id):
        return jsonify({"error": "Semester not found."}), 404

    section.section_name         = section_name
    section.preferred_days       = body.get("preferred_days", section.preferred_days)
    section.preferred_time_start = _parse_time(body.get("preferred_time_start")) or section.preferred_time_start
    section.preferred_time_end   = _parse_time(body.get("preferred_time_end")) or section.preferred_time_end
    section.room_id              = room_id
    section.semester_id          = semester_id or section.semester_id
    section.status               = body.get("status", section.status)

    db.session.commit()
    return jsonify({"message": "Section updated.", "section": section.to_dict()}), 200


@courses_bp.delete("/sections/<int:section_id>")
@login_required
@role_required("chairperson")
def delete_section(section_id: int):
    section = db.session.get(Section, section_id)
    if not section:
        return jsonify({"error": "Section not found."}), 404

    db.session.delete(section)
    db.session.commit()
    return jsonify({"message": "Section removed."}), 200


# ── Section assignment coverage (real data, joined against published
#    Schedule entries) ──
@courses_bp.get("/coverage")
@login_required
def section_coverage():
    from models import Schedule

    semester_id = request.args.get("semester_id", type=int)
    semester = db.session.get(Semester, semester_id) if semester_id else \
               Semester.query.filter_by(is_active=True).first()

    if not semester:
        return jsonify({"courses": [], "totals": {
            "total_courses": 0, "total_sections": 0, "sections_covered": 0
        }}), 200

    # Build a lookup of (course_code, section_name) -> faculty full name from
    # published Schedule rows for this semester. Schedule doesn't reference
    # Section by ID, so this string-key match is how the two connect.
    scheduled = Schedule.query.filter_by(semester_id=semester.id).all()
    assigned_lookup = {}
    for s in scheduled:
        key = (s.course_code, s.section_name)
        if key not in assigned_lookup:
            assigned_lookup[key] = f"{s.faculty.first_name} {s.faculty.last_name}" if s.faculty else None

    courses = Course.query.filter_by(is_active=True).order_by(Course.course_code).all()
    result = []
    total_sections = 0
    total_covered  = 0

    for course in courses:
        sections = Section.query.filter_by(course_id=course.id, semester_id=semester.id).all()
        sec_list = []
        covered = 0
        for sec in sections:
            assigned_to = assigned_lookup.get((course.course_code, sec.section_name))
            if assigned_to:
                covered += 1
            sec_list.append({"label": sec.section_name, "assignedTo": assigned_to})

        total_sections += len(sections)
        total_covered  += covered

        result.append({
            "code":            course.course_code,
            "name":            course.course_title,
            "totalSections":   len(sections),
            "coveredSections": covered,
            "sections":        sec_list,
        })

    return jsonify({
        "courses": result,
        "totals": {
            "total_courses":    len(courses),
            "total_sections":   total_sections,
            "sections_covered": total_covered,
        },
    }), 200


# ── Semesters (read-only, real DB — for dropdowns) ───────────
@courses_bp.get("/semesters")
@login_required
def list_semesters():
    semesters = Semester.query.order_by(Semester.id.desc()).all()
    return jsonify([s.to_dict() for s in semesters]), 200
