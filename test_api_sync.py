import requests
import json

url = "http://127.0.0.1:5000/api/v1/sync"
headers = {
    "X-API-KEY": "se-sync-b207751da3457441107e542ffe798303",
    "Content-Type": "application/json"
}

# Datos de prueba simulando SoftExpert
payload = [
    {
        "radicado": "TEST-2026-001",
        "funcionario": "JOSE ARANGO",
        "tipo_solicitud": "TRAMITE DE PRUEBA API",
        "fecha_vencimiento": "2026-12-31",
        "estado_tramite": "EN MARCHA",
        "descripcion": "Este registro fue enviado automaticamente mediante la API de prueba."
    },
    {
        "radicado": "TEST-2026-002",
        "funcionario": "ADMINISTRADOR",
        "tipo_solicitud": "URGENTE: VALIDACION SISTEMA",
        "fecha_vencimiento": "2026-05-10",
        "estado_tramite": "POR VENCER",
        "descripcion": "Validacion de integracion SoftExpert Suite v2.2"
    }
]

print("Enviando datos a la API...")
try:
    response = requests.post(url, headers=headers, data=json.dumps(payload))
    if response.status_code == 200:
        print("EXITO: La API recibio los datos correctamente.")
        print(f"Respuesta: {response.json()}")
    else:
        print(f"ERROR {response.status_code}: {response.text}")
except Exception as e:
    print(f"ERROR de conexion: {e}")
