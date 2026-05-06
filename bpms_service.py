import os, unicodedata
from datetime import date, datetime
import pandas as pd
from dotenv import load_dotenv
import database

load_dotenv()

REPORT_PATH = os.getenv("REPORT_PATH", "Reporte BPMS.xlsx")

# Simple in-memory cache
_cache = {
    "data": None,
    "last_loaded": None,
    "mtime": 0
}

def normalize_text(value):
    if value is None: return ""
    value = str(value).strip().upper()
    value = "".join(ch for ch in unicodedata.normalize("NFD", value) if unicodedata.category(ch) != "Mn")
    while "  " in value: value = value.replace("  ", " ")
    return value

def bpms_status(value):
    if pd.isna(value): return "SIN FECHA"
    days = (value.date() - date.today()).days
    if days < 0: return "VENCIDO"
    if days <= 3: return "POR VENCER"
    return "EN MARCHA"

def days_left(value):
    if pd.isna(value): return None
    if isinstance(value, str):
        value = pd.to_datetime(value, errors="coerce")
    if pd.isna(value): return None
    return (value.date() - date.today()).days

def load_bpms(force_reload=False):
    global _cache
    
    # Fallback to Excel (Main Source)
    if not os.path.exists(REPORT_PATH):
        return pd.DataFrame()
    
    current_mtime = os.path.getmtime(REPORT_PATH)
    if not force_reload and _cache["data"] is not None and _cache["mtime"] == current_mtime:
        return _cache["data"]

    # Load from Excel
    xl = pd.ExcelFile(REPORT_PATH)
    df = pd.read_excel(REPORT_PATH, sheet_name=xl.sheet_names[0])
    
    # Standardize columns
    df["RADICADO"] = df["radicado_inicial"].astype(str).str.strip() if "radicado_inicial" in df.columns else df.iloc[:,0].astype(str).str.strip()
    
    if "usuario_responsable_actividad" in df.columns:
        df["FUNCIONARIO"] = df["usuario_responsable_actividad"].apply(normalize_text)
    else:
        df["FUNCIONARIO"] = df.iloc[:,16].apply(normalize_text) if len(df.columns) > 16 else ""
        
    df["TIPO_SOLICITUD"] = df["descripcion"].fillna("").astype(str) if "descripcion" in df.columns else ""
    df["FECHA_VENCIMIENTO"] = pd.to_datetime(df["fecha_vencimiento"], errors="coerce") if "fecha_vencimiento" in df.columns else pd.NaT
    df["ESTADO_TRAMITE_ACTUAL"] = df["estado_tramite"].fillna("").astype(str) if "estado_tramite" in df.columns else ""
    df["OBSERVACIONES"] = ""

    # Merge with DB updates
    updates = pd.DataFrame(database.query_all("SELECT * FROM bpms_updates"))
    if not updates.empty:
        updates["radicado"] = updates["radicado"].astype(str).str.strip()
        updates["fecha_vencimiento"] = pd.to_datetime(updates["fecha_vencimiento"], errors="coerce")
        updates = updates.rename(columns={
            "observaciones": "OBS_DB",
            "estado_tramite_actual": "ESTADO_DB",
            "fecha_vencimiento": "FECHA_DB",
        })
        df = df.merge(updates[["radicado", "OBS_DB", "ESTADO_DB", "FECHA_DB"]], left_on="RADICADO", right_on="radicado", how="left")
        df["OBSERVACIONES"] = df["OBS_DB"].fillna("")
        df["ESTADO_TRAMITE_ACTUAL"] = df["ESTADO_DB"].fillna(df["ESTADO_TRAMITE_ACTUAL"])
        df["FECHA_VENCIMIENTO"] = df["FECHA_DB"].combine_first(df["FECHA_VENCIMIENTO"])
        df.drop(columns=["radicado", "OBS_DB", "ESTADO_DB", "FECHA_DB"], inplace=True, errors="ignore")

    df["CONTROL_VENCIMIENTO"] = df["FECHA_VENCIMIENTO"].apply(bpms_status)
    df["DIAS_RESTANTES"] = df["FECHA_VENCIMIENTO"].apply(days_left)
    
    result = df[["RADICADO","FUNCIONARIO","TIPO_SOLICITUD","FECHA_VENCIMIENTO","DIAS_RESTANTES","CONTROL_VENCIMIENTO","ESTADO_TRAMITE_ACTUAL","OBSERVACIONES"]].copy()
    
    # Update cache
    _cache["data"] = result
    _cache["mtime"] = os.path.getmtime(REPORT_PATH) if os.path.exists(REPORT_PATH) else 0
    _cache["last_loaded"] = datetime.now()
    
    return result

def get_filtered_data(user, funcionario="TODOS", estado="TODOS", buscar=""):
    df = load_bpms()
    if df.empty: return df
    
    # Filtering logic (Simplified for readability)
    if user["role"] != "admin":
        perms = database.query_all("SELECT funcionario_name FROM user_permissions WHERE user_id=?", (user["id"],))
        allowed = {p["funcionario_name"] for p in perms}
        if allowed:
            df = df[df["FUNCIONARIO"].isin(allowed)]
        else:
            df = df[df["FUNCIONARIO"] == normalize_text(user["full_name"])]
            
    if funcionario and funcionario != "TODOS":
        df = df[df["FUNCIONARIO"] == normalize_text(funcionario)]
        
    if estado and estado != "TODOS":
        df = df[df["CONTROL_VENCIMIENTO"] == estado]
        
    buscar = (buscar or "").strip().lower()
    if buscar:
        mask = df.apply(lambda row: buscar in str(row.values).lower(), axis=1)
        df = df[mask]
        
    order_map = {"VENCIDO":0, "POR VENCER":1, "EN MARCHA":2, "SIN FECHA":3}
    df["ORDEN"] = df["CONTROL_VENCIMIENTO"].map(order_map).fillna(9)
    return df.sort_values(by=["ORDEN","FECHA_VENCIMIENTO"]).drop(columns=["ORDEN"], errors="ignore")
