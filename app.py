import os, datetime, io, csv, secrets
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvasimport os, datetime, io, csv, secrets
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# ================= BASIC CONFIG =================

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    "DATABASE_URL",
    "sqlite:///payroll_hr.db"
)

# Fix for Render PostgreSQL (very important)
if app.config["SQLALCHEMY_DATABASE_URI"].startswith("postgres://"):
    app.config["SQLALCHEMY_DATABASE_URI"] = app.config["SQLALCHEMY_DATABASE_URI"].replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ================= MODELS =================

class Admin(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(50), default='admin')  # superadmin/admin/employee
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=True)


class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    emp_code = db.Column(db.String(64), unique=True, nullable=False)
    first_name = db.Column(db.String(200))
    last_name = db.Column(db.String(200))
    email = db.Column(db.String(120))
    basic_salary = db.Column(db.Float, default=0.0)


class LeaveRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    reason = db.Column(db.Text)
    status = db.Column(db.String(30), default='pending')


class Payroll(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    month = db.Column(db.String(20))
    year = db.Column(db.Integer)
    net_salary = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)


# ================= LOGIN MANAGER =================

@login_manager.user_loader
def load_user(user_id):
    return Admin.query.get(int(user_id))


def hash_password(password):
    return generate_password_hash(password)


def verify_password(hash_val, password):
    return check_password_hash(hash_val, password)


# ================= AUTO DATABASE INIT (FOR RENDER) =================

with app.app_context():
    db.create_all()

    # Create default superadmin if not exists
    if not Admin.query.filter_by(username="admin").first():
        admin = Admin(
            username="admin",
            password_hash=hash_password("admin"),
            role="superadmin"
        )
        db.session.add(admin)
        db.session.commit()

# ================= LOGIN ROUTES =================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form.get('username')
        p = request.form.get('password')

        user = Admin.query.filter_by(username=u).first()

        if user and verify_password(user.password_hash, p):
            login_user(user)

            if user.role == "employee":
                return redirect(url_for('employee_dashboard'))
            else:
                return redirect(url_for('index'))

        flash("Invalid Credentials", "danger")

    return render_template('login.html')


@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))


# ================= DASHBOARDS =================

@app.route('/')
@login_required
def index():
    if current_user.role == "employee":
        return redirect(url_for('employee_dashboard'))

    employees = Employee.query.all()
    payrolls = Payroll.query.order_by(Payroll.id.desc()).all()

    return render_template('index.html', employees=employees, payrolls=payrolls)


@app.route('/employee/dashboard')
@login_required
def employee_dashboard():
    if current_user.role != "employee":
        return redirect(url_for('index'))

    emp = Employee.query.get(current_user.employee_id)
    leaves = LeaveRequest.query.filter_by(employee_id=emp.id).all()
    payrolls = Payroll.query.filter_by(employee_id=emp.id).all()

    return render_template(
        'employee_dashboard.html',
        employee=emp,
        leaves=leaves,
        payrolls=payrolls
    )


# ================= EMPLOYEE CREATE =================

@app.route('/employee/add', methods=['POST'])
@login_required
def add_employee():
    if current_user.role == "employee":
        return jsonify({'error': 'Not allowed'}), 403

    code = request.form.get('emp_code')
    email = request.form.get('email')

    emp = Employee(
        emp_code=code,
        first_name=request.form.get('first_name'),
        last_name=request.form.get('last_name'),
        email=email,
        basic_salary=float(request.form.get('basic_salary') or 0)
    )

    db.session.add(emp)
    db.session.commit()

    # Auto create employee login
    emp_user = Admin(
        username=email,
        password_hash=hash_password("1234"),
        role="employee",
        employee_id=emp.id
    )
    db.session.add(emp_user)
    db.session.commit()

    return jsonify({'ok': True})


# ================= EMPLOYEE LEAVE =================

@app.route('/employee/leave', methods=['POST'])
@login_required
def employee_leave():
    if current_user.role != "employee":
        return redirect(url_for('index'))

    lr = LeaveRequest(
        employee_id=current_user.employee_id,
        start_date=datetime.date.fromisoformat(request.form.get('start_date')),
        end_date=datetime.date.fromisoformat(request.form.get('end_date')),
        reason=request.form.get('reason')
    )

    db.session.add(lr)
    db.session.commit()

    return redirect(url_for('employee_dashboard'))


@app.route('/leave/<int:lid>/decide', methods=['POST'])
@login_required
def leave_decide(lid):
    if current_user.role == "employee":
        return jsonify({'error': 'Not allowed'}), 403

    lr = LeaveRequest.query.get_or_404(lid)
    lr.status = request.form.get('action')
    db.session.commit()

    return jsonify({'ok': True})


# ================= RUN =================

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
import pandas as pd

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY','dev-hr-key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL","sqlite:///payroll_hr.db")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 4 * 1024 * 1024

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ================= MODELS =================

