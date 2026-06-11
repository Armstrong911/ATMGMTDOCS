import os, json
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-me-in-production')

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
PORTAL_URL        = os.environ.get('PORTAL_URL', '#')
RESEND_API_KEY    = os.environ.get('RESEND_API_KEY', '')
NOTIFY_EMAIL      = os.environ.get('NOTIFY_EMAIL', 'admin@huttonstrata.com')
MAIL_FROM         = os.environ.get('MAIL_FROM', 'Hutton <onboarding@resend.dev>')

DESTINATIONS = [
    {"name": "Services",                 "url": "/services",      "description": "What Hutton offers, strata management services"},
    {"name": "FAQ",                      "url": "/faq",           "description": "Frequently asked questions about strata living"},
    {"name": "Contact",                  "url": "/contact",       "description": "Contact Hutton — phone, email, office hours, address"},
    {"name": "Maintenance Request",      "url": "/forms/maintenance",  "description": "Submit a maintenance or repair request"},
    {"name": "Owner Registration",       "url": "/forms/registration", "description": "Register as a new strata owner"},
    {"name": "Bylaw Complaint",          "url": "/forms/complaint",    "description": "File a bylaw or rule violation complaint"},
    {"name": "Pre-Authorized Debit",     "url": "/forms/debit",        "description": "Set up automatic strata fee payments"},
    {"name": "Realtor Document Request", "url": "/forms/realtor",      "description": "Realtors requesting Form B or strata documents"},
    {"name": "Legal Document Request",   "url": "/forms/legal",        "description": "Request Form F/B for legal or ownership changes"},
    {"name": "Form K",                   "url": "/forms/form-k",       "description": "Tenant notification form — renting out your unit"},
    {"name": "Strata Documents Request", "url": "/forms/strata-docs",  "description": "Request general strata corporation documents"},
    {"name": "Client Portal",            "url": PORTAL_URL,            "description": "Owner and staff login to access strata documents"},
]

def send_email(subject, body):
    if not RESEND_API_KEY:
        app.logger.info(f"Email (not sent — no API key): {subject}")
        return
    try:
        import resend
        resend.api_key = RESEND_API_KEY
        resend.Emails.send({"from": MAIL_FROM, "to": NOTIFY_EMAIL, "subject": subject, "text": body})
    except Exception as e:
        app.logger.warning(f"Email failed: {e}")

def form_body(form_name, data):
    lines = [f"New {form_name} submission from huttonstrata.com\n"]
    for k, v in data.items():
        lines.append(f"{k.replace('_',' ').title()}: {v}")
    return "\n".join(lines)

# ---------------------------------------------------------------------------
# Main pages
# ---------------------------------------------------------------------------
@app.route('/')
def home():
    return render_template('home.html', portal_url=PORTAL_URL)

@app.route('/services')
def services():
    return render_template('services.html')

@app.route('/faq')
def faq():
    return render_template('faq.html')

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        data = {k: v for k, v in request.form.items()}
        send_email(f"Contact message from {data.get('name','')}: {data.get('subject','')}", form_body("Contact", data))
        return render_template('contact.html', sent=True)
    return render_template('contact.html', sent=False)

# ---------------------------------------------------------------------------
# AI routing
# ---------------------------------------------------------------------------
@app.route('/ask', methods=['POST'])
def ask():
    query = request.json.get('query', '').strip()
    if not query:
        return jsonify({'error': 'No query'}), 400
    if ANTHROPIC_API_KEY:
        return _ai_route(query)
    return _fallback_route(query)

def _ai_route(query):
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        caps = "\n".join(f"- {d['name']}: {d['description']} → {d['url']}" for d in DESTINATIONS)
        system = f"""You are the assistant for Hutton, a strata property management company in Victoria, BC.
Direct visitors to the right page based on what they need.

Available pages:
{caps}

Reply with JSON only:
{{"message": "One short friendly sentence.", "destination_name": "Name", "url": "exact URL", "confidence": "high|medium|low"}}

If unrelated to strata, reply:
{{"message": "I can help with strata questions, forms, documents, and getting in touch with Hutton. What do you need?", "destination_name": null, "url": null, "confidence": "low"}}"""
        r = client.messages.create(model="claude-haiku-4-5-20251001", max_tokens=200, system=system,
                                    messages=[{"role": "user", "content": query}])
        return jsonify(json.loads(r.content[0].text))
    except Exception as e:
        app.logger.warning(f"AI routing failed: {e}")
        return _fallback_route(query)

