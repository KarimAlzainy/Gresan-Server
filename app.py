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
import os

app = Flask(__name__)
CORS(app)

SHEET_NAME = "Copy of Copy of Gresan System (External) - March 19, 9:26 PM"
DB_TAB     = "Data Base"
DAILY_TAB  = "Daily 26 (3)"
PRICES_TAB = "Prices"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
cred_path = os.path.join(BASE_DIR, "credentials.json")

SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

db_sheet     = None
daily_sheet  = None
prices_sheet = None

try:
    creds = ServiceAccountCredentials.from_json_keyfile_name(cred_path, SCOPE)
    client       = gspread.authorize(creds)
    spreadsheet  = client.open(SHEET_NAME)
    db_sheet     = spreadsheet.worksheet(DB_TAB)
    daily_sheet  = spreadsheet.worksheet(DAILY_TAB)
    prices_sheet = spreadsheet.worksheet(PRICES_TAB)
    print("OK: Google Sheets connected.")
except Exception as e:
    print(f"Error: Google Sheets Error: {e}")


# ─── Pricing ─────────────────────────────────────────────────────────────────

_prices_cache = None
_prices_cache_time = None

def get_prices_catalogue():
    """Read from Prices sheet and Inventory table. Cache for 5 min."""
    global _prices_cache, _prices_cache_time
    import time
    now = time.time()
    if _prices_cache is not None and _prices_cache_time and (now - _prices_cache_time) < 300:
        return _prices_cache
    try:
        rows = prices_sheet.get_all_values()
        cat  = {}
        for i, row in enumerate(rows[1:], start=1):   # skip header
            # -- Left table (Prices) --
            name_L  = (row[0] if len(row) > 0 else "").strip()
            price_L = (row[1] if len(row) > 1 else "").strip()
            typ_L   = (row[2] if len(row) > 2 else "OTHER").strip()
            
            if name_L and price_L:
                clean_price_L = re.sub(r'[^\d.]', '', price_L)
                try:
                    price_val = int(float(clean_price_L))
                    key = f"L_{i}"
                    cat[key] = {"name": name_L, "price": price_val, "type": typ_L or "OTHER"}
                except Exception:
                    pass

            # -- Right table (Inventory) --
            # Details (Index 7), Type (Index 8), SELLING PRICE (Index 13)
            name_R  = (row[7] if len(row) > 7 else "").strip()
            typ_R   = (row[8] if len(row) > 8 else "OTHER").strip()
            price_R = (row[13] if len(row) > 13 else "").strip()

            if name_R and price_R:
                clean_price_R = re.sub(r'[^\d.]', '', price_R)
                try:
                    price_val_R = int(float(clean_price_R))
                    key = f"R_{i}"
                    cat[key] = {"name": name_R, "price": price_val_R, "type": typ_R or "OTHER"}
                except Exception:
                    pass

        _prices_cache      = cat
        _prices_cache_time = now
        return cat
    except Exception as e:
        print(f"Prices read error: {e}")
        return {}


def calc_hour_price(elapsed_seconds: float) -> int:
    minutes = elapsed_seconds / 60
    if minutes <= 30:
        return 0
    elif minutes <= 60:
        return 15
    elif minutes <= 120:
        return 30
    else:
        return 50

def calc_snacks_price(snack_keys: list):
    cat   = get_prices_catalogue()
    total = 0
    names = []
    for k in snack_keys:
        item = cat.get(str(k))
        if item:
            total += item["price"]
            names.append(item["name"])
    return total, ", ".join(names)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def format_egypt_phone(raw):
    clean = re.sub(r"[^\d+]", "", str(raw))
    if clean.startswith("+20"): return clean
    if clean.startswith("20"):  return "+" + clean
    if clean.startswith("01"):  return "+20" + clean[1:]
    if clean.startswith("1") and len(clean) == 10: return "+20" + clean
    return clean

