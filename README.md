# Verascan — Face Recognition Attendance Management System

Verascan is a polished Flask prototype for webcam-driven attendance tracking.
The system detects and recognizes registered student faces in real time, logs attendance events to a database, and exposes dashboard analytics plus CSV export for audit purposes.

## Features

- **Student registration** via browser webcam
- **Local face recognition** using OpenCV Haar Cascade + LBPH
- **Manual attendance confirmation** for reliable logging
- **Dashboard analytics** with daily attendance, confidence, and course breakdown
- **Report filtering** by date, course, or student ID
- **CSV export** for institutional records
- **Recognition audit trail** logging every scan event

## Project structure

```
face_attendance/
├── app.py               Flask app routes and JSON API endpoints
├── database.py          SQLite data layer and analytics queries
├── face_utils.py        Face detection, LBPH training, and recognition logic
├── requirements.txt     Python dependencies
├── templates/           Jinja2 views (dashboard, register, attendance, students, reports)
├── static/
│   ├── css/style.css    Green/white UI theme and components
│   └── js/main.js       Shared browser helpers for webcam capture and API calls
└── data/
    ├── faces/           Persisted face sample images by student ID
    └── db/              SQLite database and trained LBPH model files
```

## Requirements

- Python 3.10 or newer
- Webcam-enabled browser (Chrome, Edge, Firefox)
- `pip` package manager

## Setup

1. Create and activate a virtual environment:

```powershell
python -m venv venv
venv\Scripts\activate
```

2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Start the app:

```powershell
python app.py
```

4. Open the browser at **http://localhost:5000**.

> Allow camera permission when prompted for the Register and Attendance pages.

## Application workflow

### 1. Register a student

- Visit `/register`
- Enter `Student ID`, `Full name`, `Course`, and optional `Email`
- Capture 5 live face samples in the browser feed
- Train the recognition model after samples are captured

### 2. Train the model

- Click **Train recognition model**
- The app retrains LBPH on all stored face samples
- Training is required whenever new students are registered

### 3. Take attendance

- Visit `/attendance`
- Point the camera at a student face
- The app scans the frame automatically every ~1.4 seconds
- Recognition results show confidence, decision, and match details
- Confirm the attendance event manually

### 4. Dashboard

- Visit `/`
- Review total registered students and present today
- Inspect average confidence, flagged scans, and attendance trend
- See attendance totals by course

### 5. Reports

- Visit `/reports`
- Filter logs by date, course, or student ID
- Download filtered attendance records as CSV

## Technical notes

- LBPH acceptance threshold is configured in `face_utils.py` as `CONFIDENCE_ACCEPT_THRESHOLD`.
- The app converts LBPH distance to a 0–100% confidence score for user-facing explainability.
- Attendance records are stored in SQLite at `data/db/attendance.db`.
- `recognition_events` logs every scan, including low-confidence or rejected matches.

## Limitations and future work

- Does not implement liveness detection or anti-spoofing.
- Uses a single webcam frame per scan, so printed photos could theoretically be presented as a spoof.
- The storage layer is SQLite for prototype use; the schema is portable to MySQL for production.
- Future upgrades could include a CNN embedding model, multi-camera support, and biometric liveness checks.

## Submission checklist

- [x] Install dependencies from `requirements.txt`
- [x] Start the app and open `http://localhost:5000`
- [x] Register a student and capture 5 face samples
- [x] Train the LBPH recognition model
- [x] Take attendance and confirm logging for a recognized student
- [x] View dashboard analytics and export report CSV
- [x] Ensure README explains setup, usage, and limitations clearly

## Run the app

```powershell
python app.py
```

Then visit **http://localhost:5000**.
