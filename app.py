import os
from pathlib import Path
import sqlite3, hashlib, unicodedata, json, traceback, io
from datetime import date, datetime
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("DB_PATH", str(BASE_DIR / "bpms_web.db")))
REPORT_PATH = Path(os.getenv("REPORT_PATH", str(BASE_DIR / "Reporte BPMS.xlsx")))
SEED_PATH = BASE_DIR / "hacienda_seed.json"
LOG_PATH = Path(os.getenv("LOG_PATH", str(BASE_DIR / "error.log")))

# Asegurar que el directorio de la base de datos existe
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.secret_key = "bpms-web-enterprise-local-change-this"

def normalize_text(value):
    if value is None:
        return ""
    value = str(value).strip().upper()
    value = "".join(ch for ch in unicodedata.normalize("NFD", value) if unicodedata.category(ch) != "Mn")
    while "  " in value:
        value = value.replace("  ", " ")
    return value

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def query_all(sql, params=()):
    conn = db()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows

def query_one(sql, params=()):
    conn = db()
    row = conn.execute(sql, params).fetchone()
    conn.close()
    return row

def execute(sql, params=()):
    conn = db()
    conn.execute(sql, params)
    conn.commit()
    conn.close()

def log_error(where, exc):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("\n" + "="*80 + "\n")
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {where}\n")
            f.write(str(exc) + "\n")
            f.write(traceback.format_exc() + "\n")
    except Exception:
        pass

def init_db():
    conn = db()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','user')), full_name TEXT, is_active INTEGER DEFAULT 1, force_password_change INTEGER DEFAULT 1, last_login_at TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS user_permissions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, funcionario_name TEXT NOT NULL, UNIQUE(user_id, funcionario_name))")
    cur.execute("CREATE TABLE IF NOT EXISTS bpms_updates (id INTEGER PRIMARY KEY AUTOINCREMENT, radicado TEXT UNIQUE NOT NULL, observaciones TEXT, estado_tramite_actual TEXT, fecha_vencimiento TEXT, updated_by TEXT, updated_at TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS hacienda_staff (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, status TEXT, dependency TEXT, include_flag INTEGER DEFAULT 1)")
    conn.commit()
    if not cur.execute("SELECT 1 FROM users WHERE username='admin'").fetchone():
        cur.execute("INSERT INTO users(username,password_hash,role,full_name,is_active,force_password_change) VALUES (?,?,?,?,1,0)", ("admin", hash_password("admin123"), "admin", "ADMINISTRADOR"))
        conn.commit()
    total_staff = cur.execute("SELECT COUNT(*) AS t FROM hacienda_staff").fetchone()["t"]
    if total_staff == 0 and SEED_PATH.exists():
        data = json.loads(SEED_PATH.read_text(encoding='utf-8'))
        cur.executemany("INSERT INTO hacienda_staff(name,status,dependency,include_flag) VALUES (?,?,?,?)", [(normalize_text(n), s, d, int(i)) for n, s, d, i in data])
        conn.commit()
    conn.close()

def get_user(username):
    return query_one("SELECT * FROM users WHERE username=?", (username,))

def get_user_by_id(user_id):
    return query_one("SELECT * FROM users WHERE id=?", (user_id,))

def get_staff_by_id(staff_id):
    return query_one("SELECT * FROM hacienda_staff WHERE id=?", (staff_id,))

def current_user():
    username = session.get("username")
    return get_user(username) if username else None

def authenticate(username, password):
    user = get_user(username)
    if user and int(user["is_active"]) == 1 and user["password_hash"] == hash_password(password):
        execute("UPDATE users SET last_login_at=? WHERE id=?", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user["id"]))
        return get_user(username)
    return None

def verify_user_password(user_id, password):
    row = query_one("SELECT password_hash FROM users WHERE id=?", (user_id,))
    return bool(row and row["password_hash"] == hash_password(password))

def change_user_password(user_id, new_password):
    execute("UPDATE users SET password_hash=?, force_password_change=0 WHERE id=?", (hash_password(new_password), user_id))

