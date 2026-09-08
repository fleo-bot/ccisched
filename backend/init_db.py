"""
init_db.py
----------
One-time setup script.  Run once to:
  1. Create all tables
  2. Seed semesters from the existing CSV
  3. Create a default chairperson account
  4. Seed faculty accounts from faculty.csv

Usage:
    cd backend
    python init_db.py
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

from werkzeug.security import generate_password_hash
import pandas as pd

# ── Make sure the backend package is importable ──
sys.path.insert(0, str(Path(__file__).parent))

from app import create_app
from database import db
from models import User, Semester, Course, Room, Section


def seed_semesters(app):
    DATA_DIR = Path(__file__).parent / "data"
    df = pd.read_csv(DATA_DIR / "Sememster.csv")

    with app.app_context():
        if Semester.query.count() > 0:
            print("  [skip] Semesters already seeded.")
            return

        for _, row in df.iterrows():
            sem = Semester(
                id            = int(row["semester_id"]),
                academic_year = str(row["academic_year"]),
                semester_term = str(row["semester_term"]),
                start_date    = _parse_date(str(row["start_date"])),
                end_date      = _parse_date(str(row["end_date"])),
                max_units_per_faculty = int(row["max_units_per_faculty"]),
                is_active     = bool(int(row["is_active"])),
            )
            db.session.add(sem)

        db.session.commit()
        print(f"  [ok] Seeded {df.shape[0]} semesters.")


def _normalize_password(employee_number: str) -> str:
    """
    Default faculty password derived from employee_number, normalized to be
    easy to type: lowercase, dashes removed. EMP-2024-001 -> emp2024001
    """
    return employee_number.strip().lower().replace("-", "")


def _dedupe_emails(df):
    """
    faculty.csv has a few rows where two different people share the same
    email (e.g. two 'Paolo Garcia' entries both mapped to pgarcia@pup.edu.ph).
    The `email` column is UNIQUE, so we disambiguate repeats by appending a
    number, keeping the first occurrence untouched: pgarcia@pup.edu.ph,
    pgarcia2@pup.edu.ph, pgarcia3@pup.edu.ph, ...
    """
    seen = {}
    new_emails = []
    for email in df["email"]:
        email = str(email).strip()
        if email not in seen:
            seen[email] = 1
            new_emails.append(email)
        else:
            seen[email] += 1
            user, domain = email.split("@", 1)
            new_emails.append(f"{user}{seen[email]}@{domain}")
    dupes = {e: c for e, c in seen.items() if c > 1}
    if dupes:
        print(f"  [warn] Found duplicate emails in faculty.csv, renumbered: {dupes}")
    df = df.copy()
    df["email"] = new_emails
    return df


def seed_users(app):
    DATA_DIR = Path(__file__).parent / "data"
    df = pd.read_csv(DATA_DIR / "faculty.csv")
    df = _dedupe_emails(df)

    with app.app_context():
        # ── Default chairperson (create-or-update) ──
        chair = User.query.filter_by(email="chair@pup.edu.ph").first()
        if chair is None:
            chair = User(employee_number="EMP-2024-000", email="chair@pup.edu.ph")
            db.session.add(chair)
        chair.first_name              = "Admin"
        chair.last_name               = "Chairperson"
        chair.password_hash           = generate_password_hash("chair1234")
        chair.role                    = "chairperson"
        chair.specialization          = "Department Administration"
        chair.academic_rank           = "Department Chair"
        chair.highest_educ_attainment = "PhD"
        chair.exp_years               = 10
        chair.employment_type         = "Full Time"
        chair.max_units               = 0
        chair.avatar                  = chair.avatar or "female"

        # ── Faculty from CSV (create-or-update, keyed by faculty_id) ──
        created, updated = 0, 0
        for _, row in df.iterrows():
            fid = int(row["faculty_id"])
            user = User.query.get(fid)
            is_new = user is None
            if is_new:
                user = User(id=fid)
                db.session.add(user)

            user.employee_number         = str(row["employee_number"])
            user.first_name              = str(row["first_name"])
            user.last_name               = str(row["last_name"])
            user.email                   = str(row["email"])
            # Default password = normalized employee_number, e.g. emp2024001
            user.password_hash           = generate_password_hash(_normalize_password(str(row["employee_number"])))
            user.role                    = "faculty"
            user.specialization          = str(row.get("specialization", ""))
            user.academic_rank           = str(row.get("academic_rank", ""))
            user.highest_educ_attainment = str(row.get("highest_educ_attainment", ""))
            user.exp_years               = int(row.get("exp_years", 0))
            user.employment_type         = str(row.get("employment_type", "Full Time"))
            user.max_units               = int(row.get("max_units", 21))
            user.preferred_courses       = str(row.get("preferred_courses", ""))
            user.preferred_days          = str(row.get("preferred_days", ""))
            user.time_preference_mon     = str(row.get("time_preference_mon", "Not available"))
            user.time_preference_tue     = str(row.get("time_preference_tue", "Not available"))
            user.time_preference_wed     = str(row.get("time_preference_wed", "Not available"))
            user.time_preference_thu     = str(row.get("time_preference_thu", "Not available"))
            user.time_preference_fri     = str(row.get("time_preference_fri", "Not available"))
            user.time_preference_sat     = str(row.get("time_preference_sat", "Not available"))
            user.avatar                  = user.avatar or "female"

            created += is_new
            updated += (not is_new)

        db.session.commit()
        print(f"  [ok] Chairperson + faculty synced: {created} created, {updated} updated.")
        print("  [info] Default faculty password = normalized employee number, e.g. emp2024001")
        print("  [info] Chairperson password     = chair1234")


def seed_demo_accounts(app):
    """
    A handful of easy-to-remember demo accounts matching the hint text
    shown on the login page. Unlike seed_users, this runs every time
    init_db.py is executed and upserts (create-or-update) so these
    always work, even on a database that was already seeded before.
    """
    demo_accounts = [
        dict(email="chairperson@pup.edu.ph", password="admin123",   role="chairperson",
             first_name="Admin",         last_name="Chairperson", employee_number="DEMO-CHAIR-01"),
        dict(email="demo.chair@pup.edu.ph",  password="chair123",   role="chairperson",
             first_name="Christian Rey", last_name="Dela Cruz",   employee_number="DEMO-CHAIR-02"),
        dict(email="faculty@pup.edu.ph",     password="faculty123", role="faculty",
             first_name="Test",          last_name="Faculty",     employee_number="DEMO-FAC-01"),
        dict(email="msantos@pup.edu.ph",     password="faculty123", role="faculty",
             first_name="Maria",         last_name="Santos",      employee_number="DEMO-FAC-02"),
    ]

    with app.app_context():
        for acc in demo_accounts:
            user = User.query.filter_by(email=acc["email"]).first()
            if user:
                user.password_hash = generate_password_hash(acc["password"])
                user.role          = acc["role"]
            else:
                user = User(
                    employee_number         = acc["employee_number"],
                    first_name              = acc["first_name"],
                    last_name               = acc["last_name"],
                    email                   = acc["email"],
                    password_hash           = generate_password_hash(acc["password"]),
                    role                    = acc["role"],
                    specialization          = "Demo Account",
                    academic_rank           = "N/A",
                    highest_educ_attainment = "N/A",
                    exp_years               = 0,
                    employment_type         = "Full Time",
                    max_units               = 0 if acc["role"] == "chairperson" else 21,
                    avatar                  = "female",
                )
                db.session.add(user)
        db.session.commit()
        print("  [ok] Demo accounts ready:")
        for acc in demo_accounts:
            print(f"       {acc['email']} / {acc['password']}  ({acc['role']})")


def _parse_date(val: str):
    """Parse M/D/YY or YYYY-MM-DD → date object."""
    from datetime import datetime
    for fmt in ("%m/%d/%y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(val.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _parse_time(val: str):
    """Parse HH:MM:SS or HH:MM → time object."""
    from datetime import datetime
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(str(val).strip(), fmt).time()
        except ValueError:
            continue
    return None


def seed_courses_rooms_sections(app):
    """
    Courses/Rooms/Sections previously only existed as static CSV files read
    by the /api/generate solver — there was no real database table backing
    them, so nothing added/edited via the UI could ever persist. This seeds
    real DB rows from those same CSVs (upsert-style, like seed_users), so
    the new Course CRUD API has real data to start from.
    """
    DATA_DIR = Path(__file__).parent / "data"
    courses_df  = pd.read_csv(DATA_DIR / "courses.csv")
    rooms_df    = pd.read_csv(DATA_DIR / "rooms.csv")
    sections_df = pd.read_csv(DATA_DIR / "sections.csv")

    with app.app_context():
        # ── Courses ──
        for _, row in courses_df.iterrows():
            cid = int(row["course_id"])
            course = db.session.get(Course, cid)
            if course is None:
                course = Course(id=cid)
                db.session.add(course)
            course.course_code    = str(row["course_code"])
            course.course_title   = str(row["course_title"])
            course.units          = int(row.get("units", 3))
            course.year_level     = str(row.get("year_level", ""))
            course.department     = str(row.get("department", "CCIS"))
            course.is_active      = bool(int(row.get("is_active", 1)))
        db.session.commit()

        # ── Rooms ──
        for _, row in rooms_df.iterrows():
            rid = int(row["room_id"])
            room = db.session.get(Room, rid)
            if room is None:
                room = Room(id=rid)
                db.session.add(room)
            room.room_code    = str(row["room_code"])
            room.building     = str(row.get("building", ""))
            room.floor_number = int(row["floor_number"]) if str(row.get("floor_number", "")).strip() not in ("", "nan") else None
            room.capacity     = int(row.get("capacity", 40))
            room.room_type    = str(row.get("room_type", "Lecture"))
            room.is_active    = bool(int(row.get("is_active", 1)))
        db.session.commit()

        # ── Sections ──
        for _, row in sections_df.iterrows():
            sid = int(row["section_id"])
            section = db.session.get(Section, sid)
            if section is None:
                section = Section(id=sid)
                db.session.add(section)
            section.course_id            = int(row["course_id"])
            section.section_name         = str(row["section_name"])
            section.preferred_days       = str(row.get("preferred_days", ""))
            section.preferred_time_start = _parse_time(row.get("preferred_time_start", ""))
            section.preferred_time_end   = _parse_time(row.get("preferred_time_end", ""))
            room_id = row.get("room_id")
            section.room_id     = int(room_id) if str(room_id).strip() not in ("", "nan") else None
            section.semester_id = int(row["semester_id"])
            section.status      = str(row.get("status", "open"))
        db.session.commit()

        print(f"  [ok] Synced {len(courses_df)} courses, {len(rooms_df)} rooms, "
              f"{len(sections_df)} sections.")


def main():
    app = create_app()

    with app.app_context():
        print("\n[init_db] Creating tables…")
        db.create_all()
        print("[init_db] Tables created.\n")

    print("[init_db] Seeding data…")
    seed_semesters(app)
    seed_courses_rooms_sections(app)
    seed_users(app)
    seed_demo_accounts(app)
    print("\n[init_db] Done. You can now run:  python app.py\n")


if __name__ == "__main__":
    main()
