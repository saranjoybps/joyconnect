"""Request-scoped access to shared services stored on app.state."""

from typing import Annotated

import httpx
from fastapi import Depends, Request

from app.core.secrets import SecretStore
from app.db.client import Database


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_store(request: Request) -> SecretStore:
    return request.app.state.secret_store


def get_http(request: Request) -> httpx.AsyncClient:
    return request.app.state.http


DbDep = Annotated[Database, Depends(get_db)]
StoreDep = Annotated[SecretStore, Depends(get_store)]
HttpDep = Annotated[httpx.AsyncClient, Depends(get_http)]
