from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.api.v1.router import api_router
from app.core.config import settings
from app.db.base import Base
from app.db.session import engine
from app.models.area import Area
from app.models.laboratory import Laboratory
from app.models.practice_request import PracticeRequest
from app.models.practice_material import PracticeMaterial


def ensure_reservations_schema():
    inspector = inspect(engine)

    with engine.begin() as connection:
        existing_tables = set(inspector.get_table_names())

        if "areas" not in existing_tables:
            connection.execute(
                text(
                    """
                    CREATE TABLE areas (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR(120) NOT NULL UNIQUE,
                        description TEXT,
                        is_active BOOLEAN NOT NULL DEFAULT TRUE,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    )
                    """
                )
            )

        default_area_id = connection.execute(
            text(
                """
                INSERT INTO areas (name, description, is_active)
                VALUES ('General', 'Area generada automaticamente para compatibilidad', TRUE)
                ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
                """
            )
        ).scalar_one()

        laboratory_columns = {column["name"] for column in inspector.get_columns("laboratories")} \
            if "laboratories" in existing_tables else set()

        if "laboratories" in existing_tables and "area_id" not in laboratory_columns:
            connection.execute(text("ALTER TABLE laboratories ADD COLUMN area_id INTEGER"))
            connection.execute(
                text("UPDATE laboratories SET area_id = :default_area_id WHERE area_id IS NULL"),
                {"default_area_id": default_area_id},
            )
            connection.execute(
                text(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1
                            FROM pg_constraint
                            WHERE conname = 'laboratories_area_id_fkey'
                        ) THEN
                            ALTER TABLE laboratories
                            ADD CONSTRAINT laboratories_area_id_fkey
                            FOREIGN KEY (area_id) REFERENCES areas (id);
                        END IF;
                    END
                    $$;
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_laboratories_area_id
                    ON laboratories (area_id)
                    """
                )
            )
            connection.execute(text("ALTER TABLE laboratories ALTER COLUMN area_id SET NOT NULL"))

        if "practice_requests" in existing_tables:
            practice_request_columns = {
                column["name"] for column in inspector.get_columns("practice_requests")
            }

            if "review_comment" not in practice_request_columns:
                connection.execute(text("ALTER TABLE practice_requests ADD COLUMN review_comment TEXT"))

            if "status_updated_at" not in practice_request_columns:
                connection.execute(text("ALTER TABLE practice_requests ADD COLUMN status_updated_at TIMESTAMP"))
                connection.execute(
                    text(
                        """
                        UPDATE practice_requests
                        SET status_updated_at = COALESCE(created_at, NOW())
                        WHERE status_updated_at IS NULL
                        """
                    )
                )
                connection.execute(
                    text("ALTER TABLE practice_requests ALTER COLUMN status_updated_at SET NOT NULL")
                )

            if "user_notification_read" not in practice_request_columns:
                connection.execute(
                    text(
                        """
                        ALTER TABLE practice_requests
                        ADD COLUMN user_notification_read BOOLEAN NOT NULL DEFAULT TRUE
                        """
                    )
                )


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/")
def root():
    return {"message": "LabConnect Reservations Service running"}
