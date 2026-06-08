import os
import uuid
from datetime import datetime, timedelta
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for,
                   flash, send_from_directory, abort, session)
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-me-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'dochost.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB

# Mail config — set these as Railway environment variables
app.config['MAIL_SERVER']   = os.environ.get('MAIL_SERVER',   'smtp.gmail.com')
app.config['MAIL_PORT']     = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS']  = os.environ.get('MAIL_USE_TLS',  'true').lower() == 'true'
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', '')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get(
    'MAIL_DEFAULT_SENDER',
    os.environ.get('MAIL_USERNAME', 'noreply@huttonstrata.com')
)

ALLOWED_EXTENSIONS = {'pdf'}
NOTICE_EXPIRY_DAYS = 45

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db   = SQLAlchemy(app)
mail = Mail(app)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

user_buildings = db.Table('user_buildings',
    db.Column('user_id',     db.Integer, db.ForeignKey('user.id'),     primary_key=True),
    db.Column('building_id', db.Integer, db.ForeignKey('building.id'), primary_key=True),
)


class Building(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(255), nullable=False)
    address    = db.Column(db.String(255), default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    documents  = db.relationship('Document', backref='building', lazy=True)
    notices    = db.relationship('Notice',   backref='building', lazy=True)
    members    = db.relationship('User', secondary=user_buildings, back_populates='buildings')


class User(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(120), nullable=False)
    email      = db.Column(db.String(255), unique=True, nullable=False)
    password   = db.Column(db.String(255), nullable=False)
    role       = db.Column(db.String(20),  nullable=False, default='viewer')
    # roles: admin | editor | viewer | contractor
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    documents  = db.relationship('Document', backref='uploader', lazy=True)
    notices    = db.relationship('Notice',   backref='poster',   lazy=True)
    buildings  = db.relationship('Building', secondary=user_buildings, back_populates='members')


class Document(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    title         = db.Column(db.String(255), nullable=False)
    description   = db.Column(db.Text, default='')
    filename      = db.Column(db.String(255), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    min_role      = db.Column(db.String(20),  nullable=False, default='viewer')
    building_id   = db.Column(db.Integer, db.ForeignKey('building.id'), nullable=True)
    uploaded_by   = db.Column(db.Integer, db.ForeignKey('user.id'),     nullable=False)
    uploaded_at   = db.Column(db.DateTime, default=datetime.utcnow)


class Notice(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    title       = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, default='')
    work_date   = db.Column(db.String(100), default='')   # free-text date / date range
    building_id = db.Column(db.Integer, db.ForeignKey('building.id'), nullable=False)
    posted_by   = db.Column(db.Integer, db.ForeignKey('user.id'),     nullable=False)
    posted_at   = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at  = db.Column(db.DateTime, nullable=False)  # posted_at + 45 days


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
ROLE_RANK = {'viewer': 1, 'editor': 2, 'admin': 3, 'contractor': 0}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def current_user():
    uid = session.get('user_id')
    if uid:
        return db.session.get(User, uid)
    return None

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user():
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            user = current_user()
            if not user or user.role not in roles:
                abort(403)
            return f(*args, **kwargs)
        return decorated
    return decorator

def can_access_doc(user, doc):
    if user.role in ('admin', 'editor'):
        return True
    if user.role == 'contractor':
        return False
    # Viewer
    if ROLE_RANK.get(user.role, 0) < ROLE_RANK.get(doc.min_role, 1):
        return False
    if doc.building_id is None:
        return False
    return any(b.id == doc.building_id for b in user.buildings)

def purge_expired_notices():
    """Delete notices older than 45 days. Called on each page load."""
    expired = Notice.query.filter(Notice.expires_at <= datetime.utcnow()).all()
    for n in expired:
        db.session.delete(n)
    if expired:
        db.session.commit()

def send_notice_emails(notice, building):
    """Email all viewer members of the building about a new contractor notice."""
    if not app.config.get('MAIL_USERNAME'):
        return  # email not configured — skip silently
    recipients = [u.email for u in building.members if u.role == 'viewer' and u.email]
    if not recipients:
        return
    subject = f"[{building.name}] Work Notice: {notice.title}"
    body = f"""Hello,

A new work notice has been posted for {building.name}.

Notice: {notice.title}
Date of Work: {notice.work_date or 'See description'}
Details: {notice.description or 'No additional details provided.'}

Posted: {notice.posted_at.strftime('%B %d, %Y at %I:%M %p')}

This notice will be automatically removed after {NOTICE_EXPIRY_DAYS} days.

---
Hutton Condominium Services Ltd.
This email was sent because you are a registered owner at {building.name}.
Your email address is used solely to notify you of work being performed in your building.
"""
    try:
        msg = Message(subject=subject, recipients=recipients, body=body)
        mail.send(msg)
    except Exception as e:
        app.logger.warning(f"Email send failed: {e}")

@app.context_processor
def inject_user():
    return dict(user=current_user(), role_rank=ROLE_RANK)

# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------
@app.route('/')
def index():
    user = current_user()
    if not user:
        return redirect(url_for('login'))
    if user.role == 'contractor':
        return redirect(url_for('contractor_dashboard'))
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user():
        return redirect(url_for('index'))
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            if user.role == 'contractor':
                return redirect(url_for('contractor_dashboard'))
            return redirect(url_for('dashboard'))
        flash('Invalid email or password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ---------------------------------------------------------------------------
# Dashboard (staff + viewers)
# ---------------------------------------------------------------------------
@app.route('/dashboard')
@login_required
def dashboard():
    user = current_user()
    if user.role == 'contractor':
        return redirect(url_for('contractor_dashboard'))
    purge_expired_notices()
    if user.role in ('admin', 'editor'):
        buildings        = Building.query.order_by(Building.name).all()
        selected_bid     = request.args.get('building', type=int)
        if selected_bid:
            docs              = Document.query.filter_by(building_id=selected_bid)\
                                              .order_by(Document.uploaded_at.desc()).all()
            notices           = Notice.query.filter_by(building_id=selected_bid)\
                                            .order_by(Notice.posted_at.desc()).all()
            selected_building = db.session.get(Building, selected_bid)
        else:
            docs              = Document.query.order_by(Document.uploaded_at.desc()).all()
            notices           = Notice.query.order_by(Notice.posted_at.desc()).all()
            selected_building = None
        return render_template('dashboard.html', documents=docs, notices=notices,
                               buildings=buildings, selected_building=selected_building)
    else:
        my_building_ids = [b.id for b in user.buildings]
        docs = Document.query.filter(
            Document.building_id.in_(my_building_ids)
        ).order_by(Document.uploaded_at.desc()).all()
        accessible = [d for d in docs if can_access_doc(user, d)]
        notices = Notice.query.filter(
            Notice.building_id.in_(my_building_ids)
        ).order_by(Notice.posted_at.desc()).all()
        return render_template('dashboard.html', documents=accessible, notices=notices,
                               buildings=user.buildings, selected_building=None)

# ---------------------------------------------------------------------------
# Contractor portal
# ---------------------------------------------------------------------------
@app.route('/contractor', methods=['GET', 'POST'])
@login_required
@role_required('contractor', 'admin', 'editor')
def contractor_dashboard():
    user      = current_user()
    purge_expired_notices()

    # Contractors only see their assigned buildings; staff see all
    if user.role in ('admin', 'editor'):
        buildings = Building.query.order_by(Building.name).all()
    else:
        buildings = user.buildings

    if request.method == 'POST':
        title       = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        work_date   = request.form.get('work_date', '').strip()
        building_id = request.form.get('building_id', type=int)

        if not title or not building_id:
            flash('Notice title and building are required.', 'danger')
            return redirect(url_for('contractor_dashboard'))

        building = db.session.get(Building, building_id)
        if not building:
            abort(404)

        # Contractors can only post to their assigned buildings
        if user.role == 'contractor' and building not in user.buildings:
            abort(403)

        notice = Notice(
            title=title,
            description=description,
            work_date=work_date,
            building_id=building_id,
            posted_by=user.id,
            expires_at=datetime.utcnow() + timedelta(days=NOTICE_EXPIRY_DAYS),
        )
        db.session.add(notice)
        db.session.commit()

        send_notice_emails(notice, building)
        flash(f'Notice posted. All owners at {building.name} have been notified by email.', 'success')
        return redirect(url_for('contractor_dashboard'))

    # Show recent notices for this contractor's buildings
    if user.role in ('admin', 'editor'):
        recent_notices = Notice.query.order_by(Notice.posted_at.desc()).limit(50).all()
    else:
        bids = [b.id for b in buildings]
        recent_notices = Notice.query.filter(Notice.building_id.in_(bids))\
                                     .order_by(Notice.posted_at.desc()).all()

    return render_template('contractor_dashboard.html',
                           buildings=buildings, notices=recent_notices)

@app.route('/notices/<int:notice_id>/delete', methods=['POST'])
@login_required
@role_required('admin')
def delete_notice(notice_id):
    notice = Notice.query.get_or_404(notice_id)
    db.session.delete(notice)
    db.session.commit()
    flash('Notice deleted.', 'success')
    return redirect(request.referrer or url_for('dashboard'))

# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
@app.route('/upload', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'editor')
def upload():
    buildings = Building.query.order_by(Building.name).all()
    if request.method == 'POST':
        title       = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        min_role    = request.form.get('min_role', 'viewer')
        building_id = request.form.get('building_id', type=int)
        file        = request.files.get('file')

        if not title:
            flash('Title is required.', 'danger')
            return redirect(url_for('upload'))
        if not file or file.filename == '':
            flash('Please select a PDF file.', 'danger')
            return redirect(url_for('upload'))
        if not allowed_file(file.filename):
            flash('Only PDF files are allowed.', 'danger')
            return redirect(url_for('upload'))

        user = current_user()
        if ROLE_RANK.get(min_role, 0) > ROLE_RANK.get(user.role, 0):
            min_role = user.role

        original_name = secure_filename(file.filename)
        stored_name   = str(uuid.uuid4()) + '.pdf'
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], stored_name))

        doc = Document(
            title=title, description=description,
            filename=stored_name, original_name=original_name,
            min_role=min_role, building_id=building_id or None,
            uploaded_by=user.id,
        )
        db.session.add(doc)
        db.session.commit()
        flash(f'"{title}" uploaded successfully.', 'success')
        return redirect(url_for('dashboard'))

    return render_template('upload.html', buildings=buildings)

@app.route('/docs/<int:doc_id>/view')
@login_required
def view_doc(doc_id):
    doc  = Document.query.get_or_404(doc_id)
    user = current_user()
    if not can_access_doc(user, doc):
        abort(403)
    return render_template('view_doc.html', doc=doc)

@app.route('/docs/<int:doc_id>/download')
@login_required
def download_doc(doc_id):
    doc  = Document.query.get_or_404(doc_id)
    user = current_user()
    if not can_access_doc(user, doc):
        abort(403)
    return send_from_directory(app.config['UPLOAD_FOLDER'], doc.filename,
                               as_attachment=True, download_name=doc.original_name)

@app.route('/docs/<int:doc_id>/file')
@login_required
def serve_doc(doc_id):
    doc  = Document.query.get_or_404(doc_id)
    user = current_user()
    if not can_access_doc(user, doc):
        abort(403)
    return send_from_directory(app.config['UPLOAD_FOLDER'], doc.filename)

@app.route('/docs/<int:doc_id>/delete', methods=['POST'])
@login_required
@role_required('admin', 'editor')
def delete_doc(doc_id):
    doc  = Document.query.get_or_404(doc_id)
    user = current_user()
    if user.role == 'editor' and doc.uploaded_by != user.id:
        abort(403)
    try:
        os.remove(os.path.join(app.config['UPLOAD_FOLDER'], doc.filename))
    except FileNotFoundError:
        pass
    db.session.delete(doc)
    db.session.commit()
    flash(f'"{doc.title}" deleted.', 'success')
    return redirect(url_for('dashboard'))

# ---------------------------------------------------------------------------
# Admin — Buildings
# ---------------------------------------------------------------------------
@app.route('/admin/buildings')
@login_required
@role_required('admin')
def admin_buildings():
    buildings = Building.query.order_by(Building.name).all()
    return render_template('admin_buildings.html', buildings=buildings)

@app.route('/admin/buildings/new', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def admin_new_building():
    if request.method == 'POST':
        name    = request.form.get('name', '').strip()
        address = request.form.get('address', '').strip()
        if not name:
            flash('Building name is required.', 'danger')
            return redirect(url_for('admin_new_building'))
        b = Building(name=name, address=address)
        db.session.add(b)
        db.session.commit()
        flash(f'Building "{name}" added.', 'success')
        return redirect(url_for('admin_buildings'))
    return render_template('admin_new_building.html')

@app.route('/admin/buildings/<int:building_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def admin_edit_building(building_id):
    b = Building.query.get_or_404(building_id)
    if request.method == 'POST':
        b.name    = request.form.get('name', b.name).strip()
        b.address = request.form.get('address', b.address).strip()
        db.session.commit()
        flash(f'Building "{b.name}" updated.', 'success')
        return redirect(url_for('admin_buildings'))
    return render_template('admin_edit_building.html', building=b)

@app.route('/admin/buildings/<int:building_id>/delete', methods=['POST'])
@login_required
@role_required('admin')
def admin_delete_building(building_id):
    b = Building.query.get_or_404(building_id)
    if b.documents:
        flash(f'Cannot delete "{b.name}" — it has documents. Remove them first.', 'danger')
        return redirect(url_for('admin_buildings'))
    db.session.delete(b)
    db.session.commit()
    flash(f'Building "{b.name}" deleted.', 'success')
    return redirect(url_for('admin_buildings'))

# ---------------------------------------------------------------------------
# Admin — Users
# ---------------------------------------------------------------------------
@app.route('/admin/users')
@login_required
@role_required('admin')
def admin_users():
    users = User.query.order_by(User.name).all()
    return render_template('admin_users.html', users=users)

@app.route('/admin/users/new', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def admin_new_user():
    buildings = Building.query.order_by(Building.name).all()
    if request.method == 'POST':
        name     = request.form.get('name', '').strip()
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        role     = request.form.get('role', 'viewer')
        bids     = request.form.getlist('building_ids', type=int)

        if not name or not email or not password:
            flash('All fields are required.', 'danger')
            return redirect(url_for('admin_new_user'))
        if User.query.filter_by(email=email).first():
            flash('A user with that email already exists.', 'danger')
            return redirect(url_for('admin_new_user'))

        user = User(name=name, email=email,
                    password=generate_password_hash(password), role=role)
        if role in ('viewer', 'contractor') and bids:
            user.buildings = Building.query.filter(Building.id.in_(bids)).all()
        db.session.add(user)
        db.session.commit()
        flash(f'User "{name}" created.', 'success')
        return redirect(url_for('admin_users'))

    return render_template('admin_new_user.html', buildings=buildings)

@app.route('/admin/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def admin_edit_user(user_id):
    target    = User.query.get_or_404(user_id)
    buildings = Building.query.order_by(Building.name).all()
    if request.method == 'POST':
        target.name  = request.form.get('name', target.name).strip()
        target.email = request.form.get('email', target.email).strip().lower()
        target.role  = request.form.get('role', target.role)
        new_password = request.form.get('password', '').strip()
        if new_password:
            target.password = generate_password_hash(new_password)
        bids = request.form.getlist('building_ids', type=int)
        if target.role in ('viewer', 'contractor'):
            target.buildings = Building.query.filter(Building.id.in_(bids)).all()
        else:
            target.buildings = []
        db.session.commit()
        flash(f'User "{target.name}" updated.', 'success')
        return redirect(url_for('admin_users'))
    return render_template('admin_edit_user.html', target=target, buildings=buildings)

@app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@login_required
@role_required('admin')
def admin_delete_user(user_id):
    me = current_user()
    if me.id == user_id:
        flash("You can't delete your own account.", 'danger')
        return redirect(url_for('admin_users'))
    target = User.query.get_or_404(user_id)
    db.session.delete(target)
    db.session.commit()
    flash(f'User "{target.name}" deleted.', 'success')
    return redirect(url_for('admin_users'))

# ---------------------------------------------------------------------------
# Error pages
# ---------------------------------------------------------------------------
@app.errorhandler(403)
def forbidden(e):
    return render_template('error.html', code=403,
                           message="You don't have permission to access this page."), 403

@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', code=404,
                           message="Page or document not found."), 404

# ---------------------------------------------------------------------------
# Init DB + default admin
# ---------------------------------------------------------------------------
def init_db():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(email='admin@example.com').first():
            admin = User(
                name='Admin',
                email='admin@example.com',
                password=generate_password_hash('admin123'),
                role='admin',
            )
            db.session.add(admin)
            db.session.commit()
            print("Default admin created: admin@example.com / admin123")
            print("IMPORTANT: Change this password immediately after first login!")

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
