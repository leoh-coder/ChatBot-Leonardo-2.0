from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from db import SessionLocal
from models import Todo

STATUS_VALUES = {"aberta", "em_andamento", "concluida"}
_MISSING = object()
_BLOCKED_MSG = "Tarefa concluída não pode ser alterada ou excluída."


class TodoError(Exception):
    def __init__(self, detail: str, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _ensure_status(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    value = value.strip().lower()
    if value not in STATUS_VALUES:
        raise TodoError("status inválido.", status_code=422)
    return value


def _serialize(todo: Todo) -> Dict[str, object]:
    return {
        "id": todo.id,
        "title": todo.title,
        "description": todo.description or "",
        "due_date": todo.due_date.isoformat() if todo.due_date else None,
        "status": todo.status,
        "created_at": todo.created_at.isoformat() if todo.created_at else None,
        "updated_at": todo.updated_at.isoformat() if todo.updated_at else None,
    }


def _use_session(db: Optional[Session]) -> Tuple[Session, bool]:
    if isinstance(db, Session):
        return db, False
    session = SessionLocal()
    return session, True


def create_todo(
    db: Optional[Session] = None,
    title: str = "",
    description: Optional[str] = "",
    due_date: Optional[datetime] = None,
    status: str = "aberta",
) -> Dict[str, object]:
    base_session = db if isinstance(db, Session) else None
    if base_session is None and not title and isinstance(db, str):
        title = db
    session, should_close = _use_session(base_session)
    try:
        clean_title = (title or "").strip()
        if not clean_title:
            raise TodoError("título obrigatório.", status_code=422)
        status_value = _ensure_status(status) or "aberta"
        todo = Todo(
            title=clean_title,
            description=(description or "").strip(),
            due_date=due_date,
            status=status_value,
        )
        session.add(todo)
        session.commit()
        session.refresh(todo)
        return _serialize(todo)
    finally:
        if should_close:
            session.close()


def list_todos(
    db: Optional[Session] = None,
    status: Optional[str] = None,
    target_date: Optional[date] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> List[Dict[str, object]]:
    session, should_close = _use_session(db)
    try:
        query = session.query(Todo)
        status_value = _ensure_status(status)
        if status_value:
            query = query.filter(Todo.status == status_value)
        if target_date:
            query = query.filter(func.date(Todo.due_date) == target_date)
        if start_date:
            query = query.filter(Todo.due_date >= start_date)
        if end_date:
            query = query.filter(Todo.due_date <= end_date)
        todos = query.order_by(Todo.due_date.asc(), Todo.created_at.asc()).all()
        return [_serialize(todo) for todo in todos]

    finally:
        if should_close:
            session.close()


def _ensure_editable(todo: Todo) -> None:
    if todo.status == "concluida":
        raise TodoError(_BLOCKED_MSG, status_code=409)


def update_todo(
    db: Optional[Session] = None,
    todo_id: Optional[int] = None,
    *,
    title: Optional[str] = None,
    description: Optional[str] = None,
    due_date: object = _MISSING,
    status: Optional[str] = None,
) -> Dict[str, object]:
    session, should_close = _use_session(db)
    try:
        if todo_id is None:
            raise TodoError("tarefa não encontrada.", status_code=404)
        todo = session.get(Todo, todo_id)
        if not todo:
            raise TodoError("tarefa não encontrada.", status_code=404)
        _ensure_editable(todo)

        if title is not None:
            novo_titulo = title.strip()
            if not novo_titulo:
                raise TodoError("título obrigatório.", status_code=422)
            todo.title = novo_titulo
        if description is not None:
            todo.description = (description or "").strip()
        if due_date is not _MISSING:
            todo.due_date = due_date
        if status is not None:
            todo.status = _ensure_status(status) or todo.status

        session.add(todo)
        session.commit()
        session.refresh(todo)
        return _serialize(todo)
    finally:
        if should_close:
            session.close()


def delete_todo(db: Optional[Session] = None, todo_id: Optional[int] = None) -> Dict[str, object]:
    session, should_close = _use_session(db)
    try:
        if todo_id is None:
            raise TodoError("tarefa não encontrada.", status_code=404)
        todo = session.get(Todo, todo_id)
        if not todo:
            raise TodoError("tarefa não encontrada.", status_code=404)
        _ensure_editable(todo)
        session.delete(todo)
        session.commit()
        return {"message": "tarefa removida"}
    finally:
        if should_close:
            session.close()


def stats_por_status(db: Optional[Session] = None) -> Dict[str, int]:
    session, should_close = _use_session(db)
    try:
        data = {status: 0 for status in STATUS_VALUES}
        for status, total in session.query(Todo.status, func.count()).group_by(Todo.status):
            data[status] = int(total or 0)
        return data
    finally:
        if should_close:
            session.close()
