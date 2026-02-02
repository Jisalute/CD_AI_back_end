from pydantic import BaseModel, EmailStr, constr
from typing import Optional, Literal


class BaseUserCreate(BaseModel):
    username: str
    password: Optional[str] = None
    phone: Optional[constr(strip_whitespace=True, min_length=1, max_length=32)] = None
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None


class StudentCreate(BaseUserCreate):
    pass


class TeacherCreate(BaseUserCreate):
    pass


class AdminCreate(BaseUserCreate):
    role: Optional[str] = "admin"


class UserUpdate(BaseModel):
    user_type: Optional[Literal["student", "teacher", "admin"]] = None
    phone: Optional[constr(strip_whitespace=True, min_length=1, max_length=32)] = None
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    role: Optional[str] = None
    password: Optional[str] = None


class UserOut(BaseModel):
    id: int
    username: str
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    role: Optional[str] = None
    created_at: str
    updated_at: str


class UserBindPhone(BaseModel):
    phone: constr(strip_whitespace=True, min_length=1, max_length=32)


class UserBindEmail(BaseModel):
    email: EmailStr
