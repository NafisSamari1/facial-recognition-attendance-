"""
app.py
------
Flask backend for the Face Recognition Attendance Management System.

Routes:
    /                   dashboard (analytics overview)
    /register           student registration + face capture
    /attendance         live recognition / attendance-taking screen
    /reports            searchable, exportable attendance records
    /students           manage registered students

API (JSON, called from the browser via fetch()):
    POST /api/students                 create a student
    POST /api/capture-sample           save one face sample frame
    POST /api/train                    (re)train the LBPH model
    POST /api/recognize                run recognition on one frame
    POST /api/mark-attendance          confirm + log an attendance event
    GET  /api/stats                    summary numbers for the dashboard
    GET  /api/trend                    7-day attendance trend
    GET  /api/course-breakdown         attendance count per course
    GET  /api/attendance.csv           export attendance as CSV
"""

import csv
import io
import os
import urllib.parse

from flask import Flask, Response, jsonify, render_template, request, redirect, url_for, flash, session

import database as db
import face_utils
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key')
db.init_db()


MANAGER_PAGES = {"register_page", "zone_page", "students_page"}
MANAGER_API_ENDPOINTS = {
    "api_create_student",
    "api_courses",
    "api_delete_course",
    "api_start_session",
    "api_end_session",
    "api_delete_student",
    "api_manager_unbind_device"
}

@app.before_request
def restrict_manager_access():
    # If the endpoint is restricted, check authentication and authorization
    is_restricted_api = request.endpoint in MANAGER_API_ENDPOINTS or (request.endpoint == "api_zone" and request.method in {"POST", "DELETE"})
    is_restricted_page = request.endpoint in MANAGER_PAGES

    if is_restricted_page or is_restricted_api:
        if not session.get("logged_in"):
            if is_restricted_api:
                return jsonify({"ok": False, "error": "Authentication required"}), 401
            return redirect(url_for("login_page"))
        
        if session.get("role") != "manager":
            if is_restricted_api:
                return jsonify({"ok": False, "error": "Manager access required"}), 403
            flash("Access restricted to Managers.")
            return redirect(url_for("dashboard"))

def is_manager():
    return session.get("logged_in") and session.get("role") == "manager"


# --------------------------------------------------------------- pages -----

@app.route("/")
def dashboard():
    if not session.get("logged_in"):
        return redirect(url_for("login_page"))
    
    if session.get("role") == "student":
        student_id = session.get("student_id")
        summary = db.get_student_summary(student_id) if student_id else None
        return render_template("dashboard.html", student_summary=summary)
        
    return render_template("dashboard.html")


