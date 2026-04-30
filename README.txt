BPMS Web Enterprise Editable

Esta versión corrige:
- filtro solo Hacienda
- login sin credenciales visibles
- módulos admin: Usuarios y Lista Hacienda
- edición de BPMS desde la web

Uso:
1. descomprime
2. pon Reporte BPMS.xlsx en la carpeta
3. ejecuta start_bpms_tray.bat
4. entra a http://127.0.0.1:5000


Ajuste v2:
- Los filtros de funcionario y estado ahora se autoaplican al cambiar la selección.


Ajuste v3:
- corregido manejo de fechas al editar BPMS para evitar errores al volver al dashboard.


Ajuste v4:
- normalización de fechas con guion o slash al editar BPMS.
- el formulario de edición ahora recibe la fecha ya normalizada en formato YYYY-MM-DD.


Ajuste v5:
- ahora registra errores en error.log.
- incluye run_visible_debug.bat para ver el traceback si vuelve a fallar.


Ajuste v6:
- corregido el merge de bpms_updates para evitar choque de nombres de columnas como fecha_vencimiento.


Ajuste v7:
- menú para cambiar contraseña en todos los usuarios.
- exportación a Excel de lo actualmente previsualizado según filtros.


Ajuste v8:
- agregado Resumen por Funcionario en dashboard.
- cuando el filtro está en TODOS, muestra el ranking completo.
- si seleccionas un funcionario, el resumen se ajusta a esa vista.


Ajuste v9:
- el ranking ahora vive en una vista dinámica separada llamada Ranking.
- desde Dashboard puedes ir a Ranking y volver con el botón Dashboard del menú.


Ajuste v10:
- edición de funcionarios en Lista Hacienda.
- edición de usuarios.
- cambio obligatorio de clave en primer ingreso si force_password_change=1.
- última sesión ya queda guardada en last_login_at y visible en usuarios.