def get_all_db_rows():
    try:
        all_vals = db_sheet.get_all_values()
    except Exception as e:
        print(f"DB read error: {e}")
        return []
    rows = []
    for row in all_vals[1:]:
        if not any(row): continue
        rows.append({
            "code":   (row[0] if len(row) > 0 else "").strip(),
            "name":   (row[1] if len(row) > 1 else "").strip(),
            "phone":  (row[2] if len(row) > 2 else "").strip(),
            "career": (row[7] if len(row) > 7 else "").strip(),
        })
    return rows

def _is_valid(user):
    return bool(user.get("name", "").strip() or user.get("phone", "").strip())

def find_by_phone(phone):
    return next((r for r in get_all_db_rows() if r["phone"] == phone and _is_valid(r)), None)

def find_by_code(code):
    return next((r for r in get_all_db_rows() if str(r["code"]) == str(code) and _is_valid(r)), None)

def find_first_empty_db_row():
    try:
        all_vals = db_sheet.get_all_values()
        for i, row in enumerate(all_vals):
            if i == 0: continue
            if (row[1].strip() if len(row) > 1 else "") == "":
                return i + 1
        return len(all_vals) + 1
    except: return 2

def get_code_for_row(row_number):
    try:
        val = db_sheet.cell(row_number, 1).value
        if val and str(val).strip() != "": 
            return int(float(val))
    except: pass
    return None

def find_first_empty_daily_row():
    try:
        col_b = daily_sheet.col_values(2)
        for i, val in enumerate(col_b):
            if i == 0: continue
            if str(val).strip() == "": return i + 1
        return len(col_b) + 1
    except: return 2


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "ok"}), 200

@app.route("/snacks", methods=["GET"])
def get_snacks():
    return jsonify({"status": "success", "snacks": get_prices_catalogue()}), 200

@app.route("/validate_code/<code>", methods=["GET"])
def validate_code(code):
    if db_sheet is None:
        return jsonify({"status": "error", "message": "Sheet not connected"}), 500
    
    user = find_by_code(code)
    if not user:
        user = find_by_phone(code)
    if not user:
        user = find_by_phone(format_egypt_phone(code))
        
    if not user:
        return jsonify({"status": "not_found", "message": "Code or phone not found"}), 404
        
    return jsonify({"status": "success", "name": user["name"], "code": user["code"]}), 200

@app.route("/signup", methods=["POST"])
def signup():
    if db_sheet is None:
        return jsonify({"status": "error", "message": "Sheet not connected"}), 500
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "No JSON body"}), 400
    missing = [f for f in ("name", "pnumber") if not str(data.get(f, "")).strip()]
    if missing:
        return jsonify({"status": "error", "message": f'Missing: {", ".join(missing)}'}), 400

    user_name  = str(data["name"]).strip()
    user_phone = format_egypt_phone(str(data["pnumber"]).strip())
    birthday   = str(data.get("birthday", "")).strip()
    title      = str(data.get("title", "")).strip()
    jtitle     = str(data.get("jtitle", "")).strip()
    career     = f"{title}" if jtitle else title

    if find_by_phone(user_phone):
        return jsonify({"status": "phone_error", "message": f"{user_phone} already registered."}), 409

    try:
        join_date  = datetime.now().strftime("%Y-%m-%d")
        target_row = find_first_empty_db_row()
        
        existing_code = get_code_for_row(target_row)
        if existing_code is not None:
            code = existing_code
            db_sheet.update(f"B{target_row}:I{target_row}",
                [[user_name, user_phone, "", "", birthday, join_date, career, ""]],
                value_input_option="RAW")
        else:
            code = target_row - 1
            db_sheet.update(f"A{target_row}:I{target_row}",
                [[code, user_name, user_phone, "", "", birthday, join_date, career, ""]],
                value_input_option="RAW")
                
        # Auto-start session
        session_data = _do_start_session(str(code), [])
        return jsonify({
            "status": "success", "message": "Registered.", "code": code, "name": user_name,
            "auto_session": session_data,
        }), 201
    except Exception as e:
        print(f"Signup error: {e}")
        return jsonify({"status": "error", "message": "Registration failed."}), 500


