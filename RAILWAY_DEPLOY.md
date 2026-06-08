# How to Put the Hutton Client Portal Online Using Railway

This guide assumes no technical background. Follow each step in order.

---

## What you'll need

- A computer with internet access
- A GitHub account (free) — think of it as a folder in the cloud where your app lives
- The `dochost` folder on your computer

---

## Part 1 — Create a free GitHub account

GitHub is where you'll store the app files. Railway reads from GitHub to run your site.

1. Go to **github.com**
2. Click **Sign up**
3. Enter an email, create a password, choose a username
4. Verify your email when prompted
5. You're in — you don't need to understand anything else about GitHub for this

---

## Part 2 — Upload your app files to GitHub

1. Once logged in to GitHub, click the **+** button in the top-right corner
2. Choose **New repository**
3. Name it something like `hutton-portal`
4. Leave everything else as default
5. Click **Create repository**

Now upload your files:

6. On the next screen, click **uploading an existing file**
7. Open the `dochost` folder on your computer
8. Select **all the files inside it** (app.py, requirements.txt, Procfile, and the `templates` folder)
9. Drag them into the GitHub upload window
10. Scroll down and click **Commit changes**

Your files are now saved in GitHub.

---

## Part 3 — Create a Railway account

1. Go to **railway.app**
2. Click **Start a New Project**
3. Choose **Sign in with GitHub** — this links Railway to the files you just uploaded
4. Approve the connection when prompted

---

## Part 4 — Deploy your app on Railway

1. Once inside Railway, click **New Project**
2. Choose **Deploy from GitHub repo**
3. Select `hutton-portal` from the list
4. Railway will detect it's a Python app automatically
5. Click **Deploy**

Railway will take about 1–2 minutes to set everything up. You'll see a log of activity — that's normal.

---

## Part 5 — Set your secret key

This is a security step that protects your users' login sessions.

1. In Railway, click on your project
2. Click the **Variables** tab
3. Click **New Variable**
4. In the Name field type: `SECRET_KEY`
5. In the Value field, type any long random string of letters and numbers
   (example: `hutton2024xK9mPqR7vL3nW`)
6. Click **Add**
7. Railway will automatically restart your app with this setting

---

## Part 6 — Get your site's web address

1. In Railway, click on your project
2. Click **Settings**
3. Under **Domains**, click **Generate Domain**
4. Railway will give you a web address like `hutton-portal-production.up.railway.app`
5. Open that address in your browser

You should see the Hutton Client Portal login screen.

---

## Part 7 — Log in and set up your admin account

1. Go to your Railway web address
2. Log in with:
   - **Email:** admin@example.com
   - **Password:** admin123
3. Immediately go to **Users** in the top navigation
4. Click **Edit** next to the Admin user
5. Change the email to your real email and set a new password
6. Click **Save**

Your portal is now live and secure.

---

## Part 8 — Share the link with your team

Send your staff the Railway web address. They'll see the login screen and can sign in once you've created accounts for them under **Users → New User**.

---

## When you're ready to go live on your real website

At that point, you (or your web person) will:

1. Move the app to a permanent server, OR keep using Railway (Railway's paid plan is ~$5/month)
2. Add a DNS record pointing `portal.huttonpropertymanagement.com` at the server
3. Update the "Client Portal Login" link in your WordPress menu to the new address

That's it — the app itself doesn't need to change at all.

---

## If something goes wrong

- **Page won't load:** Wait 2 minutes and refresh. Railway sometimes takes a moment on first deploy.
- **Login doesn't work:** Double-check you're using `admin@example.com` and `admin123` exactly.
- **Files are missing after upload:** Make sure you uploaded the contents of the `dochost` folder, not the folder itself.
- **Need help:** Railway has a live support chat at railway.app — tell them "my Python Flask app isn't starting" and they'll help.
