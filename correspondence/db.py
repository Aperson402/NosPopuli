import sqlite3
import uuid
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "correspondence.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            name TEXT,
            zip_code TEXT,
            state TEXT,
            city TEXT,
            gmail_address TEXT,
            email_screened INTEGER DEFAULT 0,
            gmail_refresh_token TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            last_active TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS rate_limits (
            user_id TEXT,
            action TEXT,
            window_date TEXT,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, action, window_date)
        );

        CREATE TABLE IF NOT EXISTS correspondence (
            id TEXT PRIMARY KEY,
            user_id TEXT REFERENCES users(id),
            bill_id TEXT,
            bill_title TEXT,
            legislator_name TEXT,
            legislator_office TEXT,
            legislator_state TEXT,
            to_email TEXT,
            contact_form_url TEXT,
            subject TEXT,
            body TEXT,
            sent_at TEXT,
            delivery_method TEXT,
            gmail_thread_id TEXT,
            gmail_message_id TEXT,
            status TEXT DEFAULT 'sent',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS replies (
            id TEXT PRIMARY KEY,
            correspondence_id TEXT REFERENCES correspondence(id),
            gmail_message_id TEXT UNIQUE,
            received_at TEXT,
            preview_text TEXT
        );
    """)
    conn.commit()
    conn.close()


def upsert_user(user_id, email, name):
    conn = get_conn()
    conn.execute("""
        INSERT INTO users (id, email, name) VALUES (?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            email=excluded.email,
            name=excluded.name,
            last_active=datetime('now')
    """, (user_id, email, name))
    conn.commit()
    conn.close()


def get_user(user_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_user_gmail(user_id, gmail_address, refresh_token, screened):
    conn = get_conn()
    conn.execute("""
        UPDATE users SET
            gmail_address=?, gmail_refresh_token=?, email_screened=?
        WHERE id=?
    """, (gmail_address, refresh_token, 1 if screened else 0, user_id))
    conn.commit()
    conn.close()


def update_user_zip(user_id, zip_code, state, city):
    conn = get_conn()
    conn.execute("UPDATE users SET zip_code=?, state=?, city=? WHERE id=?",
                 (zip_code, state, city, user_id))
    conn.commit()
    conn.close()


def check_rate_limit(user_id, action, daily_max):
    """Returns True if the user is within their daily limit."""
    from datetime import date
    today = date.today().isoformat()
    conn = get_conn()
    row = conn.execute(
        "SELECT count FROM rate_limits WHERE user_id=? AND action=? AND window_date=?",
        (user_id, action, today)
    ).fetchone()
    count = row["count"] if row else 0
    conn.close()
    return count < daily_max


def increment_rate_limit(user_id, action):
    from datetime import date
    today = date.today().isoformat()
    conn = get_conn()
    conn.execute("""
        INSERT INTO rate_limits (user_id, action, window_date, count)
        VALUES (?, ?, ?, 1)
        ON CONFLICT(user_id, action, window_date) DO UPDATE SET count=count+1
    """, (user_id, action, today))
    conn.commit()
    conn.close()


def check_bill_rep_cooldown(user_id, bill_id, legislator_name):
    """Block repeat sends to the same rep for the same bill within 30 days."""
    conn = get_conn()
    row = conn.execute("""
        SELECT id FROM correspondence
        WHERE user_id=? AND bill_id=? AND legislator_name=?
          AND sent_at > datetime('now', '-30 days')
    """, (user_id, bill_id, legislator_name)).fetchone()
    conn.close()
    return row is not None  # True = in cooldown


def save_correspondence(item):
    conn = get_conn()
    conn.execute("""
        INSERT INTO correspondence
        (id, user_id, bill_id, bill_title, legislator_name, legislator_office,
         legislator_state, to_email, contact_form_url, subject, body,
         sent_at, delivery_method, gmail_thread_id, gmail_message_id, status)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        item["id"], item["user_id"], item["bill_id"], item["bill_title"],
        item["legislator_name"], item["legislator_office"], item["legislator_state"],
        item.get("to_email"), item.get("contact_form_url"),
        item["subject"], item["body"], item["sent_at"],
        item["delivery_method"], item.get("gmail_thread_id"),
        item.get("gmail_message_id"), "sent"
    ))
    conn.commit()
    conn.close()


def get_user_correspondence(user_id):
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM correspondence WHERE user_id=? ORDER BY sent_at DESC
    """, (user_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_correspondence_by_id(corr_id, user_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM correspondence WHERE id=? AND user_id=?", (corr_id, user_id)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def save_reply(corr_id, gmail_message_id, received_at, preview_text):
    conn = get_conn()
    conn.execute("""
        INSERT OR IGNORE INTO replies
        (id, correspondence_id, gmail_message_id, received_at, preview_text)
        VALUES (?,?,?,?,?)
    """, (str(uuid.uuid4()), corr_id, gmail_message_id, received_at, preview_text))
    conn.execute(
        "UPDATE correspondence SET status='replied' WHERE id=?", (corr_id,)
    )
    conn.commit()
    conn.close()


def get_replies(corr_id):
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM replies WHERE correspondence_id=? ORDER BY received_at DESC
    """, (corr_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