def allowed_hacienda_names():
    return [r["name"] for r in query_all("SELECT name FROM hacienda_staff WHERE include_flag=1 ORDER BY name")]

def list_hacienda_staff():
    return query_all("SELECT * FROM hacienda_staff ORDER BY include_flag DESC, name")

def list_users():
    allowed = set(allowed_hacienda_names())
    rows = query_all("SELECT * FROM users ORDER BY role DESC, full_name, username")
    return [r for r in rows if r["role"] == "admin" or normalize_text(r["full_name"]) in allowed]

def get_user_permissions(user_id):
    return [r["funcionario_name"] for r in query_all("SELECT funcionario_name FROM user_permissions WHERE user_id=? ORDER BY funcionario_name", (user_id,))]

def make_username(full_name, existing_usernames=None):
    existing_usernames = existing_usernames or set()
    parts = [p.lower() for p in normalize_text(full_name).split() if p]
    if not parts:
        candidate = "usuario"
    else:
        first_initial = parts[0][0]
        surname = parts[-2] if len(parts) >= 3 else parts[-1]
        candidate = f"{first_initial}{surname}"
        if candidate in existing_usernames and len(parts) >= 2:
            candidate = f"{first_initial}{parts[1][0]}{surname}"
        base = candidate
        i = 2
        while candidate in existing_usernames:
            candidate = f"{base}{i}"
            i += 1
    return candidate

def sync_users_from_hacienda():
    existing = list_users()
    names = {normalize_text(u["full_name"]): u for u in existing}
    usernames = {u["username"] for u in existing}
    created = 0
    for row in list_hacienda_staff():
        if int(row["include_flag"]) != 1:
            continue
        full_name = normalize_text(row["name"])
        if not full_name or full_name in names:
            continue
        username = make_username(full_name, usernames)
        conn = db()
        conn.execute("INSERT INTO users(username,password_hash,role,full_name,is_active,force_password_change) VALUES (?,?,?,?,1,1)", (username, hash_password("123456"), "user", full_name))
        uid = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
        conn.execute("INSERT OR IGNORE INTO user_permissions(user_id, funcionario_name) VALUES (?,?)", (uid, full_name))
        conn.commit()
        conn.close()
        usernames.add(username)
        created += 1
    return created

def bpms_status(value):
    if pd.isna(value):
        return "SIN FECHA"
    days = (value.date() - date.today()).days
    if days < 0:
        return "VENCIDO"
    if days <= 3:
        return "POR VENCER"
    return "EN MARCHA"

def days_left(value):
    if pd.isna(value):
        return None
    if isinstance(value, str):
        value = pd.to_datetime(value, errors="coerce")
        if pd.isna(value):
            return None
    return (value.date() - date.today()).days

def fmt_date(value):
    if value is None:
        return ""
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return ""
        value = value.replace("/", "-")
        try:
            value = pd.to_datetime(value, errors="coerce", dayfirst=False)
        except Exception:
            return ""
    if pd.isna(value):
        return ""
    try:
        return value.strftime("%Y-%m-%d")
    except Exception:
        return ""

def normalize_input_date(value):
    if value is None:
        return ""
    value = str(value).strip()
    if not value:
        return ""
    value = value.replace("/", "-")
    try:
        dt = pd.to_datetime(value, errors="coerce", dayfirst=False)
        if pd.isna(dt):
            return ""
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return ""

