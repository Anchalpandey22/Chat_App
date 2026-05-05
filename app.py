"""
WhatsApp Lite — Real-Time Chat Application
==========================================
Backend: Flask + SQLite (no extra dependencies beyond Flask)
Real-time: Server-Sent Events (SSE) — works in every browser, zero extra packages
Database: SQLite via Python's built-in sqlite3 module

Run:  python app.py
Open: http://127.0.0.1:5000
"""

import os
import sqlite3
import hashlib
import json
import time
import uuid
import threading
from datetime import datetime
from functools import wraps
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, jsonify, Response, g
)

app = Flask(__name__)
app.secret_key = "chatapp_super_secret_key_2024_anchal"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "chatapp.db")

# ── SSE broadcast store (in-memory queue per user) ────────────────────────────
# Maps user_id -> list of queued SSE events
_sse_queues: dict = {}
_sse_lock = threading.Lock()


# ═══════════════════════════════════════════════════════════════════════════════
#  DATABASE
# ═══════════════════════════════════════════════════════════════════════════════

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


@app.teardown_appcontext
def close_db(error):
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    """Create all tables if they don't exist."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    c = conn.cursor()

    # Users table
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            username  TEXT UNIQUE NOT NULL,
            password  TEXT NOT NULL,
            avatar    TEXT DEFAULT 'default',
            status    TEXT DEFAULT 'Hey there! I am using ChatApp.',
            online    INTEGER DEFAULT 0,
            last_seen TEXT DEFAULT '',
            created_at TEXT DEFAULT ''
        )
    """)

    # Messages table
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id   INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            content     TEXT NOT NULL,
            msg_type    TEXT DEFAULT 'text',
            is_read     INTEGER DEFAULT 0,
            created_at  TEXT NOT NULL,
            FOREIGN KEY(sender_id)   REFERENCES users(id),
            FOREIGN KEY(receiver_id) REFERENCES users(id)
        )
    """)

    # Groups table
    c.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            avatar     TEXT DEFAULT 'group',
            created_at TEXT NOT NULL
        )
    """)

    # Group members
    c.execute("""
        CREATE TABLE IF NOT EXISTS group_members (
            group_id  INTEGER NOT NULL,
            user_id   INTEGER NOT NULL,
            role      TEXT DEFAULT 'member',
            joined_at TEXT NOT NULL,
            PRIMARY KEY(group_id, user_id)
        )
    """)

    # Group messages
    c.execute("""
        CREATE TABLE IF NOT EXISTS group_messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id   INTEGER NOT NULL,
            sender_id  INTEGER NOT NULL,
            content    TEXT NOT NULL,
            msg_type   TEXT DEFAULT 'text',
            created_at TEXT NOT NULL,
            FOREIGN KEY(group_id)  REFERENCES groups(id),
            FOREIGN KEY(sender_id) REFERENCES users(id)
        )
    """)

    conn.commit()
    conn.close()
    print("✓ Database initialised")


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def time_ago(dt_str: str) -> str:
    if not dt_str:
        return ""
    try:
        dt  = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
        sec = int((datetime.now() - dt).total_seconds())
        if sec < 60:    return "just now"
        if sec < 3600:  return f"{sec//60}m ago"
        if sec < 86400: return f"{sec//3600}h ago"
        return f"{sec//86400}d ago"
    except:
        return ""


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def get_user(user_id: int):
    db = get_db()
    return db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()


def set_online(user_id: int, online: bool):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE users SET online=?, last_seen=? WHERE id=?",
        (1 if online else 0, now(), user_id)
    )
    conn.commit()
    conn.close()


# ── SSE helpers ────────────────────────────────────────────────────────────────

def sse_push(user_id: int, event: str, data: dict):
    """Push a real-time event to a specific user's SSE queue."""
    with _sse_lock:
        if user_id not in _sse_queues:
            _sse_queues[user_id] = []
        _sse_queues[user_id].append({"event": event, "data": data})


def sse_push_many(user_ids: list, event: str, data: dict):
    for uid in user_ids:
        sse_push(uid, event, data)


