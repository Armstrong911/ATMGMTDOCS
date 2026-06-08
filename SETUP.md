# DocHost — Setup & Deployment Guide

## What you get

- Secure login (no public access)
- Three roles: **Admin**, **Editor**, **Viewer**
- PDF upload, in-browser viewing, and download
- Admin panel to create/edit/delete users
- Runs on your own server — no third-party dependencies

---

## Role permissions

| Action              | Viewer | Editor | Admin |
|---------------------|--------|--------|-------|
| View allowed docs   | ✅     | ✅     | ✅    |
| Download docs       | ✅     | ✅     | ✅    |
| Upload docs         | ❌     | ✅     | ✅    |
| Delete own uploads  | ❌     | ✅     | ✅    |
| Delete any doc      | ❌     | ❌     | ✅    |
| Manage users        | ❌     | ❌     | ✅    |

---

## Step 1 — Get a VPS

Any Linux VPS works (DigitalOcean, Linode, Hetzner, etc.).
Recommended: Ubuntu 22.04, 1 GB RAM minimum.

---

## Step 2 — Install Python

SSH into your server, then:

```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv -y
```

---

## Step 3 — Upload the app

Copy the `dochost/` folder to your server. Using `scp`:

```bash
scp -r dochost/ your-user@your-server-ip:~/dochost
```

Or use an FTP client like FileZilla to transfer the folder.

---

## Step 4 — Install dependencies

```bash
cd ~/dochost
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## Step 5 — Set a secret key

Open `app.py` and find this line near the top:

```python
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-me-in-production')
```

Set it via an environment variable (recommended):

```bash
export SECRET_KEY="some-long-random-string-here"
```

Or replace `'change-me-in-production'` directly in the file with a long random string.

---

## Step 6 — Run the app

```bash
source venv/bin/activate
python app.py
```

This creates the database and a default admin account:

- **Email:** admin@example.com
- **Password:** admin123

**Change this password immediately** by going to Users → Edit after first login.

---

## Step 7 — Run in production with Gunicorn

For a stable production server, use Gunicorn instead of the built-in Flask server:

```bash
source venv/bin/activate
gunicorn -w 4 -b 0.0.0.0:5000 "app:app"
```

To keep it running after you close the terminal:

```bash
nohup gunicorn -w 4 -b 0.0.0.0:5000 "app:app" &
```

---

## Step 8 — (Optional) Set up Nginx as a reverse proxy

This gives you a cleaner URL and lets you use HTTPS.

```bash
sudo apt install nginx -y
```

Create a config file at `/etc/nginx/sites-available/dochost`:

```nginx
server {
    listen 80;
    server_name your-domain.com;

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

Enable it:

```bash
sudo ln -s /etc/nginx/sites-available/dochost /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

---

## Step 9 — (Optional) Add HTTPS with Let's Encrypt

```bash
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d your-domain.com
```

Follow the prompts. Certbot auto-renews certificates.

---

## File structure

```
dochost/
├── app.py              ← Main application
├── requirements.txt    ← Python dependencies
├── dochost.db          ← SQLite database (auto-created)
├── uploads/            ← Stored PDFs (auto-created)
└── templates/          ← HTML pages
    ├── base.html
    ├── login.html
    ├── dashboard.html
    ├── upload.html
    ├── view_doc.html
    ├── admin_users.html
    ├── admin_new_user.html
    ├── admin_edit_user.html
    └── error.html
```

---

## Backup

To back up all your data:

```bash
# Copy the database and uploads folder
cp ~/dochost/dochost.db ~/backup-dochost.db
cp -r ~/dochost/uploads/ ~/backup-uploads/
```

---

## Troubleshooting

**Port 5000 is in use** — change `-b 0.0.0.0:5000` to another port like `5001`.

**Can't upload large files** — increase `MAX_CONTENT_LENGTH` in `app.py` and `client_max_body_size` in nginx config.

**Forgot admin password** — connect to the server and run:

```bash
cd ~/dochost
source venv/bin/activate
python3 -c "
from app import app, db, User
from werkzeug.security import generate_password_hash
with app.app_context():
    u = User.query.filter_by(email='admin@example.com').first()
    u.password = generate_password_hash('newpassword123')
    db.session.commit()
    print('Password reset.')
"
```