def load_bpms():
    if not REPORT_PATH.exists():
        return pd.DataFrame()
    xl = pd.ExcelFile(REPORT_PATH)
    df = pd.read_excel(REPORT_PATH, sheet_name=xl.sheet_names[0])
    df["RADICADO"] = df["radicado_inicial"].astype(str).str.strip() if "radicado_inicial" in df.columns else df.iloc[:,0].astype(str).str.strip()
    if "usuario_responsable_actividad" in df.columns:
        df["FUNCIONARIO"] = df["usuario_responsable_actividad"].apply(normalize_text)
    else:
        df["FUNCIONARIO"] = df.iloc[:,16].apply(normalize_text) if len(df.columns) > 16 else ""
    df["TIPO_SOLICITUD"] = df["descripcion"].fillna("").astype(str) if "descripcion" in df.columns else ""
    df["FECHA_VENCIMIENTO"] = pd.to_datetime(df["fecha_vencimiento"], errors="coerce") if "fecha_vencimiento" in df.columns else pd.NaT
    df["ESTADO_TRAMITE_ACTUAL"] = df["estado_tramite"].fillna("").astype(str) if "estado_tramite" in df.columns else ""
    df["OBSERVACIONES"] = ""
    allowed = set(allowed_hacienda_names())
    if allowed:
        df = df[df["FUNCIONARIO"].isin(allowed)].copy()
    conn = db()
    updates = pd.read_sql_query("SELECT * FROM bpms_updates", conn)
    conn.close()
    if not updates.empty:
        updates["radicado"] = updates["radicado"].astype(str).str.strip()
        updates["fecha_vencimiento"] = pd.to_datetime(updates["fecha_vencimiento"], errors="coerce")
        updates = updates.rename(columns={
            "observaciones": "OBSERVACIONES_DB",
            "estado_tramite_actual": "ESTADO_TRAMITE_ACTUAL_DB",
            "fecha_vencimiento": "FECHA_VENCIMIENTO_DB",
        })
        df = df.merge(
            updates[["radicado", "OBSERVACIONES_DB", "ESTADO_TRAMITE_ACTUAL_DB", "FECHA_VENCIMIENTO_DB"]],
            left_on="RADICADO",
            right_on="radicado",
            how="left"
        )
        df["OBSERVACIONES"] = df["OBSERVACIONES_DB"].fillna("")
        df["ESTADO_TRAMITE_ACTUAL"] = df["ESTADO_TRAMITE_ACTUAL_DB"].fillna(df["ESTADO_TRAMITE_ACTUAL"])
        df["FECHA_VENCIMIENTO"] = df["FECHA_VENCIMIENTO_DB"].combine_first(df["FECHA_VENCIMIENTO"])
    for c in ["radicado", "OBSERVACIONES_DB", "ESTADO_TRAMITE_ACTUAL_DB", "FECHA_VENCIMIENTO_DB"]:
        if c in df.columns:
            df.drop(columns=[c], inplace=True)
    df["CONTROL_VENCIMIENTO"] = df["FECHA_VENCIMIENTO"].apply(bpms_status)
    df["DIAS_RESTANTES"] = df["FECHA_VENCIMIENTO"].apply(days_left)
    return df[["RADICADO","FUNCIONARIO","TIPO_SOLICITUD","FECHA_VENCIMIENTO","DIAS_RESTANTES","CONTROL_VENCIMIENTO","ESTADO_TRAMITE_ACTUAL","OBSERVACIONES"]].copy()

def filtered_bpms(user, funcionario="TODOS", estado="TODOS", buscar=""):
    df = load_bpms()
    if df.empty:
        return df
    if user["role"] != "admin":
        allowed = set(get_user_permissions(user["id"]))
        if allowed:
            df = df[df["FUNCIONARIO"].isin(allowed)]
            if funcionario and funcionario != "TODOS":
                df = df[df["FUNCIONARIO"] == normalize_text(funcionario)]
        else:
            df = df[df["FUNCIONARIO"] == normalize_text(user["full_name"])]
    else:
        if funcionario and funcionario != "TODOS":
            df = df[df["FUNCIONARIO"] == normalize_text(funcionario)]
    if estado and estado != "TODOS":
        df = df[df["CONTROL_VENCIMIENTO"] == estado]
    buscar = (buscar or "").strip().lower()
    if buscar:
        mask = (
            df["RADICADO"].astype(str).str.lower().str.contains(buscar, na=False) |
            df["FUNCIONARIO"].astype(str).str.lower().str.contains(buscar, na=False) |
            df["TIPO_SOLICITUD"].astype(str).str.lower().str.contains(buscar, na=False) |
            df["ESTADO_TRAMITE_ACTUAL"].astype(str).str.lower().str.contains(buscar, na=False) |
            df["OBSERVACIONES"].astype(str).str.lower().str.contains(buscar, na=False)
        )
        df = df[mask]
    order_map = {"VENCIDO":0, "POR VENCER":1, "EN MARCHA":2, "SIN FECHA":3}
    df["ORDEN"] = df["CONTROL_VENCIMIENTO"].map(order_map).fillna(9)
    df = df.sort_values(by=["ORDEN","FECHA_VENCIMIENTO"], ascending=[True,True], na_position="last")
    return df.drop(columns=["ORDEN"], errors="ignore")