@app.route("/login", methods=["GET", "POST"])
def login_page():
    if session.get("logged_in"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        student_id = (request.form.get("student_id") or "").strip()
        device_id = (request.form.get("device_id") or "").strip()
        device_name = (request.form.get("device_name") or "").strip()

        if not student_id:
            flash("Please enter your Student ID.")
            return render_template("login_student.html")
        
        student = db.get_student(student_id)
        if not student:
            flash(f"Student ID '{student_id}' not found. Please verify or ask a Manager to register your account.")
            return render_template("login_student.html")

        # Strict 1:1 Device Binding Checks
        if device_id:
            # Check 1: Is this student's account bound to a different device?
            if student.get("device_id") and student["device_id"] != device_id:
                bound_name = student.get("device_name") or "another device"
                flash(f"❌ Device Binding Mismatch: Account '{student_id}' is registered to a different phone ({bound_name}). You cannot log in from this device. If you lost or changed your phone, submit a device reset request to your manager.")
                return render_template("login_student.html")

            # Check 2: Is this device already assigned to another student?
            assigned_other = db.get_student_by_device(device_id)
            if assigned_other and assigned_other["student_id"] != student_id:
                flash(f"❌ Device Sharing Restriction: This device is already registered to another student ({assigned_other['full_name']}). Multiple students cannot share the same device.")
                return render_template("login_student.html")

            # If student is unbound, bind this device to their account automatically
            if not student.get("device_id"):
                db.assign_device(student_id, device_id, device_name)
            elif device_name and device_name != student.get("device_name"):
                db.update_device_name(student_id, device_name)

        session["logged_in"] = True
        session["role"] = "student"
        session["username"] = student["full_name"]
        session["student_id"] = student["student_id"]
        session["full_name"] = student["full_name"]
        session["course"] = student["course"]
        flash(f"Welcome back, {student['full_name']}.")
        return redirect(url_for("dashboard"))

    return render_template("login_student.html")


@app.route("/login/manager", methods=["GET", "POST"])
def login_manager():
    if session.get("logged_in"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        expected_user, expected_pass = db.get_manager_credentials()

        if not username or not password:
            flash("Username and password are required.")
            return render_template("login_manager.html")

        if username == expected_user and password == expected_pass:
            session["logged_in"] = True
            session["role"] = "manager"
            session["username"] = username
            flash("Welcome back to Verascan Manager Portal.")
            return redirect(url_for("dashboard"))

        flash("Invalid manager username or password.")

    return render_template("login_manager.html")


@app.route("/account/security", methods=["POST"])
def update_manager_account():
    if not is_manager():
        flash("Manager access required.")
        return redirect(url_for("dashboard"))

    new_username = (request.form.get("username") or "").strip()
    current_password = request.form.get("current_password") or ""
    new_password = request.form.get("new_password") or ""
    confirm_password = request.form.get("confirm_password") or ""

    manager_username, manager_password = db.get_manager_credentials()
    if not new_username or not current_password or not new_password or not confirm_password:
        flash("Please complete all account fields.")
        return redirect(url_for("dashboard"))

    if current_password != manager_password:
        flash("Current password is incorrect.")
        return redirect(url_for("dashboard"))

    if new_password != confirm_password:
        flash("New passwords do not match.")
        return redirect(url_for("dashboard"))

    try:
        db.set_manager_credentials(new_username, new_password)
    except ValueError as exc:
        flash(str(exc))
        return redirect(url_for("dashboard"))

    session["username"] = new_username
    flash("Manager account updated successfully.")
    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))


@app.route("/register")
def register_page():
    return render_template("register.html")


@app.route("/attendance")
def attendance_page():
    if not session.get("logged_in"):
        return redirect(url_for("login_page"))
    return render_template("attendance.html")


@app.route("/discover")
def discover_page():
    if not session.get("logged_in"):
        return redirect(url_for("login_page"))
    return render_template("discover.html")


@app.route("/zone-setup")
def zone_page():
    return render_template("zone.html")


@app.route("/reports")
def reports_page():
    if not session.get("logged_in"):
        return redirect(url_for("login_page"))
    return render_template("reports.html")


@app.route("/help-center")
def help_center_page():
    if not session.get("logged_in"):
        return redirect(url_for("login_page"))
    return render_template("help_center.html")


@app.route("/students")
def students_page():
    return render_template("students.html", students=db.list_students())



@app.route("/api/geocode")
def api_geocode():
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify({"ok": False, "results": []})
    try:
        import urllib.request
        import urllib.parse
        import json
        url = f"https://nominatim.openstreetmap.org/search?format=json&q={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={'User-Agent': 'VerascanAttendanceSystem/1.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            results = [{
                "display_name": item.get("display_name"),
                "lat": float(item.get("lat")),
                "lng": float(item.get("lon"))
            } for item in data[:5]]
            return jsonify({"ok": True, "results": results})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "results": []})



# --------------------------------------------------------------- API -------

