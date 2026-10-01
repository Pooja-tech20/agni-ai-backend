from app.schemas.base import BaseSchema


class HealthResponse(BaseSchema):
    status: str
    app_name: str
    environment: str


class DBTestResponse(BaseSchema):
    status: str
    detail: str
