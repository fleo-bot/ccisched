"""
app.py
------
Flask REST API for CCISched.

Endpoints
─────────
  Scheduling (CP-SAT solver):
    GET  /api/health          Server status + solver info
    POST /api/generate        Run RF → CP-SAT, return full assignment result
    GET  /api/faculty         Faculty list
    GET  /api/courses         Active course list
    GET  /api/semesters       All semesters (active one flagged)

  Database API (auth, profile, availability, notifications):
    Registered via blueprints — see routes/
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import pandas as pd
from flask import Flask, jsonify, request
from flask_cors import CORS

from database import configure_db, db
from models import User, Course, Room, Section, Semester
from rf_model import compute_scores
from cpsat_solver import solve, ORTOOLS_AVAILABLE
from routes.auth import login_required, role_required


# ──────────────────────────────────────────────
#  App factory
# ──────────────────────────────────────────────
def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

    # Frontend (Live Server, typically 127.0.0.1:5500) and backend (localhost:5000)
    # are different "sites" as far as cookies are concerned, even on the same
    # machine. Flask's default SameSite=Lax silently drops the session cookie
    # on this kind of cross-site fetch — SameSite=None + Secure=True lets it
    # through. Browsers treat loopback addresses (localhost/127.0.0.1) as a
    # trustworthy context, so Secure cookies still work here over plain HTTP.
    app.config["SESSION_COOKIE_SAMESITE"] = "None"
    app.config["SESSION_COOKIE_SECURE"]   = True

    # Database (SQLAlchemy + sessions)
    configure_db(app)

    # CORS — allow frontend on localhost:5500
    CORS(app, supports_credentials=True, origins=["http://127.0.0.1:5500", "http://localhost:5500"])

    # Register database API blueprints
    from routes.auth          import auth_bp
    from routes.profile       import profile_bp
    from routes.availability  import availability_bp
    from routes.review        import review_bp
    from routes.notifications import notifications_bp
    from routes.schedule      import schedule_bp
    from routes.courses       import courses_bp
    from routes.faculty       import faculty_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(availability_bp)
    app.register_blueprint(review_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(schedule_bp)
    app.register_blueprint(courses_bp)
    app.register_blueprint(faculty_bp)

    # Register legacy CSV-based scheduler routes (kept for backward compat)
    register_scheduler_routes(app)

    return app


# ──────────────────────────────────────────────
#  Legacy scheduler routes (CSV-based)
# ──────────────────────────────────────────────
def register_scheduler_routes(app: Flask):
    BASE_DIR = Path(__file__).parent
    DATA_DIR = BASE_DIR / "data"

    # Historical assignments remain CSV-based bootstrap training data for the
    # RF model — there's no live "confirmed past assignment" table yet, and
    # unlike faculty/courses/sections this doesn't represent current-state
    # institutional data that needs to stay in sync with chairperson edits.
    hist_df = pd.read_csv(DATA_DIR / "historical_assignments.csv")

    # ── Live DataFrame builders — query the DB fresh on every call, so
    #    anything a chairperson adds/edits via /api/manage/* is immediately
    #    reflected the next time a schedule is generated. ──
    def _faculty_df() -> pd.DataFrame:
        cols = ["faculty_id", "employee_number", "first_name", "last_name", "email",
                "specialization", "academic_rank", "highest_educ_attainment", "exp_years",
                "employment_type", "max_units", "preferred_courses", "preferred_days",
                "time_preference_mon", "time_preference_tue", "time_preference_wed",
                "time_preference_thu", "time_preference_fri", "time_preference_sat"]
        rows = User.query.filter_by(role="faculty").all()
        data = [{
            "faculty_id":              u.id,
            "employee_number":         u.employee_number,
            "first_name":              u.first_name,
            "last_name":               u.last_name,
            "email":                   u.email,
            "specialization":          u.specialization or "",
            "academic_rank":           u.academic_rank or "",
            "highest_educ_attainment": u.highest_educ_attainment or "",
            "exp_years":               u.exp_years or 0,
            "employment_type":         u.employment_type or "Full Time",
            "max_units":               u.max_units or 21,
            "preferred_courses":       u.preferred_courses or "",
            "preferred_days":          u.preferred_days or "",
            "time_preference_mon":     u.time_preference_mon or "Not available",
            "time_preference_tue":     u.time_preference_tue or "Not available",
            "time_preference_wed":     u.time_preference_wed or "Not available",
            "time_preference_thu":     u.time_preference_thu or "Not available",
            "time_preference_fri":     u.time_preference_fri or "Not available",
            "time_preference_sat":     u.time_preference_sat or "Not available",
        } for u in rows]
        return pd.DataFrame(data, columns=cols)

    def _courses_df(active_only: bool = True) -> pd.DataFrame:
        cols = ["course_id", "course_code", "course_title", "units", "is_active"]
        query = Course.query.filter_by(is_active=True) if active_only else Course.query
        rows = query.all()
        data = [{
            "course_id":    c.id,
            "course_code":  c.course_code,
            "course_title": c.course_title,
            "units":        c.units or 3,
            "is_active":    int(bool(c.is_active)),
        } for c in rows]
        return pd.DataFrame(data, columns=cols)

    def _rooms_df() -> pd.DataFrame:
        cols = ["room_id", "room_code", "building", "capacity", "room_type", "is_active"]
        rows = Room.query.filter_by(is_active=True).all()
        data = [{
            "room_id":   r.id,
            "room_code": r.room_code,
            "building":  r.building or "",
            "capacity":  r.capacity or 40,
            "room_type": r.room_type or "Lecture",
            "is_active": int(bool(r.is_active)),
        } for r in rows]
        return pd.DataFrame(data, columns=cols)

    def _sections_df(semester_id: int | None = None) -> pd.DataFrame:
        cols = ["section_id", "course_id", "section_name", "preferred_days",
                "preferred_time_start", "preferred_time_end", "room_id",
                "semester_id", "status"]
        query = Section.query.filter_by(semester_id=semester_id) if semester_id else Section.query
        rows = query.all()
        data = [{
            "section_id":           s.id,
            "course_id":            s.course_id,
            "section_name":         s.section_name,
            "preferred_days":       s.preferred_days or "MWF",
            "preferred_time_start": s.preferred_time_start.strftime("%H:%M:%S") if s.preferred_time_start else "07:30:00",
            "preferred_time_end":   s.preferred_time_end.strftime("%H:%M:%S") if s.preferred_time_end else "09:00:00",
            "room_id":              s.room_id or 0,
            "semester_id":          s.semester_id,
            "status":               s.status,
        } for s in rows]
        return pd.DataFrame(data, columns=cols)

    def _resolve_semester(academic_year: str, semester_term: str) -> Semester | None:
        """Match the requested (academic_year, semester) to a real Semester
        row; fall back to whichever semester is flagged active if there's no
        exact match, so generation still works with a slightly mismatched
        request rather than silently returning nothing."""
        exact = Semester.query.filter_by(
            academic_year=academic_year, semester_term=semester_term
        ).first()
        if exact:
            return exact
        return Semester.query.filter_by(is_active=True).first()

    def _room_label(room_id: int, rooms_df: pd.DataFrame) -> str:
        if not room_id:
            return "TBA"
        match = rooms_df[rooms_df["room_id"] == room_id]
        if match.empty:
            return "TBA"
        r = match.iloc[0]
        return f"{r['room_code']} ({r['building']})"

    def _group_by_faculty(assignments: list[dict], rooms_df: pd.DataFrame) -> list[dict]:
        grouped: dict[int, dict] = {}
        for row in assignments:
            fid = row["faculty_id"]
            if fid not in grouped:
                grouped[fid] = {
                    "id":              fid,
                    "name":            row["faculty_name"],
                    "employment_type": row["employment_type"],
                    "load":            0,
                    "max_units":       row["max_units"],
                    "rf_score":        row["rf_score"],
                    "courses":         [],
                    "course_details":  [],
                }
            entry = grouped[fid]
            entry["load"] += row["units"]
            time_label = f"{row['time_start'][:5]}–{row['time_end'][:5]}"
            entry["courses"].append(
                f"{row['course_code']} \u2013 {row['course_title']}"
                f"  [{row['preferred_days']} {time_label}]"
            )
            entry["course_details"].append({
                "code":          row["course_code"],
                "title":         row["course_title"],
                "section":       row["section_name"],
                "days":          row["preferred_days"],
                "time":          time_label,
                "room":          _room_label(row["room_id"], rooms_df),
                "units":         row["units"],
                "type":          "Lecture",
                "justification": row["justification"],
            })
        return list(grouped.values())

    def _group_by_department(assignments: list[dict]) -> list[dict]:
        cs_codes = {"CS101","CS102","CS103","CS201","CS202","CS301","CS401"}
        bscs_fac, bsit_fac = set(), set()
        for row in assignments:
            if row["course_code"] in cs_codes:
                bscs_fac.add(row["faculty_id"])
            else:
                bsit_fac.add(row["faculty_id"])
        return [
            {"department": "Bachelor of Science in Computer Science",
             "totalFaculty": len(bscs_fac), "status": "Completed"},
            {"department": "Bachelor of Science in Information Technology",
             "totalFaculty": len(bsit_fac), "status": "Completed"},
        ]

    def _dept_detail(faculty_view: list[dict]) -> dict:
        cs_codes = {"CS101","CS102","CS103","CS201","CS202","CS301","CS401"}
        bscs_faculty, bsit_faculty = [], []
        for f in faculty_view:
            cs_det = [d for d in f["course_details"] if d["code"] in cs_codes]
            it_det = [d for d in f["course_details"] if d["code"] not in cs_codes]
            justif = f["course_details"][0]["justification"] if f["course_details"] else ""
            if cs_det:
                bscs_faculty.append({
                    "name":         f["name"],
                    "type":         f["employment_type"],
                    "load":         f["load"],
                    "max":          f["max_units"],
                    "score":        f["rf_score"],
                    "department":   "Computer Science",
                    "justification": justif,
                    "courses": [
                        {"code": d["code"], "desc": d["title"].upper(),
                         "type": d["type"].upper(), "units": d["units"]}
                        for d in cs_det
                    ],
                })
            if it_det:
                bsit_faculty.append({
                    "name":         f["name"],
                    "type":         f["employment_type"],
                    "load":         f["load"],
                    "max":          f["max_units"],
                    "score":        f["rf_score"],
                    "department":   "Information Technology",
                    "justification": justif,
                    "courses": [
                        {"code": d["code"], "desc": d["title"].upper(),
                         "type": d["type"].upper(), "units": d["units"]}
                        for d in it_det
                    ],
                })
        return {
            "0": {"label": "BSCS", "title": "GENERATED PREVIEW: BSCS DEPARTMENT",
                  "faculty": bscs_faculty},
            "1": {"label": "BSIT", "title": "GENERATED PREVIEW: BSIT DEPARTMENT",
                  "faculty": bsit_faculty},
        }

    def _timetable_by_faculty(assignments: list[dict]) -> dict[int, list[dict]]:
        TIME_SLOTS = [
            (7*60+30,  9*60),    (9*60,    10*60+30), (10*60+30,12*60),
            (12*60,   13*60+30), (13*60+30,15*60),    (15*60,   16*60+30),
            (16*60+30,18*60),    (18*60,   19*60+30),
        ]
        DAY_EXPAND = {
            "MWF": ["Monday","Wednesday","Friday"],
            "TTh": ["Tuesday","Thursday"],
            "Sat": ["Saturday"],
            "MTh": ["Monday","Thursday"],
            "MW":  ["Monday","Wednesday"],
            "TF":  ["Tuesday","Friday"],
        }
        result: dict[int, list[dict]] = {}
        for row in assignments:
            fid   = row["faculty_id"]
            start = int(row["time_start"].split(":")[0]) * 60 + int(row["time_start"].split(":")[1])
            col = 0
            for i, (s, e) in enumerate(TIME_SLOTS):
                if abs(start - s) <= 30:
                    col = i
                    break
            days = DAY_EXPAND.get(row["preferred_days"], ["Monday"])
            result.setdefault(fid, [])
            for day in days:
                result[fid].append({
                    "day":     day,
                    "col":     col,
                    "code":    row["course_code"],
                    "name":    row["course_title"],
                    "section": row["section_name"],
                })
        return result

    # ── Routes ──
    @app.get("/")
    def index():
        return {"status": "CCISched backend running", "database": "connected"}, 200

    @app.get("/api/health")
    def health():
        active_sem = Semester.query.filter_by(is_active=True).first()
        return jsonify({
            "status":            "ok",
            "ortools_available": ORTOOLS_AVAILABLE,
            "solver_mode":       "CP-SAT" if ORTOOLS_AVAILABLE else "Greedy fallback",
            "faculty_count":     User.query.filter_by(role="faculty").count(),
            "course_count":      Course.query.filter_by(is_active=True).count(),
            "section_count":     Section.query.count(),
            "room_count":        Room.query.filter_by(is_active=True).count(),
            "history_rows":      len(hist_df),
            "active_semester":   active_sem.to_dict() if active_sem else {},
        })

    @app.post("/api/generate")
    @login_required
    @role_required("chairperson")
    def generate():
        body          = request.get_json(silent=True) or {}
        academic_year = body.get("academic_year", "2025-2026")
        semester      = body.get("semester", "1st")

        target_sem = _resolve_semester(academic_year, semester)
        if not target_sem:
            return jsonify({"error": "No matching or active semester found. "
                                      "Add one in the database first."}), 400

        faculty_df = _faculty_df()
        courses_df = _courses_df(active_only=True)
        rooms_df   = _rooms_df()
        sections_df = _sections_df(semester_id=target_sem.id)

        if faculty_df.empty:
            return jsonify({"error": "No faculty accounts found. Add faculty before generating."}), 400
        if sections_df.empty:
            return jsonify({"error": f"No sections found for {target_sem.academic_year} "
                                      f"{target_sem.semester_term} semester. Add sections first."}), 400

        # ── Layer 1: Random Forest — predicts faculty↔section suitability
        #    scores from historical assignment patterns + rule-based features ──
        scores = compute_scores(faculty_df, sections_df, courses_df, hist_df)

        # ── Layer 2: CP-SAT — enforces hard constraints (load limits, day
        #    availability, no double-booking) while maximising RF scores ──
        assignments = solve(faculty_df, sections_df, courses_df, rooms_df, scores)

        faculty_view = _group_by_faculty(assignments, rooms_df)
        dept_summary = _group_by_department(assignments)
        dept_det     = _dept_detail(faculty_view)
        timetable    = _timetable_by_faculty(assignments)

        return jsonify({
            "academic_year": target_sem.academic_year,
            "semester":      target_sem.semester_term,
            "solver_mode":   "CP-SAT" if ORTOOLS_AVAILABLE else "Greedy",
            "faculty_data":  faculty_view,
            "dept_summary":  dept_summary,
            "dept_detail":   dept_det,
            "timetable":     timetable,
            "assignments":   assignments,
        })

    @app.get("/api/faculty")
    def get_faculty():
        cols = ["faculty_id","employee_number","first_name","last_name","email",
                "specialization","academic_rank","employment_type",
                "max_units","exp_years","preferred_courses","preferred_days"]
        return jsonify(_faculty_df()[cols].to_dict(orient="records"))

    @app.get("/api/courses")
    def get_courses():
        return jsonify(_courses_df(active_only=True).to_dict(orient="records"))

    @app.get("/api/sections")
    def get_sections():
        sections_df = _sections_df()
        courses_df  = _courses_df(active_only=False)
        rooms_df    = _rooms_df()
        merged = sections_df.merge(
            courses_df[["course_id","course_code","course_title"]],
            on="course_id", how="left"
        )
        merged["room_label"] = merged["room_id"].apply(lambda rid: _room_label(rid, rooms_df))
        return jsonify(merged.to_dict(orient="records"))

    @app.get("/api/semesters")
    def get_semesters():
        semesters = Semester.query.order_by(Semester.id.desc()).all()
        return jsonify([s.to_dict() for s in semesters])

    @app.get("/api/rooms")
    def get_rooms():
        return jsonify(_rooms_df().to_dict(orient="records"))


# ──────────────────────────────────────────────
#  Entry point
# ──────────────────────────────────────────────
if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  CCISched backend  →  http://localhost:{port}")
    print(f"  Solver: {'CP-SAT (OR-Tools)' if ORTOOLS_AVAILABLE else 'Greedy fallback (install ortools)'}\n")
    app.run(host="0.0.0.0", port=port, debug=True)
