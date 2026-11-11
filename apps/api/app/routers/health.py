from fastapi import APIRouter

from app.core.security import UserDep

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/me")
async def me(user: UserDep) -> dict:
    return {"id": user.id, "email": user.email}