def _fallback_route(query):
    q = query.lower()
    kw = {
        "maintenance": "Maintenance Request", "repair": "Maintenance Request", "broken": "Maintenance Request",
        "complaint": "Bylaw Complaint", "bylaw": "Bylaw Complaint", "noise": "Bylaw Complaint",
        "register": "Owner Registration", "new owner": "Owner Registration",
        "payment": "Pre-Authorized Debit", "debit": "Pre-Authorized Debit", "fees": "Pre-Authorized Debit",
        "realtor": "Realtor Document Request", "form b": "Realtor Document Request",
        "legal": "Legal Document Request", "form f": "Legal Document Request",
        "form k": "Form K", "tenant": "Form K",
        "strata documents": "Strata Documents Request", "minutes": "Strata Documents Request",
        "contact": "Contact", "phone": "Contact", "hours": "Contact",
        "faq": "FAQ", "question": "FAQ",
        "service": "Services", "manage": "Services",
        "portal": "Client Portal", "login": "Client Portal",
    }
    dest = {d['name']: d for d in DESTINATIONS}
    best, best_score = None, 0
    for keyword, name in kw.items():
        if keyword in q and name in dest:
            score = len(keyword)
            if score > best_score:
                best_score, best = score, dest[name]
    if best:
        return jsonify({"message": "Here's where you need to go.", "destination_name": best['name'], "url": best['url'], "confidence": "medium"})
    return jsonify({"message": "I can help with strata questions, forms, documents, and getting in touch with Hutton. What do you need?", "destination_name": None, "url": None, "confidence": "low"})

# ---------------------------------------------------------------------------
# Forms
# ---------------------------------------------------------------------------
def handle_form(template, form_name, subject_field=None):
    if request.method == 'POST':
        data = {k: v for k, v in request.form.items()}
        subj = f"New {form_name}"
        if subject_field and subject_field in data:
            subj += f" — {data[subject_field]}"
        send_email(subj, form_body(form_name, data))
        return render_template('success.html',
            title="Submitted",
            message=f"Your {form_name.lower()} has been received. We'll be in touch shortly.")
    return render_template(template)

@app.route('/forms/maintenance',  methods=['GET','POST'])
def form_maintenance():  return handle_form('form_maintenance.html',  'Maintenance Request', 'building')

@app.route('/forms/complaint',    methods=['GET','POST'])
def form_complaint():    return handle_form('form_complaint.html',    'Bylaw Complaint', 'building')

@app.route('/forms/registration', methods=['GET','POST'])
def form_registration(): return handle_form('form_registration.html', 'Owner Registration', 'building')

@app.route('/forms/realtor',      methods=['GET','POST'])
def form_realtor():      return handle_form('form_realtor.html',      'Realtor Document Request', 'building')

@app.route('/forms/lender',       methods=['GET','POST'])
def form_lender():       return handle_form('form_lender.html',       'Lender Information Request', 'building')

@app.route('/forms/legal',        methods=['GET','POST'])
def form_legal():        return handle_form('form_legal.html',        'Legal Document Request', 'building')

@app.route('/forms/strata-docs',  methods=['GET','POST'])
def form_strata_docs():  return handle_form('form_strata_docs.html',  'Strata Documents Request', 'building')

@app.route('/forms/debit',        methods=['GET','POST'])
def form_debit():        return handle_form('form_debit.html',        'Pre-Authorized Debit', 'building')

@app.route('/forms/form-k',       methods=['GET','POST'])
def form_k():            return handle_form('form_k.html',            'Form K', 'building')

# ---------------------------------------------------------------------------
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