# ═══════════════════════════════════════════════════════════════════════════════
#  AUTH ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("chat"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        db   = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE username=? AND password=?",
            (username, hash_password(password))
        ).fetchone()
        if user:
            session["user_id"]   = user["id"]
            session["username"]  = user["username"]
            set_online(user["id"], True)
            return redirect(url_for("chat"))
        error = "Invalid username or password."
    return render_template("login.html", error=error)


@app.route("/register", methods=["GET", "POST"])
def register():
    error = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm  = request.form.get("confirm", "")
        if len(username) < 3:
            error = "Username must be at least 3 characters."
        elif len(password) < 4:
            error = "Password must be at least 4 characters."
        elif password != confirm:
            error = "Passwords do not match."
        else:
            db = get_db()
            existing = db.execute(
                "SELECT id FROM users WHERE username=?", (username,)
            ).fetchone()
            if existing:
                error = "Username already taken."
            else:
                db.execute(
                    "INSERT INTO users (username, password, created_at) VALUES (?,?,?)",
                    (username, hash_password(password), now())
                )
                db.commit()
                user = db.execute(
                    "SELECT * FROM users WHERE username=?", (username,)
                ).fetchone()
                session["user_id"]  = user["id"]
                session["username"] = user["username"]
                set_online(user["id"], True)
                return redirect(url_for("chat"))
    return render_template("register.html", error=error)


@app.route("/logout")
def logout():
    if "user_id" in session:
        set_online(session["user_id"], False)
        with _sse_lock:
            _sse_queues.pop(session["user_id"], None)
    session.clear()
    return redirect(url_for("login"))


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN CHAT PAGE
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/chat")
@login_required
def chat():
    user = get_user(session["user_id"])
    return render_template("chat.html", user=user)


# ═══════════════════════════════════════════════════════════════════════════════
#  API — USERS
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/users")
@login_required
def api_users():
    db    = get_db()
    me    = session["user_id"]
    users = db.execute(
        "SELECT id, username, avatar, status, online, last_seen FROM users WHERE id != ?",
        (me,)
    ).fetchall()

    result = []
    for u in users:
        # Last message between me and this user
        last_msg = db.execute("""
            SELECT content, created_at FROM messages
            WHERE (sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?)
            ORDER BY id DESC LIMIT 1
        """, (me, u["id"], u["id"], me)).fetchone()

        # Unread count
        unread = db.execute("""
            SELECT COUNT(*) as cnt FROM messages
            WHERE sender_id=? AND receiver_id=? AND is_read=0
        """, (u["id"], me)).fetchone()["cnt"]

        result.append({
            "id":        u["id"],
            "username":  u["username"],
            "avatar":    u["avatar"],
            "status":    u["status"],
            "online":    bool(u["online"]),
            "last_seen": time_ago(u["last_seen"]),
            "last_msg":  last_msg["content"][:40] if last_msg else "",
            "last_time": time_ago(last_msg["created_at"]) if last_msg else "",
            "unread":    unread,
        })

    # Sort: online first, then by last message
    result.sort(key=lambda x: (not x["online"], x["last_time"] == ""))
    return jsonify(result)


@app.route("/api/me")
@login_required
def api_me():
    user = get_user(session["user_id"])
    return jsonify({
        "id":       user["id"],
        "username": user["username"],
        "avatar":   user["avatar"],
        "status":   user["status"],
    })


@app.route("/api/profile", methods=["POST"])
@login_required
def api_profile():
    data   = request.get_json()
    status = data.get("status", "").strip()[:100]
    db     = get_db()
    db.execute("UPDATE users SET status=? WHERE id=?", (status, session["user_id"]))
    db.commit()
    return jsonify({"ok": True})


