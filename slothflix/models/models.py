"""SQLAlchemy ORM models for SlothFlix."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, Integer, String, Text, LargeBinary, Index
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class CatalogEntry(Base):
    __tablename__ = "catalog"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(500), nullable=False)
    info_hash = Column(String(40), index=True)
    seeders = Column(Integer, default=0)
    leechers = Column(Integer, default=0)
    size = Column(String(50))
    magnet_uri = Column(Text)
    uploader = Column(String(200))
    category = Column(String(50), nullable=False, index=True)
    updated_at = Column(String(30), default=lambda: datetime.now(timezone.utc).isoformat())

    __table_args__ = (Index("ix_catalog_title_category", "title", "category"),)


class Poster(Base):
    __tablename__ = "posters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(500), nullable=False, unique=True, index=True)
    image_blob = Column(LargeBinary, nullable=False)
    content_hash = Column(String(64))  # SHA-256 for ETag/304
    updated_at = Column(String(30), default=lambda: datetime.now(timezone.utc).isoformat())


class Blurb(Base):
    __tablename__ = "blurbs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(500), nullable=False, unique=True, index=True)
    text = Column(Text)
    updated_at = Column(String(30), default=lambda: datetime.now(timezone.utc).isoformat())


class Trailer(Base):
    __tablename__ = "trailers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(String(20), nullable=False)
    position = Column(Integer, default=0)
    updated_at = Column(String(30), default=lambda: datetime.now(timezone.utc).isoformat())


class Token(Base):
    __tablename__ = "tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(50), nullable=False, index=True)
    username = Column(String(200))
    token = Column(String(64), nullable=False, unique=True, index=True)
    created_at = Column(String(30), default=lambda: datetime.now(timezone.utc).isoformat())
    expires_at = Column(String(30), nullable=False)
    revoked = Column(Boolean, default=False)