def find_single_bpms_row(radicado, user):
    df = filtered_bpms(user, "TODOS", "TODOS", "")
    match = df[df["RADICADO"].astype(str) == str(radicado).strip()]
    if match.empty:
        return None
    return match.iloc[0].to_dict()

@app.route("/", methods=["GET","POST"])
def login():
    if request.method == "POST":
        user = authenticate(request.form.get("username",""), request.form.get("password",""))
        if user:
            session["username"] = user["username"]
            if int(user["force_password_change"]) == 1:
                flash("Debes cambiar tu contraseña antes de continuar.", "danger")
                return redirect(url_for("change_password"))
            return redirect(url_for("dashboard"))
        flash("Usuario o contraseña incorrectos", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
def dashboard():
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    funcionario = request.args.get("funcionario","TODOS")
    estado = request.args.get("estado","TODOS")
    buscar = request.args.get("buscar","")
    df = filtered_bpms(user, funcionario, estado, buscar)
    counts = {
        "total": int(len(df)),
        "en_marcha": int((df["CONTROL_VENCIMIENTO"]=="EN MARCHA").sum()) if not df.empty else 0,
        "por_vencer": int((df["CONTROL_VENCIMIENTO"]=="POR VENCER").sum()) if not df.empty else 0,
        "vencidos": int((df["CONTROL_VENCIMIENTO"]=="VENCIDO").sum()) if not df.empty else 0,
        "sin_fecha": int((df["CONTROL_VENCIMIENTO"]=="SIN FECHA").sum()) if not df.empty else 0,
    }
    if user["role"] == "admin":
        funcionarios = ["TODOS"] + allowed_hacienda_names()
    else:
        perms = sorted(get_user_permissions(user["id"]))
        funcionarios = ["TODOS"] + perms if len(perms) > 1 else (perms or [normalize_text(user["full_name"])])
    rows = []
    for _,r in df.head(300).iterrows():
        rows.append({
            "RADICADO": r["RADICADO"],
            "FUNCIONARIO": r["FUNCIONARIO"],
            "TIPO_SOLICITUD": r["TIPO_SOLICITUD"],
            "FECHA_VENCIMIENTO": fmt_date(r["FECHA_VENCIMIENTO"]),
            "DIAS_RESTANTES": "" if pd.isna(r["DIAS_RESTANTES"]) else int(r["DIAS_RESTANTES"]),
            "CONTROL_VENCIMIENTO": r["CONTROL_VENCIMIENTO"],
            "ESTADO_TRAMITE_ACTUAL": r["ESTADO_TRAMITE_ACTUAL"],
            "OBSERVACIONES": r["OBSERVACIONES"],
        })
    return render_template("dashboard.html", title="Dashboard", user=user, counts=counts, rows=rows, funcionarios=funcionarios, funcionario_actual=funcionario, estado_actual=estado, buscar_actual=buscar)

@app.route("/ranking")
def ranking():
    user = current_user()
    if not user:
        return redirect(url_for("login"))

    funcionario = request.args.get("funcionario", "TODOS")
    estado = request.args.get("estado", "TODOS")
    buscar = request.args.get("buscar", "")

    df = filtered_bpms(user, funcionario, estado, buscar)
    ranking_rows = []
    if not df.empty:
        grp = df.groupby("FUNCIONARIO").agg(
            TOTAL=("RADICADO", "count"),
            EN_MARCHA=("CONTROL_VENCIMIENTO", lambda s: int((s == "EN MARCHA").sum())),
            POR_VENCER=("CONTROL_VENCIMIENTO", lambda s: int((s == "POR VENCER").sum())),
            VENCIDOS=("CONTROL_VENCIMIENTO", lambda s: int((s == "VENCIDO").sum())),
        ).reset_index().sort_values(["TOTAL", "VENCIDOS", "POR_VENCER"], ascending=[False, False, False])

        for _, rr in grp.iterrows():
            ranking_rows.append({
                "FUNCIONARIO": rr["FUNCIONARIO"],
                "TOTAL": int(rr["TOTAL"]),
                "EN_MARCHA": int(rr["EN_MARCHA"]),
                "POR_VENCER": int(rr["POR_VENCER"]),
                "VENCIDOS": int(rr["VENCIDOS"]),
            })

    return render_template(
        "ranking.html",
        title="Ranking",
        user=user,
        ranking_rows=ranking_rows,
        funcionario_actual=funcionario,
        estado_actual=estado,
        buscar_actual=buscar,
    )


@app.route("/export")
def export_preview():
    user = current_user()
    if not user:
        return redirect(url_for("login"))

    funcionario = request.args.get("funcionario", "TODOS")
    estado = request.args.get("estado", "TODOS")
    buscar = request.args.get("buscar", "")

    df = filtered_bpms(user, funcionario, estado, buscar).copy()
    if df.empty:
        flash("No hay datos para exportar con los filtros actuales.", "danger")
        return redirect(url_for("dashboard", funcionario=funcionario, estado=estado, buscar=buscar))

    export_df = df.copy()
    export_df["FECHA_VENCIMIENTO"] = export_df["FECHA_VENCIMIENTO"].apply(fmt_date)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        export_df.to_excel(writer, sheet_name="BPMS", index=False)
        summary = pd.DataFrame([{
            "total": int(len(df)),
            "en_marcha": int((df["CONTROL_VENCIMIENTO"]=="EN MARCHA").sum()),
            "por_vencer": int((df["CONTROL_VENCIMIENTO"]=="POR VENCER").sum()),
            "vencidos": int((df["CONTROL_VENCIMIENTO"]=="VENCIDO").sum()),
            "sin_fecha": int((df["CONTROL_VENCIMIENTO"]=="SIN FECHA").sum()),
            "funcionario_filtro": funcionario,
            "estado_filtro": estado,
            "buscar": buscar,
        }])
        summary.to_excel(writer, sheet_name="Resumen", index=False)
    output.seek(0)

    filename = f"BPMS_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(output, as_attachment=True, download_name=filename, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/change-password", methods=["GET","POST"])
