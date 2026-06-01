from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional


class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str


class WorkoutCreate(BaseModel):
    title: str
    description: Optional[str] = None


class WorkoutResponse(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
