import sqlite3
import hashlib

def hash_password(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

conn = sqlite3.connect('bpms_web.db')
new_hash = hash_password("admin123")
conn.execute("UPDATE users SET password_hash=?, force_password_change=0 WHERE username='admin'", (new_hash,))
conn.commit()
conn.close()
print("La contraseña del usuario 'admin' ha sido restablecida a 'admin123'")
