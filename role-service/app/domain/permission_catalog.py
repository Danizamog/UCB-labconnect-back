PERMISSIONS = {
    "consultar_usuarios": ("Consultar usuarios", "Consulta administrativa de cuentas."),
    "modificar_usuarios": ("Modificar usuarios", "Actualizar datos administrativos."),
    "dar_baja_usuarios": ("Dar de baja usuarios", "Desactivar cuentas sin borrar su trazabilidad."),
    "desbloquear_usuarios": ("Desbloquear usuarios", "Restablecer bloqueos por intentos fallidos."),
    "reiniciar_credenciales": ("Reiniciar credenciales", "Generar credenciales temporales de un solo uso."),
    "consultar_directorio_operativo": ("Consultar directorio operativo", "Consulta minima para operaciones."),
    "consultar_roles": ("Consultar roles", "Consultar la matriz RBAC."),
    "gestionar_roles": ("Gestionar roles", "Crear y modificar roles."),
    "asignar_roles": ("Asignar roles", "Asignar roles a usuarios."),
    "gestionar_reservas": ("Gestionar reservas", "Administrar solicitudes de reserva."),
    "gestionar_reservas_materiales": ("Gestionar materiales de reserva", "Administrar insumos solicitados."),
    "gestionar_reglas_reserva": ("Gestionar reglas de reserva", "Administrar reglas y restricciones."),
    "gestionar_estructura_laboratorios": ("Gestionar laboratorios", "Administrar areas y espacios."),
    "gestionar_horarios_laboratorio": ("Gestionar horarios", "Administrar horarios recurrentes."),
    "gestionar_accesos_laboratorio": ("Gestionar accesos", "Registrar entradas y salidas."),
    "gestionar_penalizaciones": ("Gestionar penalizaciones", "Administrar sanciones operativas."),
    "gestionar_inventario": ("Gestionar inventario", "Administrar activos."),
    "gestionar_stock": ("Gestionar stock", "Administrar existencias."),
    "gestionar_estado_equipos": ("Gestionar estado de equipos", "Actualizar estado operativo."),
    "gestionar_mantenimiento": ("Gestionar mantenimiento", "Administrar mantenimientos."),
    "registrar_tickets_equipo": ("Registrar tickets de equipo", "Crear y consultar tickets del laboratorio asignado, sin cerrarlos."),
    "gestionar_prestamos": ("Gestionar prestamos", "Administrar prestamos y devoluciones."),
    "gestionar_reactivos_quimicos": ("Gestionar reactivos", "Administrar reactivos quimicos."),
    "gestionar_tutorias_propias": ("Gestionar tutorias propias", "Crear y editar tutorias propias."),
    "aprobar_tutorias": ("Aprobar tutorias", "Aprobar sesiones propuestas."),
    "gestionar_asistencia_tutorias": ("Gestionar asistencia", "Registrar asistencia en tutorias propias."),
    "gestionar_observaciones_tutorias": ("Gestionar observaciones", "Registrar observaciones propias."),
    "solicitar_recursos_clase": ("Solicitar recursos", "Solicitar recursos para clases."),
    "gestionar_clases_propias": ("Gestionar clases propias", "Crear y modificar clases propias sujetas a aprobacion."),
    "aprobar_clases": ("Aprobar clases", "Aprobar o rechazar clases docentes desde Solicitudes y acceso."),
    "generar_reportes": ("Generar reportes", "Exportar reportes operativos."),
    "consultar_estadisticas": ("Consultar estadisticas", "Consultar analitica operativa."),
    "consultar_auditoria_seguridad": ("Consultar auditoria", "Leer eventos sanitizados."),
    "consultar_eventos_autenticacion": ("Consultar autenticaciones", "Leer accesos exitosos y fallidos."),
    "consultar_sesiones_usuarios": ("Consultar sesiones", "Leer sesiones sin secretos."),
    "consultar_incidentes_seguridad": ("Consultar incidentes", "Leer incidentes de seguridad."),
    "revisar_accesos_rbac": ("Revisar accesos RBAC", "Auditar roles y asignaciones."),
    "exportar_reportes_seguridad": ("Exportar seguridad", "Exportar evidencia sanitizada."),
}

PERMISSION_ICONS = {
    "consultar_usuarios": "👥", "gestionar_usuarios": "🧑‍💼", "gestionar_estado_cuentas": "🔐",
    "modificar_usuarios": "✏️", "dar_baja_usuarios": "⛔",
    "desbloquear_usuarios": "🔓", "reiniciar_credenciales": "🗝️",
    "consultar_directorio_operativo": "📇", "consultar_roles": "🪪", "gestionar_roles": "🛡️",
    "asignar_roles": "🔑",
    "gestionar_reservas": "📅", "gestionar_reservas_materiales": "📦", "gestionar_reglas_reserva": "📋",
    "gestionar_estructura_laboratorios": "🏢", "gestionar_horarios_laboratorio": "🕒",
    "gestionar_accesos_laboratorio": "🚪", "gestionar_penalizaciones": "⚠️",
    "gestionar_inventario": "🧰", "gestionar_stock": "📊", "gestionar_estado_equipos": "🖥️",
    "gestionar_mantenimiento": "🛠️", "gestionar_prestamos": "🤝", "gestionar_reactivos_quimicos": "🧪",
    "registrar_tickets_equipo": "🎫",
    "gestionar_tutorias_propias": "🎓", "aprobar_tutorias": "✅", "gestionar_asistencia_tutorias": "📝",
    "gestionar_observaciones_tutorias": "💬", "solicitar_recursos_clase": "📨",
    "generar_reportes": "📄", "consultar_estadisticas": "📈",
    "consultar_auditoria_seguridad": "🔎", "consultar_eventos_autenticacion": "🔓",
    "consultar_sesiones_usuarios": "💻", "consultar_incidentes_seguridad": "🚨",
    "revisar_accesos_rbac": "🧭", "exportar_reportes_seguridad": "📤",
}