# ═══════════════════════════════════════════════════════════════════════════════
#  API — MESSAGES (1-to-1)
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/messages/<int:other_id>")
@login_required
def api_messages(other_id):
    me = session["user_id"]
    db = get_db()

    # Mark incoming as read
    db.execute("""
        UPDATE messages SET is_read=1
        WHERE sender_id=? AND receiver_id=? AND is_read=0
    """, (other_id, me))
    db.commit()

    msgs = db.execute("""
        SELECT m.id, m.sender_id, m.receiver_id, m.content,
               m.msg_type, m.is_read, m.created_at,
               u.username as sender_name
        FROM messages m
        JOIN users u ON u.id = m.sender_id
        WHERE (m.sender_id=? AND m.receiver_id=?)
           OR (m.sender_id=? AND m.receiver_id=?)
        ORDER BY m.id ASC
        LIMIT 200
    """, (me, other_id, other_id, me)).fetchall()

    return jsonify([dict(m) for m in msgs])


@app.route("/api/send", methods=["POST"])
@login_required
def api_send():
    data      = request.get_json()
    me        = session["user_id"]
    receiver  = int(data.get("receiver_id", 0))
    content   = data.get("content", "").strip()
    msg_type  = data.get("msg_type", "text")

    if not content or not receiver:
        return jsonify({"error": "Missing fields"}), 400

    db = get_db()
    ts = now()
    cursor = db.execute("""
        INSERT INTO messages (sender_id, receiver_id, content, msg_type, created_at)
        VALUES (?,?,?,?,?)
    """, (me, receiver, content, msg_type, ts))
    db.commit()

    msg_id   = cursor.lastrowid
    sender   = get_user(me)
    msg_data = {
        "id":          msg_id,
        "sender_id":   me,
        "receiver_id": receiver,
        "content":     content,
        "msg_type":    msg_type,
        "is_read":     0,
        "created_at":  ts,
        "sender_name": sender["username"],
    }

    # Push to receiver's SSE queue
    sse_push(receiver, "message", msg_data)
    # Also echo back to sender (for multi-tab support)
    sse_push(me, "message_sent", msg_data)

    return jsonify({"ok": True, "message": msg_data})


# ═══════════════════════════════════════════════════════════════════════════════
#  API — GROUPS
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/groups")
@login_required
def api_groups():
    me = session["user_id"]
    db = get_db()
    groups = db.execute("""
        SELECT g.id, g.name, g.avatar, g.created_at
        FROM groups g
        JOIN group_members gm ON gm.group_id = g.id
        WHERE gm.user_id = ?
    """, (me,)).fetchall()

    result = []
    for g in groups:
        last = db.execute("""
            SELECT gm2.content, gm2.created_at, u.username as sender
            FROM group_messages gm2
            JOIN users u ON u.id = gm2.sender_id
            WHERE gm2.group_id = ?
            ORDER BY gm2.id DESC LIMIT 1
        """, (g["id"],)).fetchone()

        members = db.execute("""
            SELECT COUNT(*) as cnt FROM group_members WHERE group_id=?
        """, (g["id"],)).fetchone()["cnt"]

        result.append({
            "id":       g["id"],
            "name":     g["name"],
            "avatar":   g["avatar"],
            "members":  members,
            "last_msg": (last["sender"] + ": " + last["content"][:30]) if last else "",
            "last_time": time_ago(last["created_at"]) if last else "",
        })
    return jsonify(result)


@app.route("/api/groups/create", methods=["POST"])
@login_required
def api_create_group():
    data    = request.get_json()
    name    = data.get("name", "").strip()
    members = data.get("members", [])  # list of user_ids
    me      = session["user_id"]

    if not name:
        return jsonify({"error": "Group name required"}), 400

    db = get_db()
    ts = now()
    cursor = db.execute(
        "INSERT INTO groups (name, created_by, created_at) VALUES (?,?,?)",
        (name, me, ts)
    )
    gid = cursor.lastrowid

    # Add creator as admin
    db.execute(
        "INSERT INTO group_members (group_id, user_id, role, joined_at) VALUES (?,?,?,?)",
        (gid, me, "admin", ts)
    )
    # Add other members
    for uid in members:
        if uid != me:
            db.execute(
                "INSERT OR IGNORE INTO group_members (group_id, user_id, role, joined_at) VALUES (?,?,?,?)",
                (gid, int(uid), "member", ts)
            )
    db.commit()
    return jsonify({"ok": True, "group_id": gid})


