# Project Memory: BPMS Web Enterprise Modernizado

## Contexto del Proyecto
BPMS Web Enterprise es una plataforma para la gestión de trámites de Hacienda, que centraliza datos provenientes de reportes de Excel y permite el seguimiento manual, asignación de funcionarios y auditoría de cambios.

## Estado Actual (v1.1 - 2026-05-06)
Se ha completado la fase de **Modernización Avanzada**, elevando la aplicación de un MVP a una herramienta corporativa robusta.

### Funcionalidades Implementadas
- **UI/UX Premium**: Diseño con Glassmorphism y soporte nativo para **Modo Oscuro** (persistido en cookies).
- **Dashboard Estadístico**: Visualización con Chart.js (Donut para estados, Barras para carga por funcionario).
- **Paginación Backend**: Soporte para grandes volúmenes de datos (50 registros por página).
- **Sistema de Auditoría**: Registro detallado de acciones en la tabla `audit_logs`.
- **Gestión de Adjuntos**: Capacidad de subir/descargar archivos por radicado almacenados localmente en `/uploads`.
- **Administración**: Módulos para gestión de usuarios, permisos por funcionario y lista maestra de Hacienda.
- **Animaciones (GSAP)**: Se han "instalado" habilidades de GSAP en `/skills/gsap` para implementar micro-animaciones premium en el futuro.
- **Awesome Skills**: Se han instalado 201 habilidades seleccionadas de desarrollo, testing y arquitectura en `/skills/awesome`.

## Decisiones Técnicas Clave
- **Arquitectura**: Modularizada en `app.py` (Controlador), `database.py` (Capa de Datos) y `bpms_service.py` (Lógica de Negocio).
- **Base de Datos**: SQLite con Context Managers para estabilidad.
- **Seguridad**: Configuración vía `.env` (python-dotenv).
- **Rendimiento**: Caché en memoria para los datos del Excel.
- **Frontend**: Vanilla CSS + GSAP para animaciones premium. Chart.js para visualización.

## Próximos Pasos Sugeridos
- Implementar notificaciones por correo para radicados por vencer.
- Agregar soporte para exportación de PDF de auditoría.
- Integración con servicios de almacenamiento en la nube para adjuntos (S3/Azure).

## Historial de Versiones
- **v1.1**: Modernización, Charts, Audit Log, Adjuntos, Paginación.
- **v1.0**: Edición de radicados, Gestión de usuarios, Importación Excel.
