import hashlib
import secrets
from flask import Blueprint, request, jsonify

wp_sync_bp = Blueprint('wp_sync', __name__)
DEFAULT_WP_SECRET = 'nexforensics-wp-sync-2026-secure-key'

def verify_wp_secret():
    header = request.headers.get('X-WP-Secret', '')
    try:
        from flask import current_app
        expected = current_app.config.get('WP_SECRET', DEFAULT_WP_SECRET)
    except RuntimeError:
        expected = DEFAULT_WP_SECRET
    return header == expected

@wp_sync_bp.route('/wp/create-demo', methods=['POST'])
def create_demo():
    if not verify_wp_secret():
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json() or {}
    name = data.get('name', 'Demo User')
    org = data.get('org', '')
    demo_email = data.get('demo_email', '')
    demo_api_key = data.get('demo_api_key', '')
    demo_password = secrets.token_urlsafe(12)
    password_hash = hashlib.sha256(demo_password.encode()).hexdigest()
    from database import db
    db.execute("INSERT INTO ia_users (full_name, email, password_hash, organization, role, account_status, subscription_status, api_enabled, created_at) VALUES (%s, %s, %s, %s, 'investigator', 'approved', 'active', 1, NOW())", (name, demo_email, password_hash, org))
    user = db.fetch_one("SELECT id FROM ia_users WHERE email = %s", (demo_email,))
    session_token = secrets.token_urlsafe(32)
    db.execute("INSERT INTO ia_sessions (user_id, session_token, ip_address, expires_at, status) VALUES (%s, %s, '127.0.0.1', DATE_ADD(NOW(), INTERVAL 48 HOUR), 'active')", (user['id'], session_token))
    if demo_api_key:
        db.execute("INSERT INTO ia_api_keys (user_id, api_key, status, created_at) VALUES (%s, %s, 'active', NOW())", (user['id'], demo_api_key))
    return jsonify({'success': True, 'flask_inv_id': user['id'], 'session_token': session_token, 'demo_password': demo_password})

@wp_sync_bp.route('/wp/verify-user', methods=['POST'])
def verify_user():
    if not verify_wp_secret():
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    action = data.get('action', '')
    if not email or action not in ['approve', 'reject']:
        return jsonify({'error': 'Invalid data'}), 400
    from database import db
    new_status = 'approved' if action == 'approve' else 'rejected'
    db.execute("UPDATE ia_users SET account_status = %s WHERE email = %s", (new_status, email))
    if action == 'approve':
        user = db.fetch_one("SELECT id FROM ia_users WHERE email = %s", (email,))
        if user:
            api_key = 'NEXF-' + secrets.token_urlsafe(32).upper()[:20]
            db.execute("INSERT INTO ia_api_keys (user_id, api_key, status, created_at) VALUES (%s, %s, 'active', NOW())", (user['id'], api_key))
            return jsonify({'success': True, 'message': f'User {email} approved', 'api_key': api_key})
    return jsonify({'success': True, 'message': f'User {email} {action}ed'})

@wp_sync_bp.route('/wp/user-status', methods=['GET'])
def user_status():
    if not verify_wp_secret():
        return jsonify({'error': 'Unauthorized'}), 401
    email = request.args.get('email', '').strip().lower()
    if not email:
        return jsonify({'error': 'Email required'}), 400
    from database import db
    user = db.fetch_one("SELECT full_name, email, account_status, role, created_at FROM ia_users WHERE email = %s", (email,))
    if not user:
        return jsonify({'error': 'User not found'}), 404
    return jsonify({'success': True, 'data': {'name': user['full_name'], 'email': user['email'], 'status': user['account_status'], 'role': user['role'], 'created_at': str(user['created_at'])}})

@wp_sync_bp.route('/wp/pending-users', methods=['GET'])
def pending_users():
    if not verify_wp_secret():
        return jsonify({'error': 'Unauthorized'}), 401
    from database import db
    users = db.fetch_all("SELECT id, full_name, email, organization, document_path, created_at FROM ia_users WHERE account_status = 'pending' ORDER BY created_at DESC") or []
    return jsonify({'success': True, 'count': len(users), 'users': users})


# ── p32: real user account (login + password + API key) from WP CP Panel ──
@wp_sync_bp.route('/wp/create-user', methods=['POST'])
def create_user():
    if not verify_wp_secret():
        return jsonify({'error': 'Unauthorized'}), 401
    import re as _re
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    org = (data.get('org') or '').strip()
    mobile = (data.get('mobile') or '').strip()[:30]
    password = data.get('password') or ''
    days = data.get('key_days')
    if not name or not _re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        return jsonify({'error': 'Name and a valid email are required'}), 400
    generated = False
    if not password:
        password = secrets.token_urlsafe(12); generated = True
    elif len(password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters'}), 400
    from database import db
    if db.fetch_one("SELECT id FROM ia_users WHERE email = %s", (email,)):
        return jsonify({'error': 'A user with this email already exists'}), 409
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    db.execute("INSERT INTO ia_users (full_name, email, password_hash, organization, mobile, role, account_status, subscription_status, api_enabled, created_at) VALUES (%s, %s, %s, %s, %s, 'investigator', 'approved', 'active', 1, NOW())", (name, email, password_hash, org, mobile))
    user = db.fetch_one("SELECT id FROM ia_users WHERE email = %s", (email,))
    api_key = 'NEXF-' + secrets.token_hex(24).upper()
    try:
        days = int(days) if days not in (None, '', 0, '0') else None
    except (TypeError, ValueError):
        days = None
    if days:
        db.execute("INSERT INTO ia_api_keys (user_id, api_key, status, created_at, expires_at) VALUES (%s, %s, 'active', NOW(), DATE_ADD(NOW(), INTERVAL %s DAY))", (user['id'], api_key, days))
    else:
        db.execute("INSERT INTO ia_api_keys (user_id, api_key, status, created_at) VALUES (%s, %s, 'active', NOW())", (user['id'], api_key))
    # p36: one-time set-password link (72 h), stored as SHA-256 of the token
    set_token = secrets.token_urlsafe(32)
    try:
        db.execute("""CREATE TABLE IF NOT EXISTS ia_password_tokens (
            id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL,
            token_hash CHAR(64) NOT NULL UNIQUE, expires_at DATETIME NOT NULL,
            used_at DATETIME NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")
        db.execute("INSERT INTO ia_password_tokens (user_id, token_hash, expires_at) VALUES (%s, %s, DATE_ADD(NOW(), INTERVAL 72 HOUR))",
                   (user['id'], hashlib.sha256(set_token.encode()).hexdigest()))
        set_url = 'https://nexforensics.com/app/api/auth/set-password?token=' + set_token
    except Exception:
        set_url = ''
    return jsonify({'success': True, 'flask_user_id': user['id'], 'email': email, 'api_key': api_key,
                    'password': password, 'password_generated': generated, 'set_password_url': set_url})