@app.route("/api/groups/<int:group_id>/messages")
@login_required
def api_group_messages(group_id):
    me = session["user_id"]
    db = get_db()

    # Verify membership
    member = db.execute(
        "SELECT 1 FROM group_members WHERE group_id=? AND user_id=?",
        (group_id, me)
    ).fetchone()
    if not member:
        return jsonify({"error": "Not a member"}), 403

    msgs = db.execute("""
        SELECT gm.id, gm.group_id, gm.sender_id, gm.content,
               gm.msg_type, gm.created_at, u.username as sender_name
        FROM group_messages gm
        JOIN users u ON u.id = gm.sender_id
        WHERE gm.group_id = ?
        ORDER BY gm.id ASC LIMIT 200
    """, (group_id,)).fetchall()

    return jsonify([dict(m) for m in msgs])


@app.route("/api/groups/<int:group_id>/send", methods=["POST"])
@login_required
def api_group_send(group_id):
    data    = request.get_json()
    me      = session["user_id"]
    content = data.get("content", "").strip()

    if not content:
        return jsonify({"error": "Empty message"}), 400

    db = get_db()
    # Verify membership
    member = db.execute(
        "SELECT 1 FROM group_members WHERE group_id=? AND user_id=?",
        (group_id, me)
    ).fetchone()
    if not member:
        return jsonify({"error": "Not a member"}), 403

    ts     = now()
    cursor = db.execute(
        "INSERT INTO group_messages (group_id, sender_id, content, created_at) VALUES (?,?,?,?)",
        (group_id, me, content, ts)
    )
    db.commit()

    sender   = get_user(me)
    msg_data = {
        "id":          cursor.lastrowid,
        "group_id":    group_id,
        "sender_id":   me,
        "content":     content,
        "created_at":  ts,
        "sender_name": sender["username"],
        "msg_type":    "text",
    }

    # Push to all group members except sender
    members = db.execute(
        "SELECT user_id FROM group_members WHERE group_id=? AND user_id != ?",
        (group_id, me)
    ).fetchall()

    for m in members:
        sse_push(m["user_id"], "group_message", msg_data)
    sse_push(me, "group_message_sent", msg_data)

    return jsonify({"ok": True, "message": msg_data})


@app.route("/api/groups/<int:group_id>/members")
@login_required
def api_group_members(group_id):
    db = get_db()
    members = db.execute("""
        SELECT u.id, u.username, u.avatar, u.online, gm.role
        FROM group_members gm
        JOIN users u ON u.id = gm.user_id
        WHERE gm.group_id = ?
    """, (group_id,)).fetchall()
    return jsonify([dict(m) for m in members])


# ═══════════════════════════════════════════════════════════════════════════════
#  SERVER-SENT EVENTS  (Real-Time)
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/events")
@login_required
def api_events():
    """
    SSE endpoint — the browser connects here once and listens forever.
    We push new messages, online status changes, etc. through this stream.
    """
    user_id = session["user_id"]

    # Ensure queue exists
    with _sse_lock:
        if user_id not in _sse_queues:
            _sse_queues[user_id] = []

    def event_stream():
        # Send a heartbeat immediately so browser knows we're alive
        yield "data: {\"type\":\"connected\"}\n\n"
        last_heartbeat = time.time()

        while True:
            # Drain this user's queue
            events = []
            with _sse_lock:
                if user_id in _sse_queues:
                    events = _sse_queues[user_id][:]
                    _sse_queues[user_id] = []

            for ev in events:
                payload = json.dumps({"type": ev["event"], "data": ev["data"]})
                yield f"data: {payload}\n\n"

            # Heartbeat every 15s to keep connection alive
            if time.time() - last_heartbeat > 15:
                yield "data: {\"type\":\"ping\"}\n\n"
                last_heartbeat = time.time()

            time.sleep(0.3)

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":   "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":      "keep-alive",
        }
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  BOOT
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    init_db()
    print("\n" + "="*55)
    print("  💬  WhatsApp Lite — Chat Application")
    print("="*55)
    print("  Open your browser →  http://127.0.0.1:5000")
    print("  Register two accounts to start chatting!")
    print("="*55 + "\n")
    app.run(debug=False, threaded=True, port=5000)