@app.route("/api/courses", methods=["GET", "POST"])
def api_courses():
    if not is_manager():
        return jsonify({"ok": False, "error": "Manager access required"}), 403

    if request.method == "POST":
        payload = request.get_json(force=True) or {}
        course_name = (payload.get("name") or "").strip()
        if not course_name:
            return jsonify({"ok": False, "error": "Course name is required"}), 400
        db.ensure_course(course_name)
        return jsonify({"ok": True, "courses": db.list_courses()})

    return jsonify({"ok": True, "courses": db.list_courses()})


@app.route("/api/courses/<path:course_name>", methods=["DELETE"])
def api_delete_course(course_name):
    if not is_manager():
        return jsonify({"ok": False, "error": "Manager access required"}), 403

    decoded = urllib.parse.unquote(course_name).strip()
    if not decoded:
        return jsonify({"ok": False, "error": "Course name is required"}), 400

    if not db.delete_course(decoded):
        return jsonify({"ok": False, "error": f"Course '{decoded}' is in use and cannot be removed."}), 409

    return jsonify({"ok": True, "courses": db.list_courses()})


@app.route("/api/students", methods=["POST"])
def api_create_student():
    payload = request.get_json(force=True)
    student_id = (payload.get("student_id") or "").strip()
    full_name = (payload.get("full_name") or "").strip()
    course = (payload.get("course") or "").strip()
    email = (payload.get("email") or "").strip()
    device_id = (payload.get("device_id") or "").strip() or None

    if not student_id or not full_name or not course:
        return jsonify({"ok": False, "error": "Student ID, Full Name, and Course are required"}), 400

    if not device_id:
        device_id = f"dev-{student_id.lower()}"

    if db.get_student(student_id):
        return jsonify({"ok": False, "error": "A student with that ID already exists"}), 409

    if db.get_student_by_device(device_id):
        # If auto-generated device_id conflicts, append timestamp suffix
        device_id = f"{device_id}-{os.urandom(2).hex()}"

    db.add_student(student_id, full_name, course, email, device_id=device_id)
    return jsonify({"ok": True, "device_id": device_id})


@app.route("/api/students", methods=["GET"])
def api_list_students():
    if not is_manager():
        return jsonify({"ok": False, "error": "Manager access required"}), 403
    return jsonify({"ok": True, "students": db.list_students()})


@app.route("/api/capture-sample", methods=["POST"])
def api_capture_sample():
    payload = request.get_json(force=True)
    student_id = payload.get("student_id")

    # Allow if manager OR if logged-in student capturing for their own account
    is_self = (session.get("role") == "student" and session.get("student_id") == student_id)
    if not (is_manager() or is_self):
        return jsonify({"ok": False, "error": "Unauthorized to capture face samples for this student ID"}), 403

    frame = payload.get("frame")
    sample_index = int(payload.get("sample_index", 0))

    if not db.get_student(student_id):
        return jsonify({"ok": False, "error": "Unknown student_id"}), 404

    saved = face_utils.save_face_sample(student_id, frame, sample_index)
    if not saved:
        return jsonify({"ok": False, "error": "No face detected in frame - hold steady and face the camera"}), 422

    total = face_utils.count_samples(student_id)
    db.set_face_sample_count(student_id, total)
    return jsonify({"ok": True, "total_samples": total})


@app.route("/api/train", methods=["POST"])
def api_train():
    if not (is_manager() or session.get("role") == "student"):
        return jsonify({"ok": False, "error": "Unauthorized to train recognition model"}), 403
    result = face_utils.train_model()
    return jsonify(result)




@app.route("/api/recognize", methods=["POST"])
def api_recognize():
    payload = request.get_json(force=True)
    frame = payload.get("frame")
    result = face_utils.recognize(frame)

    if result.get("face_found"):
        db.log_event(
            matched=result.get("matched", False),
            student_id=result.get("student_id"),
            full_name=db.get_student(result["student_id"])["full_name"] if result.get("student_id") else None,
            confidence=result.get("confidence"),
            reason=result.get("reason", "unknown"),
        )
        if result.get("matched") and result.get("student_id"):
            student = db.get_student(result["student_id"])
            if student:
                result["full_name"] = student["full_name"]
                result["course"] = student["course"]
                result["already_marked"] = db.has_attended_today(student["student_id"], student["course"])

    return jsonify(result)


