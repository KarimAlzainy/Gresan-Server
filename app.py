"""
Gresan Workspace System - Flask Backend
========================================
Google Sheets tabs used:
  'Data Base'    → Code | Name | Phone number | international | Whatsapp |
                   Birthday | JOIN DATE | Career | notes | SURVEYED... | ACTIVE? | REFERALS | شهر3
  'Daily 26 (3)' → Column1 | code | Name(formula) | Start time | End time |
                   Duration(formula) | Time price | Snaks | Price Snacks |
                   Other Prices | Notes | Total(formula) | FL | PAID? | Digital? | Employee | Equipment

API routes:
  GET  /ping           → health check
  POST /signup         → register → append to Data Base → return code
  POST /signin         → lookup code → append session row to Daily → return user info
  GET  /user/<code>    → fetch user info by code (for homepage restore)
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from oauth2client.service_account import ServiceAccountCredentials
import gspread
import re
from datetime import datetime

app = Flask(__name__)
CORS(app)

# ─── Google Sheets config ────────────────────────────────────────────────────
SHEET_NAME = "Copy of Copy of Gresan System (External)"
DB_TAB     = "Data Base"
DAILY_TAB  = "Daily 26 (3)"

SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

db_sheet    = None
daily_sheet = None

try:
    creds       = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", SCOPE)
    client      = gspread.authorize(creds)
    spreadsheet = client.open(SHEET_NAME)
    db_sheet    = spreadsheet.worksheet(DB_TAB)
    daily_sheet = spreadsheet.worksheet(DAILY_TAB)
    print("✅  Google Sheets connected.")
except Exception as e:
    print(f"❌  Google Sheets Error: {e}")


# ─── Helpers ─────────────────────────────────────────────────────────────────

def format_egypt_phone(raw: str) -> str:
    """Normalise any Egyptian phone input → +20XXXXXXXXXX."""
    clean = re.sub(r"[^\d+]", "", str(raw))
    if clean.startswith("+20"): return clean
    if clean.startswith("20"):  return "+" + clean
    if clean.startswith("01"):  return "+20" + clean[1:]
    if clean.startswith("1") and len(clean) == 10: return "+20" + clean
    return clean


def get_all_db_rows() -> list[dict]:
    """
    Read Data Base sheet by column position (safe even though A1 holds a number, not a label).
    Positions (0-based): 0=Code 1=Name 2=Phone 7=Career 8=notes
    """
    try:
        all_vals = db_sheet.get_all_values()   # list of lists; row 0 = header
    except Exception as e:
        print(f"DB read error: {e}")
        return []

    rows = []
    for row in all_vals[1:]:          # skip header row
        if not any(row):
            continue
        rows.append({
            "code":   (row[0]  if len(row) > 0 else "").strip(),
            "name":   (row[1]  if len(row) > 1 else "").strip(),
            "phone":  (row[2]  if len(row) > 2 else "").strip(),
            "career": (row[7]  if len(row) > 7 else "").strip(),
            "notes":  (row[8]  if len(row) > 8 else "").strip(),
        })
    return rows


def find_by_phone(phone: str) -> dict | None:
    return next((r for r in get_all_db_rows() if r["phone"] == phone), None)


def find_by_code(code) -> dict | None:
    return next((r for r in get_all_db_rows() if str(r["code"]) == str(code)), None)


def find_first_empty_db_row() -> int:
    """
    The Data Base sheet has pre-filled codes in col A but empty names in col B.
    Scan from row 2 downward and return the first row number where col B (Name) is empty.
    This means we WRITE INTO the existing template row instead of appending at the bottom.
    Row numbers are 1-based (Google Sheets API style).
    """
    try:
        all_vals = db_sheet.get_all_values()
        for i, row in enumerate(all_vals):
            if i == 0:
                continue  # skip header
            name_val = row[1].strip() if len(row) > 1 else ""
            if name_val == "":
                return i + 1   # i is 0-based, sheet rows are 1-based
        # If all rows are filled, return next row after last
        return len(all_vals) + 1
    except Exception as e:
        print(f"find_first_empty_db_row error: {e}")
        return 2


def get_code_for_row(row_number: int) -> int:
    """
    Read the pre-existing code in col A for the given row.
    If it exists and is a number, use it. Otherwise fall back to row_number - 1.
    """
    try:
        val = db_sheet.cell(row_number, 1).value
        if val:
            return int(float(val))
    except Exception:
        pass
    return row_number - 1   # fallback: row 2 = code 1, row 3 = code 2, etc.


def find_first_empty_daily_row() -> int:
    """
    The Daily sheet has pre-filled formulas but col B (code) and col D (start time) are empty.
    Find the first row where col B (code) is empty — that is our next session slot.
    """
    try:
        # Only fetch col B to keep it fast
        col_b = daily_sheet.col_values(2)   # 1-based col index
        for i, val in enumerate(col_b):
            if i == 0:
                continue  # skip header
            if str(val).strip() == "":
                return i + 1   # 1-based row number
        return len(col_b) + 1
    except Exception as e:
        print(f"find_first_empty_daily_row error: {e}")
        return 2


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "ok", "message": "Gresan backend is running"}), 200


# ── Sign Up ───────────────────────────────────────────────────────────────────
@app.route("/signup", methods=["POST"])
def signup():
    if db_sheet is None:
        return jsonify({"status": "error", "message": "Sheet not connected"}), 500

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "No JSON body received"}), 400

    # Validate required fields
    missing = [f for f in ("name", "pnumber") if not str(data.get(f, "")).strip()]
    if missing:
        return jsonify({"status": "error", "message": f'Missing fields: {", ".join(missing)}'}), 400

    user_name  = str(data["name"]).strip()
    user_phone = format_egypt_phone(str(data["pnumber"]).strip())
    birthday   = str(data.get("birthday", "")).strip()   # DD/MM/YYYY from flatpickr
    title      = str(data.get("title", "")).strip()
    jtitle     = str(data.get("jtitle", "")).strip()
    career     = f"{title} — {jtitle}" if jtitle else title

    # Duplicate phone check
    if find_by_phone(user_phone):
        return jsonify({
            "status":  "phone_error",
            "message": f"Number {user_phone} is already registered.",
        }), 409

    try:
        join_date  = datetime.now().strftime("%Y-%m-%d")

        # Find first empty slot in the pre-filled template sheet
        target_row = find_first_empty_db_row()
        # Read the pre-existing code already in col A of that row
        code       = get_code_for_row(target_row)

        # Write only the columns WE own: B(Name) C(Phone) F(Birthday) G(JoinDate) H(Career)
        # We leave A (pre-filled code), D (international formula), E (Whatsapp formula) untouched
        db_sheet.update(
            f"B{target_row}:I{target_row}",
            [[user_name, user_phone, "", "", birthday, join_date, career, ""]],
            value_input_option="RAW",
        )

        return jsonify({
            "status":  "success",
            "message": "Registered successfully.",
            "code":    code,
            "name":    user_name,
        }), 201

    except Exception as e:
        print(f"Signup error: {e}")
        return jsonify({"status": "error", "message": "Registration failed. Try again."}), 500


# ── Sign In ───────────────────────────────────────────────────────────────────
@app.route("/signin", methods=["POST"])
def signin():
    if db_sheet is None or daily_sheet is None:
        return jsonify({"status": "error", "message": "Sheet not connected"}), 500

    data = request.get_json(silent=True)
    code_raw = str(data.get("code", "")).strip() if data else ""

    if not code_raw:
        return jsonify({"status": "error", "message": "User code is required"}), 400

    user = find_by_code(code_raw)
    if not user:
        return jsonify({
            "status":  "not_found",
            "message": "Code not found. Please sign up first.",
        }), 404

    # Signin only authenticates — session timing is handled by
    # /session/start and /session/end triggered from the home page buttons.
    return jsonify({
        "status":  "success",
        "message": f'Welcome, {user["name"]}!',
        "code":    user["code"],
        "name":    user["name"],
        "career":  user.get("career", ""),
    }), 200


# ── Get user by code ──────────────────────────────────────────────────────────
@app.route("/user/<code>", methods=["GET"])
def get_user(code):
    if db_sheet is None:
        return jsonify({"status": "error", "message": "Sheet not connected"}), 500

    user = find_by_code(code)
    if not user:
        return jsonify({"status": "error", "message": "User not found"}), 404

    return jsonify({
        "status": "success",
        "code":   user["code"],
        "name":   user["name"],
        "career": user.get("career", ""),
    }), 200


# ── Session Start ─────────────────────────────────────────────────────────────
@app.route("/session/start", methods=["POST"])
def session_start():
    if db_sheet is None or daily_sheet is None:
        return jsonify({"status": "error", "message": "Sheet not connected"}), 500

    data     = request.get_json(silent=True)
    code_raw = str(data.get("code", "")).strip() if data else ""

    if not code_raw:
        return jsonify({"status": "error", "message": "User code required"}), 400

    user = find_by_code(code_raw)
    if not user:
        return jsonify({"status": "not_found", "message": "Code not found."}), 404

    try:
        start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        daily_row  = find_first_empty_daily_row()

        # Write code → col B, start time → col D, career → col P
        daily_sheet.update(f"B{daily_row}", [[int(user["code"])]], value_input_option="RAW")
        daily_sheet.update(f"D{daily_row}", [[start_time]],        value_input_option="RAW")
        daily_sheet.update(f"P{daily_row}", [[user.get("career", "")]], value_input_option="RAW")

        return jsonify({
            "status":     "success",
            "start_time": start_time,
            "daily_row":  daily_row,   # send back so end-session knows which row to update
        }), 200

    except Exception as e:
        print(f"Session start error: {e}")
        return jsonify({"status": "error", "message": "Could not start session."}), 500


# ── Session End ───────────────────────────────────────────────────────────────
@app.route("/session/end", methods=["POST"])
def session_end():
    if daily_sheet is None:
        return jsonify({"status": "error", "message": "Sheet not connected"}), 500

    data      = request.get_json(silent=True)
    daily_row = data.get("daily_row") if data else None

    if not daily_row:
        return jsonify({"status": "error", "message": "daily_row required"}), 400

    try:
        end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Write end time → col E of the same row that was opened at session start
        daily_sheet.update(f"E{daily_row}", [[end_time]], value_input_option="RAW")

        # Calculate duration to send back to the frontend for display
        start_str = daily_sheet.cell(daily_row, 4).value   # col D = Start time
        duration_str = ""
        if start_str:
            try:
                start_dt = datetime.strptime(str(start_str), "%Y-%m-%d %H:%M:%S")
                end_dt   = datetime.strptime(end_time,       "%Y-%m-%d %H:%M:%S")
                delta    = end_dt - start_dt
                total_s  = int(delta.total_seconds())
                hours    = total_s // 3600
                minutes  = (total_s % 3600) // 60
                duration_str = f"{hours}h {minutes}m"
            except Exception:
                duration_str = ""

        return jsonify({
            "status":       "success",
            "end_time":     end_time,
            "duration":     duration_str,
        }), 200

    except Exception as e:
        print(f"Session end error: {e}")
        return jsonify({"status": "error", "message": "Could not end session."}), 500



if __name__ == "__main__":
    app.run(host="localhost", port=8000, debug=True)