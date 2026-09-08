# CCISched — Change Log

Summary of everything changed while migrating the backend from PostgreSQL to
MySQL and fixing the bugs that surfaced along the way.

## 1. Database: PostgreSQL → MySQL

- `backend/requirements.txt` — replaced `psycopg2-binary` with `PyMySQL`
- `backend/database.py` — connection string now expects `mysql+pymysql://...`;
  added `charset=utf8mb4` so names/text with accents or emoji save correctly
  (MySQL defaults to `latin1` unless told otherwise, unlike Postgres)
- `backend/.env.example`, `backend/DATABASE_SETUP.md`, `SETUP_GUIDE.md`,
  `FRONTEND_INTEGRATION_COMPLETE.md` — install/setup instructions and example
  connection strings updated to MySQL

## 2. Fixed: ambiguous foreign key crash on startup

`AvailabilitySubmission` has two foreign keys to `users` (`faculty_id` and
`reviewed_by`). `User.submissions` didn't say which one to join on, so
SQLAlchemy refused to start (`AmbiguousForeignKeysError`).

- `backend/models.py` — added `foreign_keys="AvailabilitySubmission.faculty_id"`
  to the `submissions` relationship (matches the pattern already used for
  `notifications`)

## 3. Fixed: duplicate faculty emails crashing the seed

The original `faculty.csv` had 3 pairs of different people sharing one email
address, which violated the `email` UNIQUE constraint during seeding.

- `backend/init_db.py` — added `_dedupe_emails()` as a safety net (auto-
  renumbers any future collisions instead of crashing)
- Faculty data was later replaced with a corrected CSV that has zero
  duplicate emails to begin with

## 4. Fixed: `.env` was never actually loaded

`python-dotenv` was listed as a dependency but `load_dotenv()` was never
called anywhere — `DATABASE_URL` only worked if manually set in the current
terminal session, and silently fell back to a local SQLite file otherwise.
This was the root cause of a long chain of confusing symptoms: "table
doesn't exist," "database stays empty after seeding," etc.

- `backend/app.py` and `backend/database.py` — both now call
  `load_dotenv(Path(__file__).parent / ".env")` explicitly, so `.env` loads
  regardless of the working directory the app is launched from

**Note:** `.env` is git-ignored and never ships inside the project zip (it
holds your DB password). Every time you unzip a fresh copy into a new
folder, you need to recreate `backend/.env` there.

## 5. Fixed: logged in successfully, then immediately logged back out

Login returned `200`, but the very next `/api/auth/me` check returned `401`.
Browsers treat `localhost` and `127.0.0.1` as different "sites" for cookie
purposes, so Flask's default session cookie setting (`SameSite=Lax`) was
being silently dropped on that cross-origin follow-up request.

- `backend/app.py` — set `SESSION_COOKIE_SAMESITE = "None"` and
  `SESSION_COOKIE_SECURE = True` (loopback addresses are treated as a
  trustworthy context by browsers, so this still works over plain HTTP)

## 6. Removed: mock login fallback that masked real errors

`login.js` had a leftover dev-era `mockUsers` dictionary. Any real backend
error (including a simple wrong password) was silently swallowed and
retried against fake local credentials, which — if matched — faked a
successful login in the browser without ever creating a real server
session. This is what caused the original "kicked out right after
logging in" symptom.

- `backend/src/scripts/login.js` — removed the `mockUsers` fallback entirely;
  real backend responses are now trusted directly
- Updated the login page's placeholder hint text to real, working example
  accounts instead of fictional ones

## 7. Added: demo accounts + normalized faculty passwords

- `backend/init_db.py` — added `seed_demo_accounts()`: creates/updates a
  small set of easy-to-remember accounts every time `init_db.py` runs:

  | Role | Email | Password |
  |---|---|---|
  | Chairperson | `chairperson@pup.edu.ph` | `admin123` |
  | Chairperson | `demo.chair@pup.edu.ph` | `chair123` |
  | Faculty | `faculty@pup.edu.ph` | `faculty123` |
  | Faculty | `msantos@pup.edu.ph` | `faculty123` |

- Real chairperson account unchanged: `chair@pup.edu.ph` / `chair1234`
- `faculty.csv` replaced with a corrected version (50 faculty, no duplicate
  emails)
- Faculty passwords normalized to lowercase/no-dash employee numbers, e.g.
  `bgarcia@pup.edu.ph` → `emp2024001`
- `seed_users()` converted from "seed once and skip" to an upsert: it now
  updates existing accounts to match the CSV every time you re-run
  `init_db.py`, instead of only seeding an empty table once

## 8. Fixed: dashboard/profile always showed "Maria Santos" / "Christian Rey"

Two compounding bugs:
- Scripts read the logged-in user before the async login check had
  finished, so the value was always empty at that point
- Even when it wasn't empty, some code targeted DOM element IDs that don't
  exist in the HTML (e.g. `#userGreeting`), or simply never touched the
  display elements at all
- `faculty-schedule.js` was actively *re-writing* the name to the literal
  string `'Maria Santos'` on every load — worse than a static placeholder

Fix: `auth-check.js` now fires an `authReady` event once the real user is
confirmed; dependent scripts listen for it instead of racing ahead.

- `backend/../src/scripts/auth-check.js` — dispatches `authReady`
- `faculty-dashboard.js`, `chairperson-dashboard.js` — now correctly update
  the greeting banner and profile panel with the real logged-in name/role
  (chairperson dashboard previously had **no** wiring for this at all)
- `faculty-profile.js` — now also updates the profile page header name/role
  (previously only populated the edit form fields, not the header); made
  defensive against pages missing some of its expected fields
- `faculty-schedule.js`, `teaching-assignments.js` — now show the real
  logged-in name instead of a hardcoded string

## 9. Fixed: wrong-role portal access wasn't blocked

Only 4 of 18 chairperson pages (`dashboard`, `notifications`, `profile`,
`view-submissions`) had any login/role check at all. The other 14
(`courses`, `faculty`, `schedule`, `assign-courses`, etc.) had **zero**
protection — no login required, no role check.

- Added `api.js` + `auth-check.js` to all 14 previously-unprotected
  chairperson pages
- `auth-check.js` — role-mismatch redirects now go to
  `login.html?error=access_denied&role=...` instead of a silent bounce
- `login.js` — displays *"Access denied: that account does not have
  permission to view that portal"* when redirected back this way

## 10. Fixed: chairperson-login-with-faculty-credentials silently redirected

Selecting the "Chairperson" tab and logging in with valid **faculty**
credentials succeeded and just quietly redirected to the faculty dashboard,
instead of rejecting the mismatch outright.

- `login.js` — now compares the account's real role (from the backend)
  against the selected tab; on a mismatch, logs the just-created session
  back out immediately and shows: *"That account is not a [role] account.
  Please switch tabs above, or use the correct portal's credentials."*

## Known remaining gaps (not yet fixed)

- **`chairperson/profile.html`'s edit form is a static mockup** — none of
  its input fields have IDs, a few fields (Middle Name, Age) don't exist in
  the database model at all, and saving doesn't work. It no longer throws
  an error on page load, but editing is still non-functional.
- **Several chairperson pages still show mock data for other people** —
  e.g. hardcoded sample rows in the faculty roster, schedule, and
  submission-detail pages (`chairperson-schedule.js`,
  `chairperson-faculty.js`, `assignment-detail.js`, `submission-detail.js`).
  This is separate from the "own profile" bug above — it's about pages
  never having been wired to the real API in the first place.
