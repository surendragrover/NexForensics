"""
InvestigatorAI v3 - Authentication Routes
"""

import logging
import hashlib
from flask import Blueprint, request, jsonify, render_template, redirect, make_response, redirect, make_response
from datetime import datetime, timedelta

from database import db
from config import current_config
from services.jwt_service import JWTService

logger = logging.getLogger(__name__)
auth_bp = Blueprint('auth', __name__)


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')

    # POST - handle login
    try:
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Login POST received. Content-Type: {request.content_type}")
        _ld = request.get_json(silent=True) or request.form or {}
        logger.info(f"Login attempt for: {_ld.get('email', '') if hasattr(_ld, 'get') else ''}")  # p33: never log passwords
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form

        if not data:
            return jsonify({'error': 'No data provided'}), 400

        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        api_key = data.get('api_key', '')

        if not email or not password:
            return jsonify({'error': 'Email and password required'}), 400

        # Find user
        user = db.fetch_one(
            "SELECT id, email, full_name, role, account_status, api_enabled, password_hash FROM ia_users WHERE email = %s",
            (email,)
        )

        if not user:
            return jsonify({'error': 'Invalid email or password'}), 401

        # Check account status
        if user['account_status'] != 'approved':
            return jsonify({'error': 'Account not approved. Please wait for approval or contact support.'}), 403

        # Verify password
        if user['password_hash']:
            if hash_password(password) != user['password_hash']:
                return jsonify({'error': 'Invalid email or password'}), 401
        else:
            # No password set - cannot login
            return jsonify({'error': 'Password not set. Please reset your password.'}), 401

        # Verify API key if provided
        if api_key:
            key_check = db.fetch_one(
                "SELECT id, status, expires_at FROM ia_api_keys WHERE user_id = %s AND api_key = %s",
                (user['id'], api_key)
            )
            if not key_check:
                return jsonify({'error': 'Invalid API key'}), 401
            if key_check['status'] != 'active':
                return jsonify({'error': 'API key revoked or expired'}), 401
            if key_check['expires_at'] and key_check['expires_at'] < datetime.now():
                return jsonify({'error': 'API key expired'}), 401

        # Check if API access enabled
        if not user['api_enabled']:
            return jsonify({'error': 'API access not enabled for this account'}), 403

        # Generate session token
        import secrets
        session_token = secrets.token_urlsafe(32)

        # Create session
        db.execute(
            """INSERT INTO ia_sessions (user_id, session_token, ip_address, user_agent, expires_at, status)
               VALUES (%s, %s, %s, %s, DATE_ADD(NOW(), INTERVAL 24 HOUR), 'active')""",
            (user['id'], session_token, request.remote_addr, request.headers.get('User-Agent', '')[:500])
        )

        # Log login
        db.execute(
            """INSERT INTO ia_login_history (user_id, email, ip_address, user_agent, login_status)
               VALUES (%s, %s, %s, %s, 'success')""",
            (user['id'], email, request.remote_addr, request.headers.get('User-Agent', '')[:500])
        )

        # Set session cookie and redirect to dashboard
        response = redirect('/app/api/auth/dashboard')
        response.set_cookie('session_token', session_token, httponly=True, secure=True, samesite='Lax')
        return response

    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        return jsonify({'error': 'Login failed', 'details': str(e)}), 500


