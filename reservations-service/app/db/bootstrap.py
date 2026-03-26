from sqlalchemy import func, inspect, select, text

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.area import Area
from app.models.class_session import ClassSession  # noqa: F401
from app.models.class_tutorial import ClassTutorial  # noqa: F401
from app.models.laboratory import Laboratory
from app.models.practice_material import PracticeMaterial  # noqa: F401
from app.models.practice_request import PracticeRequest


def ensure_reservations_schema() -> None:
    inspector = inspect(engine)
    if "practice_requests" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("practice_requests")}
    if "subject_name" not in existing_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE practice_requests ADD COLUMN subject_name VARCHAR(160)"))
            connection.execute(
                text(
                    """
                    UPDATE practice_requests
                    SET subject_name = CASE
                        WHEN support_topic IS NOT NULL AND TRIM(support_topic) <> '' THEN support_topic
                        WHEN notes IS NOT NULL AND TRIM(notes) <> '' THEN SUBSTR(notes, 1, 160)
                        ELSE 'Practica de laboratorio'
                    END
                    WHERE subject_name IS NULL OR TRIM(subject_name) = ''
                    """
                )
            )


def initialize_reservations_database() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_reservations_schema()

    with SessionLocal() as db:
        area_count = db.scalar(select(func.count(Area.id))) or 0
        if area_count == 0:
            db.add_all(
                [
                    Area(name="Tecnologia", description="Laboratorios tecnologicos", is_active=True),
                    Area(name="Ciencias", description="Laboratorios cientificos", is_active=True),
                ]
            )
            db.commit()

        lab_count = db.scalar(select(func.count(Laboratory.id))) or 0
        if lab_count == 0:
            areas = {area.name: area for area in db.query(Area).all()}
            db.add_all(
                [
                    Laboratory(
                        name="Laboratorio de Redes",
                        location="Bloque A - Piso 2",
                        capacity=24,
                        description="Espacio orientado a practicas de redes y comunicaciones.",
                        is_active=True,
                        area_id=areas["Tecnologia"].id,
                    ),
                    Laboratory(
                        name="Laboratorio de Sistemas",
                        location="Bloque B - Piso 1",
                        capacity=30,
                        description="Laboratorio para desarrollo, sistemas operativos y software.",
                        is_active=True,
                        area_id=areas["Tecnologia"].id,
                    ),
                    Laboratory(
                        name="Laboratorio de Biologia",
                        location="Bloque C - Piso 1",
                        capacity=18,
                        description="Espacio para practicas de biologia y ciencias de la vida.",
                        is_active=True,
                        area_id=areas["Ciencias"].id,
                    ),
                ]
            )
            db.commit()
