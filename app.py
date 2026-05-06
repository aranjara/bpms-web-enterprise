import os, hashlib, json, traceback, io
import pandas as pd
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
from dotenv import load_dotenv

import database
import bpms_service

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-key-fallback")
UPLOAD_FOLDER = Path(os.getenv("UPLOAD_FOLDER", "uploads"))
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

# Helper functions
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def log_error(where, exc):
    log_path = os.getenv("LOG_PATH", "error.log")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"\n[{datetime.now()}] {where}: {exc}\n{traceback.format_exc()}\n")

def current_user():
    username = session.get("username")
    return database.query_one("SELECT * FROM users WHERE username=?", (username,)) if username else None

def fmt_date(value):
    if not value or str(value) == 'NaT': return ""
    return value.strftime("%Y-%m-%d") if hasattr(value, "strftime") else str(value)

# Routes
@app.route("/", methods=["GET","POST"])
def login():
    if request.method == "POST":
        u, p = request.form.get("username",""), request.form.get("password","")
        user = database.query_one("SELECT * FROM users WHERE username=? AND is_active=1", (u,))
        if user and user["password_hash"] == hash_password(p):
            session["username"] = user["username"]
            database.execute("UPDATE users SET last_login_at=? WHERE id=?", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user["id"]))
            database.execute("INSERT INTO audit_logs(user_id, action, details, created_at) VALUES (?,?,?,?)",
                            (user["id"], "LOGIN", f"Acceso exitoso: {u}", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            if int(user["force_password_change"]) == 1:
                flash("Debes cambiar tu contraseña.", "danger")
                return redirect(url_for("change_password"))
            return redirect(url_for("dashboard"))
        flash("Credenciales inválidas", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
def dashboard():
    user = current_user()
    if not user: return redirect(url_for("login"))
    
    func = request.args.get("funcionario","TODOS")
    stat = request.args.get("estado","TODOS")
    seek = request.args.get("buscar","")
    
    df = bpms_service.get_filtered_data(user, func, stat, seek)

    counts = {
        "total": len(df),
        "en_marcha": int((df["CONTROL_VENCIMIENTO"]=="EN MARCHA").sum()),
        "por_vencer": int((df["CONTROL_VENCIMIENTO"]=="POR VENCER").sum()),
        "vencidos": int((df["CONTROL_VENCIMIENTO"]=="VENCIDO").sum()),
        "sin_fecha": int((df["CONTROL_VENCIMIENTO"]=="SIN FECHA").sum()),
    }

    # Chart data
    chart_data = {"staff_labels": [], "staff_values": []}
    if not df.empty:
        top = df["FUNCIONARIO"].value_counts().head(10)
        chart_data["staff_labels"] = list(top.index)
        chart_data["staff_values"] = [int(v) for v in top.values]

    # Allowed officials for filter
    if user["role"] == "admin":
        hacienda = [s["name"] for s in database.query_all("SELECT name FROM hacienda_staff WHERE include_flag=1 ORDER BY name")]
        funcionarios = ["TODOS"] + hacienda
    else:
        perms = [p["funcionario_name"] for p in database.query_all("SELECT funcionario_name FROM user_permissions WHERE user_id=?", (user["id"],))]
        funcionarios = ["TODOS"] + sorted(perms) if len(perms) > 1 else (perms or [bpms_service.normalize_text(user["full_name"])])

    return render_template("dashboard.html", title="Dashboard", user=user, counts=counts, 
                           funcionarios=funcionarios, funcionario_actual=func, estado_actual=stat, buscar_actual=seek,
                           chart_data=chart_data)

@app.route("/registros")
def registros():
    user = current_user()
    if not user: return redirect(url_for("login"))
    
    func = request.args.get("funcionario","TODOS")
    stat = request.args.get("estado","TODOS")
    seek = request.args.get("buscar","")
    page = request.args.get("page", 1, type=int)
    
    df = bpms_service.get_filtered_data(user, func, stat, seek)
    per_page = 50
    total_pages = (len(df) + per_page - 1) // per_page
    df_paged = df.iloc[(page-1)*per_page : page*per_page]

    rows = []
    for _, r in df_paged.iterrows():
        rows.append({
            "RADICADO": r["RADICADO"], "FUNCIONARIO": r["FUNCIONARIO"], "TIPO_SOLICITUD": r["TIPO_SOLICITUD"],
            "FECHA_VENCIMIENTO": fmt_date(r["FECHA_VENCIMIENTO"]), "DIAS_RESTANTES": int(r["DIAS_RESTANTES"]) if not bpms_service.pd.isna(r["DIAS_RESTANTES"]) else "",
            "CONTROL_VENCIMIENTO": r["CONTROL_VENCIMIENTO"], "ESTADO_TRAMITE_ACTUAL": r["ESTADO_TRAMITE_ACTUAL"], "OBSERVACIONES": r["OBSERVACIONES"]
        })

    # Allowed officials for filter
    if user["role"] == "admin":
        hacienda = [s["name"] for s in database.query_all("SELECT name FROM hacienda_staff WHERE include_flag=1 ORDER BY name")]
        funcionarios = ["TODOS"] + hacienda
    else:
        perms = [p["funcionario_name"] for p in database.query_all("SELECT funcionario_name FROM user_permissions WHERE user_id=?", (user["id"],))]
        funcionarios = ["TODOS"] + sorted(perms) if len(perms) > 1 else (perms or [bpms_service.normalize_text(user["full_name"])])

    return render_template("registros.html", title="Registros", user=user, rows=rows, 
                           funcionarios=funcionarios, funcionario_actual=func, estado_actual=stat, buscar_actual=seek,
                           page=page, total_pages=total_pages)

@app.route("/edit/<radicado>", methods=["GET","POST"])
def edit_bpms(radicado):
    user = current_user()
    if not user: return redirect(url_for("login"))
    
    if request.method == "POST":
        est = request.form.get("estado","").strip()
        fec = request.form.get("fecha","").strip()
        obs = request.form.get("observaciones","").strip()
        database.execute("""
            INSERT INTO bpms_updates(radicado, observaciones, estado_tramite_actual, fecha_vencimiento, updated_by, updated_at)
            VALUES (?,?,?,?,?,?) ON CONFLICT(radicado) DO UPDATE SET 
            observaciones=excluded.observaciones, estado_tramite_actual=excluded.estado_tramite_actual, 
            fecha_vencimiento=excluded.fecha_vencimiento, updated_by=excluded.updated_by, updated_at=excluded.updated_at
        """, (radicado, obs, est, fec, user["username"], datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        database.execute("INSERT INTO audit_logs(user_id, action, details, radicado, created_at) VALUES (?,?,?,?,?)",
                        (user["id"], "EDIT_BPMS", f"Cambios en radicado {radicado}", radicado, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        bpms_service.load_bpms(force_reload=True)
        flash("Actualizado correctamente", "success")
        return redirect(url_for("dashboard"))

    df = bpms_service.load_bpms()
    row = df[df["RADICADO"] == str(radicado)].iloc[0].to_dict() if not df[df["RADICADO"] == str(radicado)].empty else None
    if not row: return redirect(url_for("dashboard"))
    
    data = database.query_one("SELECT * FROM bpms_updates WHERE radicado=?", (radicado,))
    attachments = database.query_all("SELECT * FROM attachments WHERE radicado=? ORDER BY uploaded_at DESC", (radicado,))
    curr_fec = data["fecha_vencimiento"] if data and data["fecha_vencimiento"] else fmt_date(row["FECHA_VENCIMIENTO"])
    
    return render_template("edit.html", title="Editar", user=user, radicado=radicado, row=row, data=data, current_fecha=curr_fec, attachments=attachments)

@app.route("/admin/audit")
def admin_audit():
    user = current_user()
    if not user or user["role"] != "admin": return redirect(url_for("login"))
    
    uid = request.args.get("user_id", "")
    start = request.args.get("start_date", "")
    end = request.args.get("end_date", "")
    
    query = "SELECT a.*, u.username FROM audit_logs a LEFT JOIN users u ON a.user_id = u.id WHERE 1=1"
    params = []
    
    if uid:
        query += " AND a.user_id = ?"
        params.append(uid)
    if start:
        query += " AND a.created_at >= ?"
        params.append(f"{start} 00:00:00")
    if end:
        query += " AND a.created_at <= ?"
        params.append(f"{end} 23:59:59")
        
    query += " ORDER BY a.created_at DESC LIMIT 500"
    logs = database.query_all(query, tuple(params))
    users = database.query_all("SELECT id, username, full_name FROM users ORDER BY full_name")
    
    return render_template("admin_audit.html", title="Auditoría", user=user, logs=logs, 
                           users_list=users, current_uid=uid, current_start=start, current_end=end)

@app.route("/admin/users", methods=["GET","POST"])
def admin_users():
    user = current_user()
    if not user or user["role"] != "admin": return redirect(url_for("login"))
    edit_id = request.args.get("edit_user_id")
    edit_user = database.query_one("SELECT * FROM users WHERE id=?", (edit_id,)) if edit_id else None
    
    if request.method == "POST":
        act = request.form.get("action")
        if act in ["create", "update"]:
            un = request.form.get("username").strip()
            fn = bpms_service.normalize_text(request.form.get("full_name"))
            ro = request.form.get("role")
            ac = 1 if request.form.get("is_active") == "on" else 0
            pw = 1 if request.form.get("force_password_change") == "on" else 0
            new_pwd = request.form.get("new_password")
            
            if act == "create":
                initial_pwd = hash_password(new_pwd if new_pwd else "123456")
                database.execute("INSERT INTO users(username,password_hash,role,full_name,is_active,force_password_change) VALUES (?,?,?,?,?,?)",
                                 (un, initial_pwd, ro, fn, ac, pw))
                uid = database.query_one("SELECT id FROM users WHERE username=?", (un,))["id"]
            else:
                uid = int(request.form.get("user_id"))
                database.execute("UPDATE users SET username=?, role=?, full_name=?, is_active=?, force_password_change=? WHERE id=?", (un, ro, fn, ac, pw, uid))
                if new_pwd:
                    database.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new_pwd), uid))
                database.execute("DELETE FROM user_permissions WHERE user_id=?", (uid,))
            
            perms = request.form.getlist("permissions") if ro == "user" else [s["name"] for s in database.query_all("SELECT name FROM hacienda_staff WHERE include_flag=1")]
            for p in perms: database.execute("INSERT INTO user_permissions(user_id, funcionario_name) VALUES (?,?)", (uid, p))
            flash("Usuario guardado", "success")
        elif act == "toggle":
            uid = int(request.form.get("user_id"))
            database.execute("UPDATE users SET is_active = 1 - is_active WHERE id=?", (uid,))
            flash("Estado cambiado", "success")
        return redirect(url_for("admin_users"))

    users = database.query_all("SELECT * FROM users ORDER BY full_name")
    staff = [s["name"] for s in database.query_all("SELECT name FROM hacienda_staff WHERE include_flag=1 ORDER BY name")]
    edit_perms = [p["funcionario_name"] for p in database.query_all("SELECT funcionario_name FROM user_permissions WHERE user_id=?", (edit_id,))] if edit_id else []
    return render_template("admin_users.html", title="Usuarios", user=user, users=users, hacienda_names=staff, edit_user=edit_user, edit_permissions=edit_perms)

@app.route("/attachments/upload/<radicado>", methods=["POST"])
def upload_attachment(radicado):
    user = current_user()
    if not user: return redirect(url_for("login"))
    f = request.files.get("file")
    if f:
        fn = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{f.filename}"
        f.save(str(UPLOAD_FOLDER / fn))
        database.execute("INSERT INTO attachments(radicado, filename, file_path, uploaded_by, uploaded_at) VALUES (?,?,?,?,?)",
                        (radicado, f.filename, fn, user["username"], datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        flash("Archivo subido", "success")
    return redirect(url_for("edit_bpms", radicado=radicado))

@app.route("/attachments/download/<int:id>")
def download_attachment(id):
    att = database.query_one("SELECT * FROM attachments WHERE id=?", (id,))
    return send_file(str(UPLOAD_FOLDER / att["file_path"]), as_attachment=True, download_name=att["filename"]) if att else "No encontrado"

@app.route("/admin/hacienda", methods=["GET","POST"])
def admin_hacienda():
    user = current_user()
    if not user or user["role"] != "admin": return redirect(url_for("login"))
    edit_id = request.args.get("edit_staff_id")
    edit_staff = database.query_one("SELECT * FROM hacienda_staff WHERE id=?", (edit_id,)) if edit_id else None
    if request.method == "POST":
        act = request.form.get("action")
        if act in ["create", "update"]:
            name = bpms_service.normalize_text(request.form.get("name"))
            stat = request.form.get("status")
            dep = request.form.get("dependency")
            inc = 1 if request.form.get("include_flag") == "on" else 0
            if act == "create": database.execute("INSERT INTO hacienda_staff(name,status,dependency,include_flag) VALUES (?,?,?,?)", (name, stat, dep, inc))
            else: database.execute("UPDATE hacienda_staff SET name=?, status=?, dependency=?, include_flag=? WHERE id=?", (name, stat, dep, inc, int(request.form.get("staff_id"))))
            flash("Funcionario guardado", "success")
        elif act == "toggle":
            sid = request.form.get("staff_id")
            if sid:
                database.execute("UPDATE hacienda_staff SET include_flag = CASE WHEN include_flag = 1 THEN 0 ELSE 1 END WHERE id=?", (sid,))
                flash("Estado de inclusión actualizado", "success")
            else:
                flash("Error: ID de funcionario no encontrado", "danger")
        elif act == "sync_users":
            staff = database.query_all("SELECT id, name FROM hacienda_staff WHERE include_flag=1")
            count = 0
            for s in staff:
                exists = database.query_one("SELECT id FROM users WHERE full_name=?", (s["name"],))
                if not exists:
                    parts = s["name"].split()
                    if len(parts) >= 3:
                        # Estructura: Primera letra nombre + primer apellido
                        # Ejemplo: Jhoan Orlando Arango Jaramillo -> j + arango
                        first_initial = parts[0][0].lower()
                        first_surname = parts[2].lower() if len(parts) >= 3 else parts[1].lower()
                        un = f"{first_initial}{first_surname}"
                        
                        if database.query_one("SELECT 1 FROM users WHERE username=?", (un,)):
                            # Conflicto: añadir primera letra del segundo apellido
                            second_surname_initial = parts[3][0].lower() if len(parts) >= 4 else ""
                            un = f"{un}{second_surname_initial}"
                            
                            # Si sigue existiendo, añadir ID como último recurso
                            if database.query_one("SELECT 1 FROM users WHERE username=?", (un,)):
                                un = f"{un}{s['id']}"
                    else:
                        # Fallback para nombres cortos (ej: Juan Perez)
                        un = (parts[0][0] + parts[-1]).lower()
                        if database.query_one("SELECT 1 FROM users WHERE username=?", (un,)):
                            un = f"{un}{s['id']}"

                    database.execute("INSERT INTO users(username, password_hash, role, full_name, is_active, force_password_change) VALUES (?,?,?,?,?,?)",
                                     (un, hash_password("123456"), "user", s["name"], 1, 1))
                    uid = database.query_one("SELECT id FROM users WHERE username=?", (un,))["id"]
                    database.execute("INSERT INTO user_permissions(user_id, funcionario_name) VALUES (?,?)", (uid, s["name"]))
                    count += 1
            flash(f"Se crearon {count} nuevos usuarios automáticamente", "success" if count > 0 else "info")
        return redirect(url_for("admin_hacienda"))
    staff = database.query_all("SELECT * FROM hacienda_staff ORDER BY name")
    return render_template("admin_hacienda.html", title="Hacienda", user=user, staff=staff, edit_staff=edit_staff)

@app.route("/admin/upload", methods=["POST","GET"])
def admin_upload():
    user = current_user()
    if not user or user["role"] != "admin": return redirect(url_for("login"))
    if request.method == "POST":
        f = request.files.get("report")
        if f and f.filename.endswith(".xlsx"):
            f.save(os.getenv("REPORT_PATH", "Reporte BPMS.xlsx"))
            bpms_service.load_bpms(force_reload=True)
            flash("Excel actualizado", "success")
            return redirect(url_for("dashboard"))
    return render_template("upload.html", title="Cargar", user=user)

@app.route("/change-password", methods=["GET","POST"])
def change_password():
    user = current_user()
    if not user: return redirect(url_for("login"))
    if request.method == "POST":
        old, new, conf = request.form.get("old_password"), request.form.get("new_password"), request.form.get("confirm_password")
        if hash_password(old) == user["password_hash"] and len(new) >= 6 and new == conf:
            database.execute("UPDATE users SET password_hash=?, force_password_change=0 WHERE id=?", (hash_password(new), user["id"]))
            flash("Clave cambiada", "success")
            return redirect(url_for("dashboard"))
        flash("Error en los datos", "danger")
    return render_template("change_password.html", title="Clave", user=user, force_mode=int(user["force_password_change"])==1)

@app.route("/ranking")
def ranking():
    user = current_user()
    if not user: return redirect(url_for("login"))
    df = bpms_service.get_filtered_data(user, request.args.get("funcionario","TODOS"), request.args.get("estado","TODOS"), request.args.get("buscar",""))
    rank = []
    if not df.empty:
        grp = df.groupby("FUNCIONARIO").agg(TOTAL=("RADICADO", "count"), EN_MARCHA=("CONTROL_VENCIMIENTO", lambda s: int((s == "EN MARCHA").sum())), VENCIDOS=("CONTROL_VENCIMIENTO", lambda s: int((s == "VENCIDO").sum()))).reset_index().sort_values("TOTAL", ascending=False)
        rank = grp.to_dict("records")
    return render_template("ranking.html", title="Ranking", user=user, ranking_rows=rank, funcionario_actual=request.args.get("funcionario","TODOS"))

@app.route("/export/preview")
def export_preview():
    user = current_user()
    if not user: return redirect(url_for("login"))
    func, stat, seek = request.args.get("funcionario","TODOS"), request.args.get("estado","TODOS"), request.args.get("buscar","")
    df = bpms_service.get_filtered_data(user, func, stat, seek)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Reporte")
    output.seek(0)
    fn = f"Reporte_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(output, as_attachment=True, download_name=fn, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

@app.route("/admin/export/<target>")
def admin_export(target):
    user = current_user()
    if not user or user["role"] != "admin": return redirect(url_for("login"))
    
    fmt = request.args.get("fmt", "excel")
    data = []
    
    if target == "hacienda":
        data = database.query_all("SELECT name, status, dependency FROM hacienda_staff ORDER BY name")
        title = "Reporte de Funcionarios"
    elif target == "users":
        data = database.query_all("SELECT username, role, full_name, is_active FROM users ORDER BY full_name")
        title = "Reporte de Usuarios"
    elif target == "audit":
        uid = request.args.get("user_id", "")
        start = request.args.get("start_date", "")
        end = request.args.get("end_date", "")
        query = "SELECT a.created_at, u.username, a.action, a.radicado FROM audit_logs a LEFT JOIN users u ON a.user_id = u.id WHERE 1=1"
        params = []
        if uid: query += " AND a.user_id = ?"; params.append(uid)
        if start: query += " AND a.created_at >= ?"; params.append(f"{start} 00:00:00")
        if end: query += " AND a.created_at <= ?"; params.append(f"{end} 23:59:59")
        query += " ORDER BY a.created_at DESC LIMIT 1000"
        data = database.query_all(query, tuple(params))
        title = "Historial de Auditoría"
    else:
        return "Objetivo no válido", 400

    if fmt == "excel":
        df = pd.DataFrame(data)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name=target.capitalize())
        output.seek(0)
        fn = f"Export_{target}_{datetime.now().strftime('%Y%m%d')}.xlsx"
        return send_file(output, as_attachment=True, download_name=fn, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    
    elif fmt == "pdf":
        output = io.BytesIO()
        doc = SimpleDocTemplate(output, pagesize=landscape(letter))
        elements = []
        styles = getSampleStyleSheet()
        elements.append(Paragraph(f"<b>{title}</b>", styles['Title']))
        elements.append(Paragraph(f"Generado el: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))
        
        if data:
            headers = list(data[0].keys())
            table_data = [headers] + [[str(row[h]) for h in headers] for row in data]
            t = Table(table_data)
            t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 0), (-1, -1), colors.beige if not user.get('theme')=='dark' else colors.whitesmoke),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            elements.append(t)
        
        doc.build(elements)
        output.seek(0)
        fn = f"Export_{target}_{datetime.now().strftime('%Y%m%d')}.pdf"
        return send_file(output, as_attachment=True, download_name=fn, mimetype="application/pdf")

    return "Formato no soportado", 400

if __name__ == "__main__":
    database.init_db(hash_fn=hash_password)
    app.run(host="0.0.0.0", port=5000, debug=True)
