HR Payroll - README

This expanded HR payroll package includes:
- Departments and Roles
- Employee photo upload (stored in uploads/)
- Payroll create + PDF payslip generation
- Export employees and payrolls to CSV
- Audit log of actions
- Admin users with hashed passwords
- Simple web UI (Bootstrap) with client-side calculator and receipt preview
- Sample data created via /init-db

Important:
- Reference GUI image included in static/reference_gui.jpg (original path: /mnt/data/gu.jpg)
- To run:
  1. python -m venv venv
  2. .\\venv\\Scripts\\Activate
  3. pip install -r requirements.txt
  4. python app.py
  5. Visit: http://127.0.0.1:5000/init-db to create admin/sample data (admin/admin)
  6. Login: http://127.0.0.1:5000/login (admin/admin)

Files:
- app.py
- templates/login.html, templates/index.html
- static/style.css, static/main.js, static/reference_gui.jpg
- requirements.txt

Uploads are saved to uploads/ directory inside project folder.

