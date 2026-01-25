\
import os, datetime, io, csv, hashlib, secrets
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import pandas as pd

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY','dev-hr-key')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///payroll_hr.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 4 * 1024 * 1024

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Models
class Admin(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(50), default='admin')  # superadmin/admin/hr

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
    department_id = db.Column(db.Integer, db.ForeignKey('department.id'), nullable=True)
    role_id = db.Column(db.Integer, db.ForeignKey('role.id'), nullable=True)
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
    status = db.Column(db.String(30), default='present')  # present/absent/leave
    employee = db.relationship('Employee', backref=db.backref('attendances', lazy=True))

class LeaveRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    reason = db.Column(db.Text)
    status = db.Column(db.String(30), default='pending')  # pending/approved/rejected
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
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def log_action(user, action):
    db.session.add(AuditLog(user=user, action=action))
    db.session.commit()

@app.route('/init-db')
def init_db():
    db.create_all()
    # create default admin
    if not Admin.query.filter_by(username='admin').first():
        a = Admin(username='admin', password_hash=hash_password('admin'), role='superadmin')
        db.session.add(a); db.session.commit()
    # sample depts/roles
    if not Department.query.first():
        db.session.add_all([Department(name='HR'), Department(name='IT'), Department(name='Finance')]); db.session.commit()
    if not Role.query.first():
        db.session.add_all([Role(name='Developer'), Role(name='Manager'), Role(name='Accountant')]); db.session.commit()
    return 'initialized'

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        u = request.form.get('username'); p = request.form.get('password')
        user = Admin.query.filter_by(username=u).first()
        if user and user.password_hash == hash_password(p):
            login_user(user)
            log_action(user.username, 'login')
            return redirect(url_for('index'))
        flash('Invalid credentials','danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    if current_user.is_authenticated:
        log_action(current_user.username, 'logout')
    logout_user(); return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    employees = Employee.query.order_by(Employee.id.desc()).all()
    payrolls = Payroll.query.order_by(Payroll.id.desc()).limit(50).all()
    return render_template('index.html', employees=employees, payrolls=payrolls, departments=Department.query.all(), roles=Role.query.all())

# Employee CRUD + photo upload
@app.route('/employee/add', methods=['POST'])
@login_required
def add_employee():
    f = request.form
    code = f.get('emp_code','').strip()
    if not code: return jsonify({'ok':False,'error':'emp_code required'}),400
    emp = Employee.query.filter_by(emp_code=code).first()
    photo_file = request.files.get('photo')
    filename = None
    if photo_file and photo_file.filename:
        filename = secure_filename(f"{code}_{secrets.token_hex(6)}_{photo_file.filename}")
        photo_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    if emp:
        # update
        emp.first_name = f.get('first_name'); emp.last_name = f.get('last_name')
        emp.contact = f.get('contact'); emp.email = f.get('email'); emp.address = f.get('address')
        if f.get('department_id'): emp.department_id = int(f.get('department_id'))
        if f.get('role_id'): emp.role_id = int(f.get('role_id'))
        if f.get('basic_salary'): emp.basic_salary = float(f.get('basic_salary') or 0)
        if filename: emp.photo = filename
        db.session.commit()
        log_action(current_user.username, f'update employee {code}')
        return jsonify({'ok':True,'updated':True,'emp_code':code})
    else:
        emp = Employee(emp_code=code, first_name=f.get('first_name'), last_name=f.get('last_name'),
                       contact=f.get('contact'), email=f.get('email'), address=f.get('address'),
                       department_id = int(f.get('department_id')) if f.get('department_id') else None,
                       role_id = int(f.get('role_id')) if f.get('role_id') else None,
                       basic_salary = float(f.get('basic_salary') or 0.0),
                       photo = filename)
        db.session.add(emp); db.session.commit()
        log_action(current_user.username, f'create employee {code}')
        return jsonify({'ok':True,'created':True,'emp_code':code})

@app.route('/employee/search')
@login_required
def search_employee():
    code = request.args.get('code','').strip()
    if not code: return jsonify({'found':False})
    emp = Employee.query.filter_by(emp_code=code).first()
    if not emp:
        try: emp = Employee.query.get(int(code))
        except: emp=None
    if not emp: return jsonify({'found':False})
    data = {'id':emp.id,'emp_code':emp.emp_code,'first_name':emp.first_name,'last_name':emp.last_name,
            'department_id':emp.department_id,'role_id':emp.role_id,'basic_salary':emp.basic_salary,
            'contact':emp.contact,'email':emp.email,'address':emp.address,'photo':emp.photo}
    return jsonify({'found':True,'emp':data})

# Attendance
@app.route('/attendance/checkin', methods=['POST'])
@login_required
def attendance_checkin():
    code = request.form.get('emp_code','').strip()
    date_str = request.form.get('date') or datetime.date.today().isoformat()
    try: d = datetime.date.fromisoformat(date_str)
    except: d = datetime.date.today()
    emp = Employee.query.filter_by(emp_code=code).first()
    if not emp: return jsonify({'ok':False,'error':'employee not found'}),404
    rec = Attendance.query.filter_by(employee_id=emp.id, date=d).first()
    if not rec: rec = Attendance(employee_id=emp.id, date=d, check_in=datetime.datetime.now().time(), status='present'); db.session.add(rec)
    else: rec.check_in = datetime.datetime.now().time()
    db.session.commit(); log_action(current_user.username, f'checkin {code}')
    return jsonify({'ok':True,'msg':'checked in','date':d.isoformat()})

@app.route('/attendance/checkout', methods=['POST'])
@login_required
def attendance_checkout():
    code = request.form.get('emp_code','').strip()
    date_str = request.form.get('date') or datetime.date.today().isoformat()
    try: d = datetime.date.fromisoformat(date_str)
    except: d = datetime.date.today()
    emp = Employee.query.filter_by(emp_code=code).first()
    if not emp: return jsonify({'ok':False,'error':'employee not found'}),404
    rec = Attendance.query.filter_by(employee_id=emp.id, date=d).first()
    if not rec: return jsonify({'ok':False,'error':'no checkin record'}),400
    rec.check_out = datetime.datetime.now().time(); db.session.commit(); log_action(current_user.username, f'checkout {code}')
    return jsonify({'ok':True,'msg':'checked out','date':d.isoformat()})

# Leave requests
@app.route('/leave/request', methods=['POST'])
@login_required
def leave_request():
    f = request.form
    emp = Employee.query.filter_by(emp_code=f.get('emp_code','').strip()).first()
    if not emp: return jsonify({'ok':False,'error':'employee not found'}),404
    try:
        s = datetime.date.fromisoformat(f.get('start_date')); e = datetime.date.fromisoformat(f.get('end_date'))
    except Exception as exc:
        return jsonify({'ok':False,'error':'invalid dates'}),400
    lr = LeaveRequest(employee_id=emp.id, start_date=s, end_date=e, reason=f.get('reason'))
    db.session.add(lr); db.session.commit(); log_action(current_user.username, f'leave request {emp.emp_code}')
    return jsonify({'ok':True,'id':lr.id})

@app.route('/leave/<int:lid>/decide', methods=['POST'])
@login_required
def leave_decide(lid):
    lr = LeaveRequest.query.get_or_404(lid)
    action = request.form.get('action')
    if action not in ('approved','rejected'): return jsonify({'ok':False,'error':'invalid action'}),400
    lr.status = action; db.session.commit(); log_action(current_user.username, f'leave {action} {lr.id}')
    return jsonify({'ok':True})

# Payroll create (simple)
@app.route('/payroll/create', methods=['POST'])
@login_required
def create_payroll():
    f = request.form
    code = f.get('emp_code','').strip()
    emp = Employee.query.filter_by(emp_code=code).first()
    if not emp: return jsonify({'ok':False,'error':'employee not found'}),404
    try:
        month = f.get('month') or ''; year = int(f.get('year') or 0); net = float(f.get('net_salary') or 0)
    except Exception as e: return jsonify({'ok':False,'error':'invalid data'}),400
    p = Payroll(employee_id=emp.id, month=month, year=year, net_salary=net); db.session.add(p); db.session.commit()
    log_action(current_user.username, f'payroll create {emp.emp_code} {month}/{year}')
    return redirect(url_for('index'))

# Reports and exports
@app.route('/export/employees')
@login_required
def export_employees():
    emps = Employee.query.all()
    out = io.StringIO(); w = csv.writer(out); w.writerow(['id','emp_code','first_name','last_name','department','role','basic_salary','contact','email'])
    for e in emps:
        w.writerow([e.id,e.emp_code,e.first_name,e.last_name, e.department.name if e.department else '', e.role.name if e.role else '', e.basic_salary, e.contact,e.email])
    out.seek(0); return send_file(io.BytesIO(out.getvalue().encode('utf-8')), as_attachment=True, download_name='employees.csv', mimetype='text/csv')

@app.route('/export/payrolls')
@login_required
def export_payrolls():
    ps = Payroll.query.all()
    out = io.StringIO(); w = csv.writer(out); w.writerow(['id','employee','month','year','net'])
    for p in ps:
        w.writerow([p.id, p.employee.emp_code, p.month, p.year, p.net_salary])
    out.seek(0); return send_file(io.BytesIO(out.getvalue().encode('utf-8')), as_attachment=True, download_name='payrolls.csv', mimetype='text/csv')

# serve uploads

# Delete employee (removes employee, their attendances, leaves, payrolls, and photo file)
@app.route('/employee/<int:emp_id>/delete', methods=['POST'])
@login_required
def delete_employee(emp_id):
    emp = Employee.query.get_or_404(emp_id)
    # only allow superadmin or hr to delete (admins with any role allowed here)
    # You can adjust permissions if needed (e.g., only superadmin)
    try:
        # remove uploads photo if exists
        if emp.photo:
            try:
                photo_path = os.path.join(app.config['UPLOAD_FOLDER'], emp.photo)
                if os.path.exists(photo_path):
                    os.remove(photo_path)
            except Exception:
                pass
        # delete related records
        Attendance.query.filter_by(employee_id=emp.id).delete()
        LeaveRequest.query.filter_by(employee_id=emp.id).delete()
        Payroll.query.filter_by(employee_id=emp.id).delete()
        # finally delete employee
        db.session.delete(emp)
        db.session.commit()
        log_action(current_user.username, f'delete employee {emp.emp_code}')
        return jsonify({'ok': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/uploads/<path:filename>')
def uploaded_file(filename): return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/static/<path:filename>')
def static_file(filename): return send_from_directory(os.path.join(app.root_path,'static'), filename)

# simple user management page (create additional HR users)
@app.route('/admin/create', methods=['POST'])
@login_required
def admin_create():
    if current_user.role != 'superadmin': return jsonify({'ok':False,'error':'not permitted'}),403
    u = request.form.get('username'); p = request.form.get('password'); r = request.form.get('role') or 'hr'
    if Admin.query.filter_by(username=u).first(): return jsonify({'ok':False,'error':'exists'}),400
    a = Admin(username=u, password_hash=hash_password(p), role=r); db.session.add(a); db.session.commit(); log_action(current_user.username, f'create admin {u}'); return jsonify({'ok':True})

# payroll PDF
@app.route('/payroll/<int:pid>/pdf')
@login_required
def payroll_pdf(pid):
    p = Payroll.query.get_or_404(pid); emp = p.employee
    buf = io.BytesIO(); c = canvas.Canvas(buf, pagesize=A4); x=40; y=A4[1]-60
    c.setFont('Helvetica-Bold',14); c.drawString(x,y,'Salary Slip'); y-=20; c.setFont('Helvetica',10)
    for label,val in [('Employee',f'{emp.emp_code} {emp.first_name} {emp.last_name}'),('Month',f'{p.month}/{p.year}'),('Net',str(p.net_salary))]:
        c.drawString(x,y,f'{label}: {val}'); y-=14
    c.showPage(); c.save(); buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f'pay_{emp.emp_code}_{p.month}_{p.year}.pdf', mimetype='application/pdf')

# helper: password hashing wrapper
def hash_password(p): return hashlib.sha256(p.encode('utf-8')).hexdigest()

# simple API status
@app.route('/status')
def status(): return jsonify({'ok':True,'version':'hr-1.0'})

if __name__ == '__main__':
    with app.app_context(): db.create_all()
    print('DB:', os.path.abspath('payroll_hr.db'), 'uploads:', UPLOAD_FOLDER)
    app.run(debug=True)
from flask import Flask, render_template

app = Flask(__name__)

@app.route("/")
def home():
    return render_template("index.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
