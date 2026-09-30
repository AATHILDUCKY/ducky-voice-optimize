from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(slots=True)
class Project:
    id: int
    name: str
    source_path: str | None
    output_path: str | None
    vocal_path: str | None
    background_path: str | None
    enhanced_vocal_path: str | None
    created_at: str
    updated_at: str
    settings: str


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._create_schema()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _create_schema(self) -> None:
        with self.connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    source_path TEXT,
                    output_path TEXT,
                    vocal_path TEXT,
                    background_path TEXT,
                    enhanced_vocal_path TEXT,
                    settings TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = {row[1] for row in db.execute("PRAGMA table_info(projects)")}
            for name in ("vocal_path", "background_path", "enhanced_vocal_path"):
                if name not in columns:
                    db.execute(f"ALTER TABLE projects ADD COLUMN {name} TEXT")

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def list_projects(self) -> list[Project]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
        return [Project(**dict(row)) for row in rows]

    def create_project(self, name: str) -> Project:
        now = self._now()
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO projects(name, created_at, updated_at) VALUES (?, ?, ?)",
                (name.strip() or "Untitled project", now, now),
            )
            project_id = int(cursor.lastrowid)
            row = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return Project(**dict(row))

    def update_project(self, project_id: int, **fields: str | None) -> None:
        allowed = {
            "name",
            "source_path",
            "output_path",
            "vocal_path",
            "background_path",
            "enhanced_vocal_path",
            "settings",
        }
        values = {key: value for key, value in fields.items() if key in allowed}
        if not values:
            return
        values["updated_at"] = self._now()
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self.connect() as db:
            db.execute(
                f"UPDATE projects SET {assignments} WHERE id = ?",
                (*values.values(), project_id),
            )

    def delete_project(self, project_id: int) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