def change_password():
    user = current_user()
    if not user:
        return redirect(url_for("login"))

    force_mode = int(user["force_password_change"]) == 1

    if request.method == "POST":
        old_password = request.form.get("old_password", "").strip()
        new_password = request.form.get("new_password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        if not verify_user_password(user["id"], old_password):
            flash("La contraseña actual no es correcta.", "danger")
        elif len(new_password) < 6:
            flash("La nueva contraseña debe tener al menos 6 caracteres.", "danger")
        elif new_password != confirm_password:
            flash("La nueva contraseña y su confirmación no coinciden.", "danger")
        elif old_password == new_password:
            flash("La nueva contraseña debe ser diferente a la actual.", "danger")
        else:
            change_user_password(user["id"], new_password)
            flash("Contraseña actualizada correctamente.", "success")
            return redirect(url_for("dashboard"))

    return render_template("change_password.html", title="Cambiar contraseña", user=user, force_mode=force_mode)


@app.route("/edit/<radicado>", methods=["GET","POST"])
def edit_bpms(radicado):
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    row = find_single_bpms_row(radicado, user)
    if row is None:
        flash("No tienes acceso a ese radicado o no existe en la base filtrada.", "danger")
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        estado = request.form.get("estado","").strip()
        fecha = normalize_input_date(request.form.get("fecha", "").strip())
        observaciones = request.form.get("observaciones","").strip()
        try:
            conn = db()
            conn.execute("""
                INSERT INTO bpms_updates(radicado, observaciones, estado_tramite_actual, fecha_vencimiento, updated_by, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(radicado) DO UPDATE SET
                    observaciones=excluded.observaciones,
                    estado_tramite_actual=excluded.estado_tramite_actual,
                    fecha_vencimiento=excluded.fecha_vencimiento,
                    updated_by=excluded.updated_by,
                    updated_at=excluded.updated_at
            """, (str(radicado).strip(), observaciones, estado, fecha, user["username"], datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()
            conn.close()
            flash("Registro actualizado correctamente.", "success")
            return redirect(url_for("dashboard"))
        except Exception as e:
            log_error("edit_bpms_save", e)
            flash("Ocurrió un error al guardar. Revisa error.log", "danger")
    data = query_one("SELECT * FROM bpms_updates WHERE radicado=?", (str(radicado).strip(),))
    current_fecha = ""
    if data and data["fecha_vencimiento"]:
        current_fecha = normalize_input_date(data["fecha_vencimiento"])
    elif row.get("FECHA_VENCIMIENTO"):
        current_fecha = normalize_input_date(row.get("FECHA_VENCIMIENTO"))
    return render_template("edit.html", title="Editar BPMS", user=user, radicado=radicado, row=row, data=data, current_fecha=current_fecha)

@app.route("/admin/users", methods=["GET","POST"])
def admin_users():
    user = current_user()
    if not user or user["role"] != "admin":
        return redirect(url_for("login"))

    edit_user_id = request.args.get("edit_user_id", "")
    edit_user = get_user_by_id(int(edit_user_id)) if str(edit_user_id).isdigit() else None

    if request.method == "POST":
        action = request.form.get("action","create")
        if action == "create":
            username = request.form.get("username","").strip()
            full_name = normalize_text(request.form.get("full_name",""))
            role = request.form.get("role","user")
            is_active = 1 if request.form.get("is_active") == "on" else 0
            perms = request.form.getlist("permissions")
            force_password_change = 1 if request.form.get("force_password_change") == "on" else 0
            if not username:
                flash("Escribe un usuario.", "danger")
            else:
                try:
                    conn = db()
                    conn.execute("INSERT INTO users(username,password_hash,role,full_name,is_active,force_password_change) VALUES (?,?,?,?,?,?)", (username, hash_password("123456"), role, full_name, is_active, force_password_change or 1))
                    uid = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
                    if role == "admin":
                        perms = allowed_hacienda_names()
                    for name in perms:
                        conn.execute("INSERT OR IGNORE INTO user_permissions(user_id, funcionario_name) VALUES (?,?)", (uid, normalize_text(name)))
                    conn.commit()
                    conn.close()
                    flash("Usuario creado. Clave temporal: 123456", "success")
                except sqlite3.IntegrityError:
                    flash("Ese usuario ya existe.", "danger")

        elif action == "update":
            uid = int(request.form.get("user_id"))
            username = request.form.get("username","").strip()
            full_name = normalize_text(request.form.get("full_name",""))
            role = request.form.get("role","user")
            is_active = 1 if request.form.get("is_active") == "on" else 0
            perms = request.form.getlist("permissions")
            force_password_change = 1 if request.form.get("force_password_change") == "on" else 0
            try:
                conn = db()
                conn.execute("UPDATE users SET username=?, role=?, full_name=?, is_active=?, force_password_change=? WHERE id=?", (username, role, full_name, is_active, force_password_change, uid))
                conn.execute("DELETE FROM user_permissions WHERE user_id=?", (uid,))
                if role == "admin":
                    perms = allowed_hacienda_names()
                for name in perms:
                    conn.execute("INSERT OR IGNORE INTO user_permissions(user_id, funcionario_name) VALUES (?,?)", (uid, normalize_text(name)))
                conn.commit()
                conn.close()
                flash("Usuario actualizado correctamente.", "success")
            except sqlite3.IntegrityError:
                flash("No se pudo actualizar. El usuario ya existe.", "danger")

        elif action == "reset":
            uid = int(request.form.get("user_id"))
            execute("UPDATE users SET password_hash=?, force_password_change=1 WHERE id=?", (hash_password("123456"), uid))
            flash("Clave restablecida a 123456", "success")

        elif action == "toggle":
            uid = int(request.form.get("user_id"))
            target = get_user_by_id(uid)
            if target and target["username"] != "admin":
                execute("UPDATE users SET is_active=? WHERE id=?", (0 if int(target["is_active"]) else 1, uid))
                flash("Estado del usuario actualizado.", "success")

        return redirect(url_for("admin_users"))

    edit_permissions = get_user_permissions(edit_user["id"]) if edit_user else []
    return render_template("admin_users.html", title="Usuarios", user=user, users=list_users(), hacienda_names=allowed_hacienda_names(), edit_user=edit_user, edit_permissions=edit_permissions)

@app.route("/admin/hacienda", methods=["GET","POST"])
def admin_hacienda():
    user = current_user()
    if not user or user["role"] != "admin":
        return redirect(url_for("login"))

    edit_staff_id = request.args.get("edit_staff_id", "")
    edit_staff = get_staff_by_id(int(edit_staff_id)) if str(edit_staff_id).isdigit() else None

    if request.method == "POST":
        action = request.form.get("action","create")
        if action == "create":
            name = normalize_text(request.form.get("name",""))
            status = request.form.get("status","Activo")
            dependency = request.form.get("dependency","")
            include_flag = 1 if request.form.get("include_flag") == "on" else 0
            if name:
                try:
                    execute("INSERT INTO hacienda_staff(name,status,dependency,include_flag) VALUES (?,?,?,?)", (name, status, dependency, include_flag))
                    flash("Funcionario agregado.", "success")
                except sqlite3.IntegrityError:
                    flash("Ese funcionario ya existe.", "danger")
        elif action == "update":
            staff_id = int(request.form.get("staff_id"))
            name = normalize_text(request.form.get("name",""))
            status = request.form.get("status","Activo")
            dependency = request.form.get("dependency","")
            include_flag = 1 if request.form.get("include_flag") == "on" else 0
            try:
                execute("UPDATE hacienda_staff SET name=?, status=?, dependency=?, include_flag=? WHERE id=?", (name, status, dependency, include_flag, staff_id))
                flash("Funcionario actualizado.", "success")
            except sqlite3.IntegrityError:
                flash("No se pudo actualizar. Ese nombre ya existe.", "danger")
        elif action == "toggle":
            staff_id = int(request.form.get("staff_id"))
            row = query_one("SELECT * FROM hacienda_staff WHERE id=?", (staff_id,))
            if row:
                execute("UPDATE hacienda_staff SET include_flag=? WHERE id=?", (0 if int(row["include_flag"]) else 1, staff_id))
                flash("Inclusión actualizada.", "success")
        elif action == "sync_users":
            created = sync_users_from_hacienda()
            flash(f"Usuarios creados automáticamente: {created}", "success")
        return redirect(url_for("admin_hacienda"))

    return render_template("admin_hacienda.html", title="Lista Hacienda", user=user, staff=list_hacienda_staff(), edit_staff=edit_staff)

@app.route("/admin/upload", methods=["GET","POST"])
def admin_upload():
    user = current_user()
    if not user or user["role"] != "admin":
        return redirect(url_for("login"))
    if request.method == "POST":
        file = request.files.get("report")
        if file and file.filename.endswith(".xlsx"):
            try:
                file.save(REPORT_PATH)
                flash("Archivo Excel actualizado correctamente.", "success")
                return redirect(url_for("dashboard"))
            except Exception as e:
                log_error("admin_upload", e)
                flash("Error al guardar el archivo.", "danger")
        else:
            flash("Por favor selecciona un archivo .xlsx válido.", "danger")
    return render_template("upload.html", title="Cargar Excel", user=user)

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
