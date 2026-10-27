SEPE CONTROL — AKACENTER Y JUAN PABLO
Versión 2.0 — 26 de octubre de 2026

Aplicación instalable para cinco gestores y una cartera compartida.
Consultar primero docs/Informe_SEPE_y_manual.docx.
Integración y actualización: docs/INTEGRACION_APIS.txt.
Fechas y socios: docs/AGRUPACION_Y_FECHAS.txt.
Los requisitos, fuentes, incidencias y fórmulas se muestran dentro de la aplicación.
No incluye claves, cuentas predeterminadas ni datos individuales reales de alumnos.
No está publicada. API interna REST con Basic y Gestión GraphQL con token
implementadas; conexiones reales desactivadas hasta configurar el servidor.
Los esquemas recibidos se incluyen en integrations/schemas/. El OpenAPI no declara
empresa, sector o situación laboral: confirmar el contrato antes de activar.

INSTALACIÓN ONLINE RECOMENDADA

Requisitos: servidor Linux con Docker Engine y Docker Compose, dominio propio
con DNS apuntando al servidor, puertos 80 y 443 abiertos y espacio para copias.
Instalación de Docker: https://docs.docker.com/engine/install/
No exponer el puerto interno 8000. Usar un solo servidor para SQLite.

1. Descomprimir y entrar en el directorio sepe_control.
2. Copiar .env.example a .env y editar SEPE_DOMAIN y ACME_EMAIL.
   El dominio se escribe sin https:// ni ruta. No usar los valores de ejemplo.
3. Ejecutar:

   docker compose build
   docker compose run --rm app python app.py user admin --role admin --manager g1

   Introducir una contraseña personal de al menos 12 caracteres, dos veces.
   No se muestra en pantalla ni se guarda en texto plano.
4. Crear cinco cuentas individuales. Se puede usar admin además de estas cinco:

   docker compose run --rm app python app.py user gestor1 --manager g1
   docker compose run --rm app python app.py user gestor2 --manager g2
   docker compose run --rm app python app.py user gestor3 --manager g3
   docker compose run --rm app python app.py user gestor4 --manager g4
   docker compose run --rm app python app.py user gestor5 --manager g5

5. Arrancar:

   docker compose up -d
   docker compose logs --tail=50

6. Abrir https://TU_DOMINIO, entrar y revisar el catálogo y las incidencias.
   Caddy solicita y renueva el certificado TLS. El DNS debe resolver correctamente.
   Configuración permite cambiar nombres y capacidad semanal de los gestores.
   Los filtros muestran ambas empresas juntas o por separado.
7. Antes de uso real, verificar acceso con dos cuentas, cambios concurrentes,
   exportación, importación de prueba y restauración de una copia en otro directorio.
   Se revisaron conexiones y simulación en navegador con respuestas ficticias.
   Las APIs reales, Docker y HTTPS deben validarse en el servidor de destino.

PRUEBA LOCAL EN LINUX O macOS

   python3 -m venv .venv
   . .venv/bin/activate
   pip install -r requirements.txt
   python app.py user admin --role admin --manager g1
   SEPE_INSECURE_LOCAL=1 python app.py

Abrir http://127.0.0.1:8000. Este servidor es solo para revisión local.
SEPE_INSECURE_LOCAL desactiva la cookie Secure y no debe usarse online.
No es necesario instalar Node para la aplicación. package.json/preview.py solo
facilitan una revisión de desarrollo donde exista Python.

CUENTAS Y PERMISOS

admin: parámetros, fechas verificadas, importación, conexiones API y auditoría,
además de gestión. Crear, restablecer y desactivar cuentas requiere la consola
del servidor; cada usuario puede cambiar su propia contraseña en la web.
gestor: alumnos, tareas y propuestas, con acceso a ambas entidades.
lector: consulta; no puede modificar datos ni simular mediante POST.
Contraseñas con hash scrypt, sesiones firmadas de ocho horas, cookies HttpOnly,
SameSite Strict y Secure online, control CSRF y registro de cambios.
Las actualizaciones usan revisión optimista: si otro gestor cambia datos,
se rechaza el segundo guardado con 409. Actualizar y repetir evita sobrescribir.

Restablecer una cuenta: repetir app.py user USUARIO y establecer nueva contraseña.
Desactivar: docker compose exec app python app.py disable USUARIO
Una desactivación o cambio de contraseña invalida las sesiones anteriores.
Los nombres de los gestores no cambian los nombres de acceso de las cuentas.
SEPE_BEHIND_PROXY=1 solo con un proxy de confianza y sin exposición de app:8000.

COPIAS Y RECUPERACIÓN

   docker compose exec app python app.py backup

El comando muestra /data/backup_FECHA_HORA.sqlite3. Copiar la ruta exacta mostrada:

   docker compose cp app:/data/backup_FECHA_HORA.sqlite3 ./copia.sqlite3
   docker compose cp app:/data/secret.key ./secret.key

Custodiar ambos archivos cifrados y con acceso restringido, fuera del servidor.
El JSON exportado desde la web contiene datos operativos, no cuentas ni auditoría.
Para recuperar la copia completa, en la misma versión del programa:

   docker compose stop app
   docker compose run --rm --user root -v "$PWD:/restore:ro" app python restore.py /restore/copia.sqlite3
   docker compose up -d app

restore.py conserva una copia previa, valida el esquema y sustituye la base de
forma atómica. Las sesiones se invalidan. El secreto de sesión se puede regenerar
en un servidor nuevo; conservarlo solo cuando lo exija la política interna.
No ejecutar docker compose down -v: eliminaría los volúmenes de datos.
Comprobar una restauración periódicamente y antes de actualizar versiones.

MANTENIMIENTO

El catálogo inicial se carga una sola vez, al crear la base. Cambiar seed.json no
actualiza una instalación existente. Los cambios futuros de programación exigen
migración documentada que conserve identidades, matrículas y fuentes históricas.
Esta versión incorpora resultados agregados de socios por formulario o CSV,
fecha original y confirmada por expediente, historial y alertas. Los plazos
provisionales solo generan borradores; los confirmados permiten crear tareas.
Registra fechas límite y calendarios propuestos, pero no modifica
los Excel originales ni resuelve automáticamente las discrepancias de catálogo.
Al cambiar de convocatoria se deben versionar reglas y compromisos, no sustituir
el expediente actual. No marcar cobertura completa sin datos de todos los socios.

Conservar el servidor en una ubicación aprobada por la organización, restringir
acceso a copias, definir plazo de conservación y evitar DNI o documentos médicos
en campos libres. Guardar referencias internas a evidencias, no su contenido.

VALIDACIÓN

   pip install -r requirements-dev.txt
   python -m pytest tests -q

60 pruebas automatizadas pasan. Cubren cálculos de denominadores, CCAA, penalizaciones, ausencia de datos,
duplicados, autenticación, CSRF, roles, cambios concurrentes, importación atómica,
idempotencia de planificación, invalidación de sesiones, contratos REST/GraphQL,
autenticación API, paginación, cruces de identidad y vistas previas.
Datos de prueba ficticios; no se han realizado llamadas reales.
No equivalen a una auditoría de seguridad externa o a validación de SEPE.