@app.route("/api/mark-attendance", methods=["POST"])
def api_mark_attendance():
    payload = request.get_json(force=True)
    student_id = payload.get("student_id")
    confidence = float(payload.get("confidence", 0))

    student = db.get_student(student_id)
    if not student:
        return jsonify({"ok": False, "error": "Unknown student"}), 404

    device_id = (payload.get("device_id") or "").strip()
    device_name = (payload.get("device_name") or "").strip()
    location_lat = payload.get("location_lat")
    location_lng = payload.get("location_lng")

    if location_lat is None or location_lng is None:
        return jsonify({"ok": False, "error": "Location is required to mark attendance."}), 400

    if not device_id:
        return jsonify({"ok": False, "error": "Device identification required to mark attendance."}), 400

    # Strict 1:1 Device Checks
    assigned_student = db.get_student_by_device(device_id)
    if assigned_student and assigned_student["student_id"] != student_id:
        return jsonify({
            "ok": False,
            "error": f"❌ Device Sharing Restriction: This device is registered to {assigned_student['full_name']}. You cannot take attendance for another student on this device."
        }), 403

    if student.get("device_id") and student["device_id"] != device_id:
        bound_name = student.get("device_name") or "another phone"
        return jsonify({
            "ok": False,
            "error": f"❌ Device Mismatch: Your account is registered to a different device ({bound_name}). Request a device reset if you changed your phone."
        }), 403

    active_session = db.get_active_session(course=student["course"])
    if not active_session:
        return jsonify({
            "ok": False,
            "error": f"Attendance window for {student['course']} is closed. No active attendance signal broadcasted by manager."
        }), 403

    zone_check = face_utils.check_allowed_area(location_lat, location_lng)
    if not zone_check.get("allowed"):
        return jsonify({
            "ok": False,
            "error": zone_check.get("message", "Student must be in the allowed attendance area to sign in.")
        }), 403

    if not student.get("device_id"):
        db.assign_device(student_id, device_id, device_name)

    status = "present" if confidence >= face_utils.CONFIDENCE_ACCEPT_THRESHOLD else "flagged"
    db.log_attendance(
        student_id,
        student["full_name"],
        student["course"],
        confidence,
        status=status,
        device_id=device_id,
        location_lat=location_lat,
        location_lng=location_lng,
    )
    return jsonify({"ok": True, "duplicate": False, "status": status,
                     "message": f"Attendance recorded for {student['full_name']}."})


@app.route("/api/student/request-device-reset", methods=["POST"])
def api_request_device_reset():
    if session.get("role") != "student":
        return jsonify({"ok": False, "error": "Student access required"}), 403
    payload = request.get_json(force=True) or {}
    reason = (payload.get("reason") or "Lost or changed device").strip()
    student_id = session.get("student_id")
    db.request_device_reset(student_id, reason)
    return jsonify({"ok": True, "message": "Device reset request submitted to your manager."})


@app.route("/api/manager/unbind-device", methods=["POST"])
def api_manager_unbind_device():
    payload = request.get_json(force=True) or {}
    student_id = (payload.get("student_id") or "").strip()
    if not student_id:
        return jsonify({"ok": False, "error": "Student ID required"}), 400
    db.unbind_student_device(student_id)
    return jsonify({"ok": True, "message": f"Device binding successfully reset for student {student_id}."})



