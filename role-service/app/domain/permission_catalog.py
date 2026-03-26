PERMISSION_CATALOG = [
    {
        "value": "gestionar_roles_permisos",
        "label": "Gestionar roles y permisos",
        "description": "Permite crear roles, editar sus permisos y asignarlos a los usuarios del sistema.",
        "icon": "🛡️",
    },
    {
        "value": "reactivar_cuentas",
        "label": "Reactivar cuentas",
        "description": "Permite activar o desactivar cuentas para controlar quien puede ingresar al sistema.",
        "icon": "🔄",
    },
    {
        "value": "gestionar_reservas",
        "label": "Gestionar reservas",
        "description": "Permite revisar, aprobar, rechazar o cancelar solicitudes de reserva de laboratorio.",
        "icon": "📅",
    },
    {
        "value": "gestionar_reservas_materiales",
        "label": "Gestionar materiales en reservas",
        "description": "Permite revisar y controlar los materiales o insumos solicitados dentro de una reserva.",
        "icon": "🧪",
    },
    {
        "value": "gestionar_reglas_reserva",
        "label": "Gestionar reglas de reserva",
        "description": "Permite definir reglas de uso, condiciones, prioridades y restricciones para reservar.",
        "icon": "⚙️",
    },
    {
        "value": "gestionar_inventario",
        "label": "Gestionar inventario",
        "description": "Permite crear, editar y eliminar equipos o recursos del inventario institucional.",
        "icon": "📦",
    },
    {
        "value": "gestionar_stock",
        "label": "Gestionar stock",
        "description": "Permite actualizar cantidades, stock minimo y disponibilidad de materiales o insumos.",
        "icon": "📊",
    },
    {
        "value": "gestionar_estado_equipos",
        "label": "Gestionar estado de equipos",
        "description": "Permite cambiar el estado operativo de un equipo: disponible, en mantenimiento o dañado.",
        "icon": "🧰",
    },
    {
        "value": "gestionar_mantenimiento",
        "label": "Gestionar mantenimiento",
        "description": "Permite registrar mantenimientos y controlar equipos que estan temporalmente fuera de servicio.",
        "icon": "🛠️",
    },
    {
        "value": "gestionar_prestamos",
        "label": "Gestionar prestamos",
        "description": "Permite llevar el control de prestamos y devoluciones de materiales o equipos.",
        "icon": "🤝",
    },
    {
        "value": "adjuntar_evidencia_inventario",
        "label": "Adjuntar evidencia de inventario",
        "description": "Permite registrar fotos, documentos o respaldos asociados al inventario.",
        "icon": "📎",
    },
    {
        "value": "gestionar_accesos_laboratorio",
        "label": "Gestionar accesos al laboratorio",
        "description": "Permite habilitar o restringir laboratorios, areas y espacios visibles para reserva.",
        "icon": "🚪",
    },
    {
        "value": "gestionar_penalizaciones",
        "label": "Gestionar penalizaciones",
        "description": "Permite registrar sanciones o restricciones por incumplimientos de uso.",
        "icon": "⚠️",
    },
    {
        "value": "gestionar_tutorias",
        "label": "Gestionar tutorias",
        "description": "Permite crear, editar y organizar clases, tutorias o sesiones con invitados.",
        "icon": "🎓",
    },
    {
        "value": "gestionar_inscripciones_tutorias",
        "label": "Gestionar inscripciones de tutorias",
        "description": "Permite inscribir y administrar participantes en tutorias o sesiones academicas.",
        "icon": "📝",
    },
    {
        "value": "gestionar_asistencia_tutorias",
        "label": "Gestionar asistencia a tutorias",
        "description": "Permite registrar asistencia y seguimiento de participacion en tutorias.",
        "icon": "✅",
    },
    {
        "value": "gestionar_observaciones_tutorias",
        "label": "Gestionar observaciones de tutorias",
        "description": "Permite guardar comentarios, observaciones o notas de seguimiento academico.",
        "icon": "📋",
    },
    {
        "value": "gestionar_notificaciones",
        "label": "Gestionar notificaciones",
        "description": "Permite enviar mensajes o avisos relacionados con reservas, tutorias y cambios importantes.",
        "icon": "🔔",
    },
    {
        "value": "generar_reportes",
        "label": "Generar reportes",
        "description": "Permite generar reportes administrativos sobre uso de laboratorios, inventario y reservas.",
        "icon": "📈",
    },
    {
        "value": "consultar_estadisticas",
        "label": "Consultar estadisticas",
        "description": "Permite ver indicadores, metricas y paneles de analisis del sistema.",
        "icon": "📉",
    },
    {
        "value": "gestionar_reactivos_quimicos",
        "label": "Gestionar reactivos quimicos",
        "description": "Permite controlar reactivos, su cantidad disponible y su uso dentro del laboratorio.",
        "icon": "⚗️",
    },
]

DEFAULT_ROLE_TEMPLATES = [
    {
        "nombre": "Administrador",
        "descripcion": "Acceso total para configurar usuarios, roles, reservas, inventario y gestion academica.",
        "permisos": [item["value"] for item in PERMISSION_CATALOG],
    },
    {
        "nombre": "Encargado de Laboratorio",
        "descripcion": "Gestion operativa del laboratorio: reservas, accesos, inventario, materiales y seguimiento diario.",
        "permisos": [
            "gestionar_reservas",
            "gestionar_reservas_materiales",
            "gestionar_inventario",
            "gestionar_stock",
            "gestionar_estado_equipos",
            "gestionar_mantenimiento",
            "gestionar_prestamos",
            "adjuntar_evidencia_inventario",
            "gestionar_accesos_laboratorio",
            "gestionar_penalizaciones",
            "gestionar_tutorias",
            "gestionar_asistencia_tutorias",
            "gestionar_notificaciones",
            "generar_reportes",
            "consultar_estadisticas",
            "gestionar_reactivos_quimicos",
        ],
    },
    {
        "nombre": "Docente",
        "descripcion": "Coordinacion academica de practicas, clases, tutorias, invitados y seguimiento de participantes.",
        "permisos": [
            "gestionar_tutorias",
            "gestionar_inscripciones_tutorias",
            "gestionar_asistencia_tutorias",
            "gestionar_observaciones_tutorias",
            "gestionar_notificaciones",
        ],
    },
    {
        "nombre": "Estudiante",
        "descripcion": "Acceso base para consultar disponibilidad, reservar y seguir el estado de sus solicitudes.",
        "permisos": [],
    },
    {
        "nombre": "Invitado",
        "descripcion": "Acceso limitado para invitados o participantes externos con visibilidad restringida.",
        "permisos": [],
    },
]

ASSIGNABLE_ROLE_NAMES = [template["nombre"] for template in DEFAULT_ROLE_TEMPLATES]


def normalize_permissions(permisos: list[str]) -> list[str]:
    allowed = {item["value"] for item in PERMISSION_CATALOG}
    selected = {permission.strip() for permission in permisos if permission.strip()}
    invalid = sorted(permission for permission in selected if permission not in allowed)
    if invalid:
        raise ValueError(f"Permisos invalidos: {', '.join(invalid)}")

    ordered = [item["value"] for item in PERMISSION_CATALOG if item["value"] in selected]
    return ordered


def is_assignable_role_name(nombre: str | None) -> bool:
    if not isinstance(nombre, str):
        return False
    return nombre.strip() in ASSIGNABLE_ROLE_NAMES
