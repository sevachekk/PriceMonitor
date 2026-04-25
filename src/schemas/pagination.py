from pydantic import BaseModel
from pydantic import Field


class PaginationSchema(BaseModel):
    limit: int = Field(default=5, ge=0, le=100)
    offset: int = Field(default=0, ge=0)