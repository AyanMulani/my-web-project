import os, datetime, io, csv, hashlib, secrets
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import pandas as pd

# ------------------ BASIC CONFIG ------------------

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-hr-key')

# ------------------ DATABASE CONFIG (RENDER SAFE) ------------------

DATABASE_URL = os.environ.get("DATABASE_URL")

# Fix old postgres:// URLs if any
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# PostgreSQL on Render, SQLite locally
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL or 'sqlite:///payroll_hr.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# ------------------ OTHER CONFIG ------------------

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 4 * 1024 * 1024

db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ------------------ MODELS ------------------

class Admin(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(50), default='admin')

class Department(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)

class Role(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)

# ------------------ LOGIN ------------------

@login_manager.user_loader
def load_user(user_id):
    return Admin.query.get(int(user_id))

# ------------------ ROUTES ------------------

@app.route("/")
def index():
    return "Payroll HR App is LIVE 🚀"

# OPTIONAL: run once after first successful deploy, then DELETE
@app.route("/init-db")
def init_db():
    db.create_all()
    return "Database initialized successfully"

# ------------------ MAIN ------------------

if __name__ == "__main__":
    app.run(debug=True)