@app.route("/signin", methods=["POST"])
def signin():
    if db_sheet is None or daily_sheet is None:
        return jsonify({"status": "error", "message": "Sheet not connected"}), 500
    data         = request.get_json(silent=True)
    code_raw     = str(data.get("code", "")).strip() if data else ""
    friend_codes = data.get("friend_codes", []) if data else []

    if not code_raw:
        return jsonify({"status": "error", "message": "Code or phone required"}), 400
        
    user = find_by_code(code_raw)
    if not user:
        user = find_by_phone(code_raw)
    if not user:
        user = find_by_phone(format_egypt_phone(code_raw))
        
    if not user:
        return jsonify({"status": "not_found", "message": "Account not found. Sign up first."}), 404

    user_actual_code = str(user["code"])

    friends_info  = []
    invalid_codes = []
    for fc in friend_codes:
        fc_str = str(fc).strip()
        
        friend = find_by_code(fc_str)
        if not friend: friend = find_by_phone(fc_str)
        if not friend: friend = find_by_phone(format_egypt_phone(fc_str))
        
        if friend: 
            if str(friend["code"]) == user_actual_code: continue
            friends_info.append({"code": friend["code"], "name": friend["name"]})
        else:
            invalid_codes.append(fc_str)

    if invalid_codes:
        return jsonify({"status": "friend_not_found",
                        "message": f"Accounts not found for: {', '.join(invalid_codes)}"}), 404

    # Auto-start session on sign in
    fc_list      = [f["code"] for f in friends_info]
    session_data = _do_start_session(user_actual_code, fc_list)

    return jsonify({
        "status":       "success",
        "message":      f'Welcome, {user["name"]}!',
        "code":         user["code"],
        "name":         user["name"],
        "career":       user.get("career", ""),
        "friends":      friends_info,
        "auto_session": session_data,
    }), 200


@app.route("/user/<code>", methods=["GET"])
def get_user(code):
    if db_sheet is None:
        return jsonify({"status": "error", "message": "Sheet not connected"}), 500
    user = find_by_code(code)
    if not user:
        return jsonify({"status": "error", "message": "Not found"}), 404
    return jsonify({"status": "success", "code": user["code"], "name": user["name"],
                    "career": user.get("career", "")}), 200


def _do_start_session(code_raw, friend_codes_list):
    """Internal helper — starts a session and returns the data dict."""
    user = find_by_code(code_raw)
    if not user: return None
    try:
        start_time   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        total_people = 1 + len(friend_codes_list)
        daily_row    = find_first_empty_daily_row()
        group_note   = f"Group: {code_raw} + {', '.join(str(f) for f in friend_codes_list)}" if friend_codes_list else ""
        daily_sheet.update(f"B{daily_row}", [[int(user["code"])]], value_input_option="RAW")
        daily_sheet.update(f"D{daily_row}", [[start_time]],        value_input_option="RAW")
        daily_sheet.update(f"P{daily_row}", [[user.get("career", "")]], value_input_option="RAW")
        if group_note:
            daily_sheet.update(f"K{daily_row}", [[group_note]], value_input_option="RAW")
        return {"start_time": start_time, "daily_row": daily_row, "total_people": total_people}
    except Exception as e:
        print(f"_do_start_session error: {e}")
        return None


