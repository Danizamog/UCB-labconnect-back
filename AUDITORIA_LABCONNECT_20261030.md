# Auditoría de LabConnect — 30 de octubre de 2026

Los cambios se aplicaron en el servidor y se verificaron contra su PocketBase y el gateway. El frontend publicado también se probó en navegador.

## Roles y acceso

| Rol | Operación prevista |
| --- | --- |
| Estudiante | Crear, modificar y cancelar sus reservas personales; solicitar materiales; inscribirse en tutorías. |
| Invitado | Consultar disponibilidad y tutorías publicadas. Sin reservas, solicitudes ni inscripciones. |
| Docente | Gestionar sus clases y tutorías, asistencia y observaciones; solicitar recursos para sus actividades. |
| Encargado de Laboratorio | Operar reservas, materiales, equipos y préstamos dentro de sus laboratorios asignados. |
| Administrador | Gestionar infraestructura y operación según permisos. La creación personal de reservas sigue siendo de estudiantes. |
| Administrador de Accesos | Gestionar cuentas, roles y reactivación. Sin acceso administrativo innecesario a la operación de laboratorios. |
| OSI - Auditor de Seguridad | Consultar y gestionar las funciones de seguridad concedidas a su rol. |

Las comprobaciones de permisos del backend siguen siendo obligatorias aunque se intente abrir una URL o invocar una API directamente. El usuario conserva las funciones permitidas de su propia cuenta, como cambiar su contraseña.

## Correcciones

- Se restringió la reserva personal a Estudiante en el backend, navegación y pantalla inicial.
- Invitado ve tutorías sin botones de inscripción ni llamadas a funciones privadas de inscripción.
- Las respuestas públicas de tutorías incluyen el total de inscritos y cupos disponibles sin exponer los datos de otros estudiantes ni observaciones del tutor.
- Se asigna el laboratorio del material desde inventario al guardar la solicitud, para que aparezca en el ámbito del encargado correspondiente.
- Las consultas de accesos se dividen en grupos de 20 reservas; filtros grandes provocaban respuestas 400 de PocketBase y errores 500 del servicio.
- La reactivación usa el directorio operativo mínimo y una consulta específica de incidencias del usuario. Se habilitó ese flujo para el permiso `desbloquear_usuarios`.
- Crear una tutoría con `laboratory_id` obtiene la ubicación del laboratorio autorizado.
- La actualización de esquemas conserva campos adicionales, fechas de auditoría e identificadores de campos. Antes, un arranque podía eliminar etiquetas de demostración.

## Reglas de PocketBase

Se revisaron las 31 colecciones de aplicación. Las reglas de escritura directa están bloqueadas (`null`): el frontend escribe mediante el gateway y los servicios, que validan rol, propietario, ámbito y estado de cada operación. Los servicios usan la autenticación de superusuario configurada en el servidor.

Las lecturas directas personales se filtran por propietario. Sesiones, contraseñas, auditoría, penalizaciones, observaciones y otras colecciones privadas están restringidas al backend. Las tutorías se consultan por su API, que aplica la visibilidad y oculta información privada. Un candado en estas reglas es intencional; no significa que falten permisos de la aplicación.

Reaplicación reproducible desde el host de PocketBase:

```sh
python3 scripts/secure_pocketbase_rules.py \
  --env-file /ruta/privada/.env \
  --output /ruta/privada/api-rules.json \
  --apply
```

Sin `--apply` solo genera la propuesta. Al aplicar, crea primero un respaldo de PocketBase. No ejecutar un importador de esquemas antiguo encima de las reglas corregidas.

## Datos de demostración

Dataset: `labconnect-demo-20261030`. Los registros llevan `is_demo`, `demo_dataset` y nombres o notas `[DEMO]`; las cuentas usan el dominio no operativo `demo.labconnect.invalid`. No describen personas ni sucesos reales.

Se crearon 10 cuentas de prueba, 3 áreas y laboratorios, equipos, materiales, movimientos, reservas, accesos, solicitudes, clases, tutorías, inscripciones, asistencia, préstamos, mantenimiento y ejemplos de seguridad. Las reservas del dataset abarcan del 2 de julio al 11 de noviembre de 2026; las tutorías, del 8 de septiembre al 24 de noviembre. Los registros internos de sesiones e historial de contraseñas se generaron mediante los flujos reales correspondientes.

Al cierre del inventario se contaron 814 filas entre las 31 colecciones, incluyendo la vista derivada, con 465 marcadas como demostración. Se comprobaron los campos obligatorios sin encontrar vacíos. Son cifras de ese momento: la operación y auditoría posteriores generan más registros.

El seeder es idempotente, usa identificadores deterministas y se niega a sobrescribir registros ajenos al dataset:

```sh
python3 scripts/seed_demo_data.py \
  --env-file /ruta/privada/.env \
  --output /ruta/privada/demo-manifest-private.json \
  --apply
```

El manifiesto contiene credenciales de demostración y debe permanecer privado. No se incluye en Git. Se conservan los registros originales recuperados.

## Verificación

| Comprobación | Resultado |
| --- | --- |
| 72 operaciones GET de seis servicios, con siete roles: 504 solicitudes | Sin errores 500 ni operaciones sin un rol autorizado que pudiera consumirlas. |
| Operaciones y persistencia | 78 comprobaciones de infraestructura, reservas, materiales, clases, tutorías, préstamos, mantenimiento, roles y cuentas aprobadas. |
| Flujos adicionales | 17 comprobaciones de bloqueos, solicitudes de equipos, penalización y reactivación aprobadas. Se comprobó también la solicitud de material de una tutoría docente. |
| Tokens nativos de PocketBase | 83 comprobaciones de escrituras denegadas, lectura por propietario, colecciones privadas y cambio de contraseña con historial aprobadas. |
| Frontend publicado | 35 comprobaciones de rutas para siete roles, sin errores de JavaScript ni HTTP de API. URL de reserva denegada a Invitado. |
| Formulario publicado | Crear y editar área, recargar y verificar el valor mediante una lectura independiente de PocketBase: aprobado. |
| Reinicio de servicios | Etiquetas del dataset y reglas de las 31 colecciones conservadas. |
| Frontend | Build aprobado; lint sin errores y con tres avisos existentes de dependencias de hooks. |
| Pruebas locales | Auth: 106 aprobadas; roles: 30; materiales: 22; inventario: 24. Reservas: 105 aprobadas y 18 pruebas legadas fallidas. |

Las 18 pruebas legadas de reservas aún usan interfaces anteriores: llamadas sin esperar corrutinas, repositorios simulados sin los métodos actuales, almacenamiento de tutorías en archivos ya retirado y horarios anteriores a los bloques académicos. Afectan los archivos `test_acceptance_flows.py` y `test_laboratory_usage_analytics.py`; la suite completa de reservas no está verde. No se debilitaron las validaciones de producción para adaptarlas a esos fixtures. Los flujos equivalentes probados en el servidor pasaron, pero eso no sustituye actualizar esas pruebas.

Los reportes detallados y los respaldos anteriores a los cambios permanecen en el directorio privado de recuperación del servidor. Las pruebas no representan una garantía de todos los estados y combinaciones posibles ni sustituyen futuras pruebas de regresión.
