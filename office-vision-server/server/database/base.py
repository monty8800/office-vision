"""SQLAlchemy 声明基类。"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """全部 ORM 模型的基类。"""