@app.route("/session/start", methods=["POST"])
def session_start():
    if db_sheet is None or daily_sheet is None:
        return jsonify({"status": "error", "message": "Sheet not connected"}), 500
    data         = request.get_json(silent=True)
    code_raw     = str(data.get("code", "")).strip() if data else ""
    friend_codes = data.get("friend_codes", []) if data else []
    if not code_raw:
        return jsonify({"status": "error", "message": "Code required"}), 400
    result = _do_start_session(code_raw, friend_codes)
    if not result:
        return jsonify({"status": "error", "message": "Could not start session."}), 500
    return jsonify({"status": "success", **result}), 200


@app.route("/session/end", methods=["POST"])
def session_end():
    if daily_sheet is None:
        return jsonify({"status": "error", "message": "Sheet not connected"}), 500
    data         = request.get_json(silent=True)
    daily_row    = data.get("daily_row")  if data else None
    snack_keys   = data.get("snacks", []) if data else []
    total_people = int(data.get("total_people", 1)) if data else 1
    if not daily_row:
        return jsonify({"status": "error", "message": "daily_row required"}), 400
    try:
        end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        daily_sheet.update(f"E{daily_row}", [[end_time]], value_input_option="RAW")
        start_str    = daily_sheet.cell(daily_row, 4).value
        duration_str = ""
        hour_price   = 0
        if start_str:
            try:
                start_dt  = datetime.strptime(str(start_str), "%Y-%m-%d %H:%M:%S")
                end_dt    = datetime.strptime(end_time,       "%Y-%m-%d %H:%M:%S")
                elapsed_s = (end_dt - start_dt).total_seconds()
                hours     = int(elapsed_s) // 3600
                minutes   = (int(elapsed_s) % 3600) // 60
                duration_str = f"{hours}h {minutes}m"
                hour_price   = calc_hour_price(elapsed_s) * total_people
            except: pass

        snacks_price, snacks_names = calc_snacks_price(snack_keys)
        total_price = hour_price + snacks_price

        # Write prices and snacks to sheet
        daily_sheet.update(f"G{daily_row}", [[hour_price]],   value_input_option="RAW")
        daily_sheet.update(f"H{daily_row}", [[snacks_names]], value_input_option="RAW")
        daily_sheet.update(f"I{daily_row}", [[snacks_price]], value_input_option="RAW")

        return jsonify({
            "status": "success", "end_time": end_time, "duration": duration_str,
            "hour_price": hour_price, "snacks_price": snacks_price,
            "total_price": total_price, "total_people": total_people,
        }), 200
    except Exception as e:
        print(f"Session end error: {e}")
        return jsonify({"status": "error", "message": "Could not end session."}), 500


@app.route("/session/price", methods=["POST"])
def session_price():
    data         = request.get_json(silent=True)
    elapsed_s    = float(data.get("elapsed_seconds", 0)) if data else 0
    snack_keys   = data.get("snacks", [])                if data else []
    total_people = int(data.get("total_people", 1))      if data else 1
    hour_price              = calc_hour_price(elapsed_s) * total_people
    snacks_price, snk_names = calc_snacks_price(snack_keys)
    return jsonify({
        "hour_price": hour_price, "snacks_price": snacks_price,
        "total": hour_price + snacks_price, "snacks_names": snk_names,
    }), 200


@app.route("/session/sync_snacks", methods=["POST"])
def session_sync_snacks():
    if daily_sheet is None:
        return jsonify({"status": "error", "message": "Sheet not connected"}), 500
    data       = request.get_json(silent=True)
    daily_row  = data.get("daily_row") if data else None
    snack_keys = data.get("snacks", []) if data else []
    if not daily_row:
        return jsonify({"status": "error", "message": "daily_row required"}), 400
    try:
        snacks_price, snacks_names = calc_snacks_price(snack_keys)
        daily_sheet.update(f"H{daily_row}", [[snacks_names]], value_input_option="RAW")
        daily_sheet.update(f"I{daily_row}", [[snacks_price]], value_input_option="RAW")
        return jsonify({"status": "success"}), 200
    except Exception as e:
        print(f"Session sync snacks error: {e}")
        return jsonify({"status": "error"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
