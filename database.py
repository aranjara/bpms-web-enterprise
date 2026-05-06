import sqlite3, os
from contextlib import contextmanager
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "bpms_web.db")

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def query_all(sql, params=()):
    with get_db() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]

def query_one(sql, params=()):
    with get_db() as conn:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None

def execute(sql, params=()):
    with get_db() as conn:
        conn.execute(sql, params)
        conn.commit()

def init_db(seed_path=None, normalize_fn=None, hash_fn=None):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                username TEXT UNIQUE NOT NULL, 
                password_hash TEXT NOT NULL, 
                role TEXT NOT NULL CHECK(role IN ('admin','user')), 
                full_name TEXT, 
                is_active INTEGER DEFAULT 1, 
                force_password_change INTEGER DEFAULT 1, 
                last_login_at TEXT
            )
        """)
        cur.execute("CREATE TABLE IF NOT EXISTS user_permissions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, funcionario_name TEXT NOT NULL, UNIQUE(user_id, funcionario_name))")
        cur.execute("CREATE TABLE IF NOT EXISTS bpms_updates (id INTEGER PRIMARY KEY AUTOINCREMENT, radicado TEXT UNIQUE NOT NULL, observaciones TEXT, estado_tramite_actual TEXT, fecha_vencimiento TEXT, updated_by TEXT, updated_at TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS hacienda_staff (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, status TEXT, dependency TEXT, include_flag INTEGER DEFAULT 1)")
        cur.execute("CREATE TABLE IF NOT EXISTS audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action TEXT, details TEXT, radicado TEXT, created_at TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS attachments (id INTEGER PRIMARY KEY AUTOINCREMENT, radicado TEXT, filename TEXT, file_path TEXT, uploaded_by TEXT, uploaded_at TEXT)")
        conn.commit()
        
        # Admin default
        if not cur.execute("SELECT 1 FROM users WHERE username='admin'").fetchone() and hash_fn:
            cur.execute("INSERT INTO users(username,password_hash,role,full_name,is_active,force_password_change) VALUES (?,?,?,?,1,0)", 
                        ("admin", hash_fn("admin123"), "admin", "ADMINISTRADOR"))
            conn.commit()