@auth_bp.route('/register', methods=['POST'])
def register():
    """Handle user registration"""
    try:
        import secrets
        from datetime import datetime
        
        # Handle both form and JSON data
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form.to_dict()
        
        full_name = data.get('full_name', '').strip()
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        organization = data.get('organization', '').strip()
        
        if not full_name or not email or not password:
            return jsonify({'error': 'Full name, email and password are required'}), 400
        
        # Check if email already exists
        existing = db.fetch_one("SELECT id FROM ia_users WHERE email = %s", (email,))
        if existing:
            return jsonify({'error': 'Email already registered'}), 409
        
        # Hash password
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        
        # Generate API key
        api_key = secrets.token_urlsafe(32)
        
        # Insert user
        db.execute(
            """INSERT INTO ia_users (full_name, email, password_hash, organization, role, account_status, api_enabled, wp_user_id, created_at)
               VALUES (%s, %s, %s, %s, 'investigator', 'pending', 0, 0, NOW())""",
            (full_name, email, password_hash, organization)
        )
        
        # Get user ID
        user = db.fetch_one("SELECT id FROM ia_users WHERE email = %s", (email,))
        
        # Store API key
        db.execute(
            """INSERT INTO ia_api_keys (user_id, api_key, status, created_at)
               VALUES (%s, %s, 'pending', NOW())""",
            (user['id'], api_key)
        )
        
        return jsonify({
            'success': True,
            'message': 'Registration successful. Your account is pending approval.',
            'data': {
                'email': email,
                'status': 'pending'
            }
        }), 201
        
    except Exception as e:
        logger.error(f"Registration error: {str(e)}")
        return jsonify({'error': 'Registration failed', 'details': str(e)}), 500


@auth_bp.route('/logout', methods=['POST'])
def logout():
    try:
        data = request.get_json() or {}
        session_token = data.get('session_token', '')

        if session_token:
            db.execute(
                "UPDATE ia_sessions SET status = 'revoked' WHERE session_token = %s",
                (session_token,)
            )

        return jsonify({'success': True, 'message': 'Logged out successfully'}), 200

    except Exception as e:
        logger.error(f"Logout error: {str(e)}")
        return jsonify({'error': 'Logout failed'}), 500


@auth_bp.route('/me', methods=['GET'])
def me():
    try:
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Authorization header required'}), 401

        session_token = auth_header.split(' ')[1]
        session = db.fetch_one(
            """SELECT s.user_id, s.expires_at, s.status, u.email, u.full_name, u.role
               FROM ia_sessions s
               JOIN ia_users u ON s.user_id = u.id
               WHERE s.session_token = %s""",
            (session_token,)
        )

        if not session or session['status'] != 'active':
            return jsonify({'error': 'Invalid or expired session'}), 401

        if session['expires_at'] and session['expires_at'] < datetime.now():
            return jsonify({'error': 'Session expired'}), 401

        return jsonify({
            'success': True,
            'data': {
                'id': session['user_id'],
                'email': session['email'],
                'full_name': session['full_name'],
                'role': session['role']
            }
        }), 200

    except Exception as e:
        logger.error(f"Get user error: {str(e)}")
        return jsonify({'error': 'Failed to get user profile'}), 500


@auth_bp.route('/dashboard')
def dashboard():
    """User dashboard after login"""
    try:
        # Get user from session token
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            # Check session cookie
            session_token = request.cookies.get('session_token', '')
            if not session_token:
                return redirect('/app/login')
        else:
            session_token = auth_header.split(' ')[1]

        session = db.fetch_one(
            """SELECT s.user_id, s.expires_at, s.status, u.email, u.full_name, u.role
               FROM ia_sessions s
               JOIN ia_users u ON s.user_id = u.id
               WHERE s.session_token = %s""",
            (session_token,)
        )

        if not session or session['status'] != 'active':
            return redirect('/app/login')

        if session['expires_at'] and session['expires_at'] < datetime.now():
            return redirect('/app/login')

        # Get user's investigation history
        # NOTE: ia_cases has no numeric risk-score column. Real AI-derived
        # scores live in ia_ai_results (linked via ia_evidence -> case),
        # packed inside result_json -- wiring that in needs a case->evidence
        # ->ai_results join plus JSON parsing (tracked as a follow-up).
        # Until then we approximate a 0-100 "risk" from case priority so
        # the dashboard shows something meaningful instead of crashing on
        # a status string compared as a number.
        cases_raw = db.fetch_all(
            """SELECT case_number as case_id, status, priority, created_at as date
               FROM ia_cases
               WHERE created_by = %s
               ORDER BY created_at DESC
               LIMIT 10""",
            (session['user_id'],)
        ) or []
        PRIORITY_RISK_MAP = {'critical': 90, 'high': 70, 'medium': 45, 'low': 20}
        cases = [{
            'case_id': c['case_id'],
            'status': c['status'],
            'date': c['date'],
            'risk': PRIORITY_RISK_MAP.get(c['priority'], 0),
        } for c in cases_raw]
        # Calculate stats
        total_cases = len(cases)
        high_risk_cases = sum(1 for c in cases if c['risk'] > 75)
        avg_score = round(sum(c['risk'] for c in cases) / total_cases, 1) if total_cases else 0

        gradio_token = JWTService().generate_access_token({
            'user_id': session['user_id'],
            'email': session['email'],
            'role': session['role']
        })
        return render_template('dashboard.html',
            user={
                'full_name': session['full_name'],
                'role': session['role']
            },
            total_cases=total_cases,
            high_risk_cases=high_risk_cases,
            avg_score=avg_score,
            cases=cases,
            gradio_token=gradio_token
        )

    except Exception as e:
        logger.error(f"Dashboard error: {str(e)}")
        return redirect('/app/login')