PERMISSION_ICONS.update({"gestionar_clases_propias": "📚", "aprobar_clases": "✅"})

PERMISSION_CATALOG = [
    {"value": value, "label": label, "description": description, "icon": PERMISSION_ICONS.get(value, "•")}
    for value, (label, description) in PERMISSIONS.items()
]

ADMIN_OPERATIONAL_PERMISSIONS = [value for value in PERMISSIONS if value not in {
    "gestionar_usuarios", "gestionar_estado_cuentas", "modificar_usuarios",
    "dar_baja_usuarios", "desbloquear_usuarios", "reiniciar_credenciales", "gestionar_roles", "asignar_roles",
    "iniciar_restablecimiento_credencial", "consultar_auditoria_seguridad",
    "consultar_eventos_autenticacion", "consultar_sesiones_usuarios",
    "consultar_incidentes_seguridad", "revisar_accesos_rbac", "exportar_reportes_seguridad",
    "gestionar_clases_propias", "solicitar_recursos_clase", "gestionar_tutorias_propias",
    "gestionar_asistencia_tutorias", "gestionar_observaciones_tutorias",
}]
# Consultas compartidas: ambos administradores pueden identificar usuarios y
# comprender la matriz, pero solo Accesos puede mutar identidades o RBAC.
for _shared_permission in ("consultar_usuarios", "consultar_roles", "consultar_directorio_operativo"):
    if _shared_permission not in ADMIN_OPERATIONAL_PERMISSIONS:
        ADMIN_OPERATIONAL_PERMISSIONS.append(_shared_permission)

ACCESS_ADMIN_PERMISSIONS = [
    "consultar_usuarios", "consultar_directorio_operativo", "consultar_roles",
    "modificar_usuarios", "dar_baja_usuarios", "desbloquear_usuarios", "reiniciar_credenciales",
    "gestionar_roles", "asignar_roles",
]

DEFAULT_ROLE_TEMPLATES = [
    {"nombre": "Administrador", "descripcion": "Operacion general: areas, laboratorios, reservas, inventario, reportes y pronosticos.", "permisos": ADMIN_OPERATIONAL_PERMISSIONS},
    {"nombre": "Administrador de Accesos", "descripcion": "Gestion de cuentas, roles y credenciales; sin permisos de operacion ni auditoria OSI.", "permisos": ACCESS_ADMIN_PERMISSIONS},
    {"nombre": "Encargado de Laboratorio", "descripcion": "Opera reservas, equipos y materiales de su laboratorio sin crear productos ni cerrar tickets.", "permisos": [
        "consultar_directorio_operativo", "gestionar_reservas", "gestionar_accesos_laboratorio", "gestionar_prestamos",
        "gestionar_reservas_materiales", "registrar_tickets_equipo",
    ]},
    {"nombre": "Docente", "descripcion": "Tutorias propias y solicitudes de recursos docentes.", "permisos": [
        "gestionar_tutorias_propias", "gestionar_asistencia_tutorias", "gestionar_observaciones_tutorias",
        "solicitar_recursos_clase",
        "gestionar_clases_propias",
    ]},
    {"nombre": "Estudiante", "descripcion": "Autoservicio academico sujeto a propiedad.", "permisos": []},
    {"nombre": "Invitado", "descripcion": "Solo consulta de cuenta; sin reservas ni tutorias.", "permisos": []},
    {"nombre": "OSI - Auditor de Seguridad", "descripcion": "Auditoria de seguridad y consulta administrativa de solo lectura.", "permisos": [
        "consultar_usuarios", "consultar_directorio_operativo", "consultar_roles", "consultar_estadisticas",
        "consultar_auditoria_seguridad", "consultar_eventos_autenticacion", "consultar_sesiones_usuarios",
        "consultar_incidentes_seguridad", "revisar_accesos_rbac", "exportar_reportes_seguridad",
    ]},
]

ASSIGNABLE_ROLE_NAMES = [template["nombre"] for template in DEFAULT_ROLE_TEMPLATES]
SYSTEM_ROLE_NAMES = set(ASSIGNABLE_ROLE_NAMES)


def normalize_permissions(permisos: list[str]) -> list[str]:
    selected = {permission.strip() for permission in permisos if permission.strip()}
    invalid = sorted(selected.difference(PERMISSIONS))
    if invalid:
        raise ValueError(f"Permisos invalidos: {', '.join(invalid)}")
    return [value for value in PERMISSIONS if value in selected]


def is_assignable_role_name(nombre: str | None) -> bool:
    return isinstance(nombre, str) and nombre.strip() in ASSIGNABLE_ROLE_NAMES
