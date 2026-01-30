import os, datetime, io, csv, hashlib, secrets
from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, jsonify, send_file, send_from_directory
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user,
    logout_user, login_required, current_user
)
from werkzeug.utils import secure_filename
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# ---------------- BASIC CONFIG ----------------

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-key")

# ---------------- DATABASE (RENDER / POSTGRES READY) ----------------

DATABASE_URL = os.environ.get("DATABASE_URL")

# Fix old postgres:// URLs if any
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# PostgreSQL on Render, SQLite locally
app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL or "sqlite:///payroll_hr.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

# ---------------- MODELS ----------------

class Admin(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(50), default="admin")

class Department(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)

class Role(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)

class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    emp_code = db.Column(db.String(64), unique=True, nullable=False)
    first_name = db.Column(db.String(200))
    last_name = db.Column(db.String(200))
    department_id = db.Column(db.Integer, db.ForeignKey("department.id"))
    role_id = db.Column(db.Integer, db.ForeignKey("role.id"))
    basic_salary = db.Column(db.Float, default=0.0)
    contact = db.Column(db.String(80))
    email = db.Column(db.String(120))
    address = db.Column(db.Text)
    photo = db.Column(db.String(300))

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"))
    date = db.Column(db.Date, nullable=False)
    check_in = db.Column(db.Time)
    check_out = db.Column(db.Time)
    status = db.Column(db.String(30), default="present")

class LeaveRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"))
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    reason = db.Column(db.Text)
    status = db.Column(db.String(30), default="pending")

class Payroll(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"))
    month = db.Column(db.String(20))
    year = db.Column(db.Integer)
    net_salary = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user = db.Column(db.String(80))
    action = db.Column(db.String(200))
    ts = db.Column(db.DateTime, default=datetime.datetime.utcnow)

# ---------------- HELPERS ----------------

@login_manager.user_loader
def load_user(user_id):
    return Admin.query.get(int(user_id))

def hash_password(p):
    return hashlib.sha256(p.encode("utf-8")).hexdigest()

def log_action(user, action):
    db.session.add(AuditLog(user=user, action=action))
    db.session.commit()

# ---------------- ROUTES ----------------

@app.route("/")
@login_required
def index():
    return render_template(
        "index.html",
        employees=Employee.query.all(),
        payrolls=Payroll.query.order_by(Payroll.id.desc()).limit(50),
        departments=Department.query.all(),
        roles=Role.query.all()
    )

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form.get("username")
        p = request.form.get("password")
        user = Admin.query.filter_by(username=u).first()
        if user and user.password_hash == hash_password(p):
            login_user(user)
            log_action(user.username, "login")
            return redirect(url_for("index"))
        flash("Invalid credentials", "danger")
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    log_action(current_user.username, "logout")
    logout_user()
    return redirect(url_for("login"))

# ---------------- INIT DATABASE (RUN ONCE) ----------------

@app.route("/init-db")
def init_db():
    with app.app_context():
        db.create_all()
        if not Admin.query.filter_by(username="admin").first():
            db.session.add(
                Admin(
                    username="admin",
                    password_hash=hash_password("admin"),
                    role="superadmin"
                )
            )
            db.session.commit()
    return "Database initialized"

# ---------------- FILE SERVING ----------------

@app.route("/uploads/<path:filename>")
def uploads(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

@app.route("/status")
def status():
    return jsonify({"ok": True, "app": "Payroll HR", "env": "production"})

# ---------------- ENTRY POINT ----------------
# ❌ DO NOT USE app.run()
# Gunicorn will start this app