# ── p36: one-time set-password page (link emailed to new users) ──
_SETPW_HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Set your password - NexForensics</title>
<style>body{font-family:Arial,sans-serif;background:#0f172a;color:#e2e8f0;display:flex;justify-content:center;padding:40px 16px}
.c{background:#1e293b;border-radius:10px;padding:28px;max-width:380px;width:100%}input{width:100%;padding:10px;margin:6px 0 14px;border-radius:6px;border:1px solid #475569;background:#0f172a;color:#fff;box-sizing:border-box}
button,a.b{display:inline-block;background:#2563eb;color:#fff;border:0;padding:11px 18px;border-radius:6px;font-size:15px;text-decoration:none;cursor:pointer}.e{color:#f87171}.ok{color:#34d399}</style></head>
<body><div class="c"><h2>NexForensics</h2>{body}</div></body></html>"""


def _setpw_page(body, code=200):
    return _SETPW_HTML.replace('{body}', body), code, {'Content-Type': 'text/html; charset=utf-8'}


@auth_bp.route('/set-password', methods=['GET', 'POST'])
def set_password():
    import html as _html
    token = (request.values.get('token') or '').strip()
    th = hashlib.sha256(token.encode()).hexdigest() if token else ''
    row = db.fetch_one("SELECT id, user_id FROM ia_password_tokens WHERE token_hash = %s AND used_at IS NULL AND expires_at > NOW()", (th,)) if th else None
    if not row:
        return _setpw_page('<p class="e">This link is invalid or has expired.</p><p>Please ask your administrator for a new link.</p>', 400)
    form = ('<p>Choose a password for your account (at least 8 characters).</p>'
            '<form method="POST"><input type="hidden" name="token" value="' + _html.escape(token) + '">'
            '<label>New password</label><input type="password" name="password" minlength="8" required>'
            '<label>Confirm password</label><input type="password" name="confirm" minlength="8" required>'
            '<button type="submit">Set password</button></form>')
    if request.method == 'GET':
        return _setpw_page(form)
    pw = request.form.get('password', '')
    if len(pw) < 8:
        return _setpw_page('<p class="e">Password must be at least 8 characters.</p>' + form, 400)
    if pw != request.form.get('confirm', ''):
        return _setpw_page('<p class="e">The two passwords do not match.</p>' + form, 400)
    db.execute("UPDATE ia_users SET password_hash = %s WHERE id = %s", (hash_password(pw), row['user_id']))
    db.execute("UPDATE ia_password_tokens SET used_at = NOW() WHERE id = %s", (row['id'],))
    logger.info(f"Password set via link for user_id={row['user_id']}")
    return _setpw_page('<p class="ok">Your password is set.</p><p><a class="b" href="/app/login">Log in</a></p>')
