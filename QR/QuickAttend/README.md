# QuickAttend - QR Based Attendance System

Python (Flask) + SQLite + HTML/CSS/JavaScript.

## How to run
1. Install Python 3 (python.org).
2. Open a terminal inside this folder and run:
       pip install -r requirements.txt
       python app.py
3. Open http://127.0.0.1:5000 in your browser.
   The database file (attendance.db) is created automatically.

## Try it
1. Sign up as a Teacher (Email + password) and as a Student (Student ID + password). Use two different browsers (or one normal + one incognito window).
2. Student: Profile -> fill class (e.g. TYCS), division, roll no -> Save.
3. Teacher: Create Session -> fill details -> Generate QR code.
4. Student: Scan -> scan the QR (or type the 6 digit code) -> Present.
5. Teacher: View attendance (this session) or View History (monthly class report + CSV download).

## Using the phone camera
Browsers only allow the camera on localhost or HTTPS. So if the teacher PC runs the site and students open it on their phones over Wi-Fi:
- Option 1: type the 6 digit code shown under the QR (works everywhere).
- Option 2: run with HTTPS:  pip install cryptography   then
      Windows:  set USE_HTTPS=1 && python app.py
      Mac/Linux: USE_HTTPS=1 python app.py
  Open  https://<teacher-pc-ip>:5000  on the phone and accept the browser warning.

## Folder structure
    app.py              all backend code (routes, database, QR logic)
    templates/          HTML pages (Jinja2)
    static/css/         style.css
    static/js/          scan.js (student QR scanner)
    attendance.db       created on first run

## Database tables
- students    (student_id, password_hash, name, class_name, division, roll_no)
- teachers    (name, email, password_hash)
- sessions    (teacher_id, class_name, subject, date, start_time, end_time, qr_seconds, token, token_time, is_active)
- attendance  (session_id, student_id, marked_at)  <- UNIQUE(session_id, student_id) stops double marking

## How the QR works (good for viva)
- Creating a session stores it in the database.
- The teacher page asks the server for a new random 6 digit code every 15 seconds (as in your sketch); the code is turned into a QR image with the `qrcode` library.
- The student's scan sends the code to the server. The server checks: code matches a live session, code is fresh, student's class matches, not already marked.
- Pressing "Present" saves one row in the attendance table.
- Passwords are stored hashed (werkzeug), never as plain text.

## Before submitting
Change app.secret_key in app.py to your own random text.