class Admin(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(50), default='admin')
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=True)


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
    department_id = db.Column(db.Integer, db.ForeignKey('department.id'))
    role_id = db.Column(db.Integer, db.ForeignKey('role.id'))
    basic_salary = db.Column(db.Float, default=0.0)
    contact = db.Column(db.String(80))
    email = db.Column(db.String(120))
    address = db.Column(db.Text)
    photo = db.Column(db.String(300))

    department = db.relationship('Department', backref=db.backref('employees', lazy=True))
    role = db.relationship('Role', backref=db.backref('employees', lazy=True))


class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    check_in = db.Column(db.Time)
    check_out = db.Column(db.Time)
    status = db.Column(db.String(30), default='present')
    employee = db.relationship('Employee', backref=db.backref('attendances', lazy=True))


class LeaveRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    reason = db.Column(db.Text)
    status = db.Column(db.String(30), default='pending')
    employee = db.relationship('Employee', backref=db.backref('leaves', lazy=True))


class Payroll(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    month = db.Column(db.String(20))
    year = db.Column(db.Integer)
    net_salary = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    employee = db.relationship('Employee', backref=db.backref('payrolls', lazy=True))


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user = db.Column(db.String(80))
    action = db.Column(db.String(200))
    ts = db.Column(db.DateTime, default=datetime.datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return Admin.query.get(int(user_id))

def hash_password(password):
    return generate_password_hash(password)

def verify_password(hash_val, password):
    return check_password_hash(hash_val, password)

def log_action(user, action):
    db.session.add(AuditLog(user=user, action=action))
    db.session.commit()

# ================= LOGIN =================

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        u = request.form.get('username')
        p = request.form.get('password')
        user = Admin.query.filter_by(username=u).first()

        if user and verify_password(user.password_hash, p):
            login_user(user)
            log_action(user.username, 'login')

            if user.role == 'employee':
                return redirect(url_for('employee_dashboard'))
            else:
                return redirect(url_for('index'))

        flash('Invalid credentials','danger')

    return render_template('login.html')

@app.route('/employee/dashboard')
@login_required
def employee_dashboard():
    if current_user.role != 'employee':
        return redirect(url_for('index'))

    emp = Employee.query.get(current_user.employee_id)
    leaves = LeaveRequest.query.filter_by(employee_id=emp.id).order_by(LeaveRequest.id.desc()).all()
    payrolls = Payroll.query.filter_by(employee_id=emp.id).order_by(Payroll.id.desc()).all()

    return render_template('employee_dashboard.html',
                           employee=emp,
                           leaves=leaves,
                           payrolls=payrolls)

@app.route('/logout')
def logout():
    if current_user.is_authenticated:
        log_action(current_user.username, 'logout')
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    if current_user.role == 'employee':
        return redirect(url_for('employee_dashboard'))

    employees = Employee.query.order_by(Employee.id.desc()).all()
    payrolls = Payroll.query.order_by(Payroll.id.desc()).limit(50).all()

    return render_template('index.html',
                           employees=employees,
                           payrolls=payrolls,
                           departments=Department.query.all(),
                           roles=Role.query.all())

# ================= AUTO EMPLOYEE LOGIN =================

@app.route('/employee/add', methods=['POST'])
@login_required
def add_employee():
    f = request.form
    code = f.get('emp_code','').strip()
    if not code:
        return jsonify({'ok':False,'error':'emp_code required'}),400

    emp = Employee.query.filter_by(emp_code=code).first()
    if emp:
        return jsonify({'ok':False,'error':'Employee exists'}),400

    emp = Employee(
        emp_code=code,
        first_name=f.get('first_name'),
        last_name=f.get('last_name'),
        contact=f.get('contact'),
        email=f.get('email'),
        address=f.get('address'),
        basic_salary=float(f.get('basic_salary') or 0.0)
    )

    db.session.add(emp)
    db.session.commit()

    if emp.email and not Admin.query.filter_by(username=emp.email).first():
        emp_user = Admin(
            username=emp.email,
            password_hash=hash_password("1234"),
            role='employee',
            employee_id=emp.id
        )
        db.session.add(emp_user)
        db.session.commit()

    log_action(current_user.username, f'create employee {code}')
    return jsonify({'ok':True,'created':True})

# ================= EMPLOYEE LEAVE =================

@app.route('/employee/leave', methods=['POST'])
@login_required
def employee_leave():
    if current_user.role != 'employee':
        return jsonify({'ok':False}),403

    s = datetime.date.fromisoformat(request.form.get('start_date'))
    e = datetime.date.fromisoformat(request.form.get('end_date'))

    lr = LeaveRequest(
        employee_id=current_user.employee_id,
        start_date=s,
        end_date=e,
        reason=request.form.get('reason')
    )

    db.session.add(lr)
    db.session.commit()

    return redirect(url_for('employee_dashboard'))

@app.route('/leave/<int:lid>/decide', methods=['POST'])
@login_required
def leave_decide(lid):
    if current_user.role == 'employee':
        return jsonify({'ok':False,'error':'not allowed'}),403

    lr = LeaveRequest.query.get_or_404(lid)
    action = request.form.get('action')
    lr.status = action
    db.session.commit()
    return jsonify({'ok':True})

# ================= RUN =================

if __name__ == '__main__':
    with app.app_context():
        db.create_all()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