@app.route("/api/zone", methods=["GET", "POST", "DELETE"])
def api_zone():
    if request.method == "DELETE":
        db.clear_active_zone()
        return jsonify({"ok": True, "zone": None})
    if request.method == "POST":
        payload = request.get_json(force=True)
        lat = payload.get("lat")
        lng = payload.get("lng")
        radius = payload.get("radius_meters")
        name = (payload.get("name") or "").strip()
        if lat is None or lng is None or radius is None or not name:
            return jsonify({"ok": False, "error": "Zone name, latitude, longitude, and radius are required."}), 400
        try:
            if float(radius) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Radius must be greater than zero."}), 400
        zone = db.set_active_zone(lat, lng, radius, name)
        return jsonify({"ok": True, "zone": zone})
    
    zone = db.get_active_zone()
    return jsonify({"ok": True, "zone": zone})


@app.route("/api/zone/check", methods=["POST"])
def api_zone_check():
    payload = request.get_json(force=True)
    lat = payload.get("lat")
    lng = payload.get("lng")
    if lat is None or lng is None:
        return jsonify({"ok": False, "error": "Latitude and longitude required"}), 400
    res = face_utils.check_allowed_area(lat, lng)
    return jsonify(res)


@app.route("/api/sessions/active", methods=["GET"])
def api_active_session():
    course = request.args.get("course") or None
    if session.get("role") == "student" and not course:
        course = session.get("course")
    session_data = db.get_active_session(course)
    zone_data = db.get_active_zone()
    return jsonify({"ok": True, "session": session_data, "zone": zone_data})


@app.route("/api/sessions/start", methods=["POST"])
def api_start_session():

    payload = request.get_json(force=True)
    course = (payload.get("course") or "").strip()
    duration_value = payload.get("duration_minutes")
    title = (payload.get("title") or "").strip()
    if not course or duration_value is None:
        return jsonify({"ok": False, "error": "Course and attendance duration are required."}), 400
    try:
        duration = int(duration_value)
        if duration < 1:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Attendance duration must be at least one minute."}), 400
    if not title:
        title = f"{course} Attendance Session"

    zone = db.get_active_zone()
    if not zone:
        return jsonify({"ok": False, "error": "Save an attendance area zone before opening the attendance window."}), 400
    
    sess = db.create_session(course, duration, title)
    return jsonify({"ok": True, "session": sess})


@app.route("/api/sessions/end", methods=["POST"])
def api_end_session():

    payload = request.get_json(force=True)
    session_id = payload.get("session_id")
    if not session_id:
        return jsonify({"ok": False, "error": "Session ID required"}), 400
    db.end_session(session_id)
    return jsonify({"ok": True})


@app.route("/api/students/<student_id>", methods=["DELETE"])
def api_delete_student(student_id):

    db.delete_student(student_id)
    return jsonify({"ok": True})


@app.route("/api/stats")
def api_stats():
    return jsonify(db.get_summary_stats())


@app.route("/api/trend")
def api_trend():
    return jsonify(db.get_last_7_days_trend())


@app.route("/api/course-breakdown")
def api_course_breakdown():
    return jsonify(db.get_course_breakdown())


@app.route("/api/attendance")
def api_attendance_list():
    day = request.args.get("date") or None
    course = request.args.get("course") or None
    student_id = request.args.get("student_id") or None
    
    # If user is a student, lock search to their own student_id
    if session.get("role") == "student":
        student_id = session.get("student_id")

    return jsonify(db.list_attendance(day=day, course=course, student_id=student_id))


@app.route("/api/attendance.csv")
def api_attendance_csv():
    student_id = request.args.get("student_id") or None
    
    # If user is a student, lock export to their own student_id
    if session.get("role") == "student":
        student_id = session.get("student_id")

    rows = db.list_attendance(
        day=request.args.get("date") or None,
        course=request.args.get("course") or None,
        student_id=student_id,
        limit=100000,
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Student ID", "Name", "Course", "Date", "Time", "Confidence (%)", "Status", "Device"])
    for r in rows:
        writer.writerow([r["student_id"], r["full_name"], r["course"], r["date"],
                          r["time"], r["confidence"], r["status"], r["device_id"]])
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=attendance_export.csv"},
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)

