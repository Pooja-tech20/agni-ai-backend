# import re
# import uuid

# from pydantic import EmailStr, Field, field_validator

# from app.models.referral import ReferralSource
# from app.models.roles import UserRole
# from app.schemas.base import BaseSchema


# class UserBase(BaseSchema):
#     """Fields + validation shared by public sign-up and admin-created users."""
#     first_name: str = Field(min_length=1, max_length=100)
#     last_name: str = Field(min_length=1, max_length=100)
#     email: EmailStr
#     phone_country_code: str = Field(examples=["+91"])
#     phone_number: str = Field(examples=["9876543210"])
#     password: str = Field(min_length=8, max_length=72)

#     @field_validator("first_name", "last_name")
#     @classmethod
#     def strip_and_require_text(cls, value: str) -> str:
#         value = value.strip()
#         if not value:
#             raise ValueError("must not be blank")
#         return value

#     @field_validator("email")
#     @classmethod
#     def lowercase_email(cls, value: str) -> str:
#         return value.lower()

#     @field_validator("phone_country_code")
#     @classmethod
#     def validate_country_code(cls, value: str) -> str:
#         value = value.strip().replace(" ", "")
#         if not value.startswith("+"):
#             value = f"+{value}"
#         if not re.fullmatch(r"\+\d{1,4}", value):
#             raise ValueError("must look like +91")
#         return value

#     @field_validator("phone_number")
#     @classmethod
#     def validate_phone_number(cls, value: str) -> str:
#         # Allow spaces / dashes from the UI, store digits only
#         digits = re.sub(r"[\s\-()]", "", value)
#         if not re.fullmatch(r"\d{6,15}", digits):
#             raise ValueError("must contain 6 to 15 digits")
#         return digits


# class RegisterRequest(UserBase):
#     organization_name: str = Field(min_length=1, max_length=255)
#     referral_source: ReferralSource | None = None

#     @field_validator("organization_name")
#     @classmethod
#     def strip_org(cls, value: str) -> str:
#         value = value.strip()
#         if not value:
#             raise ValueError("must not be blank")
#         return value


# class LoginRequest(BaseSchema):
#     email: EmailStr
#     password: str = Field(min_length=1, max_length=72)

#     @field_validator("email")
#     @classmethod
#     def lowercase_email(cls, value: str) -> str:
#         return value.lower()


# class UserResponse(BaseSchema):
#     id: uuid.UUID
#     email: EmailStr
#     first_name: str
#     last_name: str
#     full_name: str
#     organization_name: str
#     client_id: uuid.UUID | None
#     phone_country_code: str
#     phone_number: str
#     referral_source: ReferralSource | None
#     role: UserRole
#     is_active: bool


# class TokenResponse(BaseSchema):
#     access_token: str
#     token_type: str = "bearer"
#     user: UserResponse

import re
import uuid

from pydantic import EmailStr, Field, field_validator

from app.models.referral import ReferralSource
from app.models.roles import UserRole
from app.schemas.base import BaseSchema


class UserBase(BaseSchema):
    """Fields + validation shared by public sign-up and admin-created users."""
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    phone_country_code: str = Field(examples=["+91"])
    phone_number: str = Field(examples=["9876543210"])
    password: str = Field(min_length=8, max_length=72)

    @field_validator("first_name", "last_name")
    @classmethod
    def strip_and_require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("email")
    @classmethod
    def lowercase_email(cls, value: str) -> str:
        return value.lower()

    @field_validator("phone_country_code")
    @classmethod
    def validate_country_code(cls, value: str) -> str:
        value = value.strip().replace(" ", "")
        if not value.startswith("+"):
            value = f"+{value}"
        if not re.fullmatch(r"\+\d{1,4}", value):
            raise ValueError("must look like +91")
        return value

    @field_validator("phone_number")
    @classmethod
    def validate_phone_number(cls, value: str) -> str:
        # Allow spaces / dashes from the UI, store digits only
        digits = re.sub(r"[\s\-()]", "", value)
        if not re.fullmatch(r"\d{6,15}", digits):
            raise ValueError("must contain 6 to 15 digits")
        return digits


class RegisterRequest(UserBase):
    organization_name: str = Field(min_length=1, max_length=255)
    referral_source: ReferralSource | None = None

    @field_validator("organization_name")
    @classmethod
    def strip_org(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class LoginRequest(BaseSchema):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)

    @field_validator("email")
    @classmethod
    def lowercase_email(cls, value: str) -> str:
        return value.lower()


class UserResponse(BaseSchema):
    id: uuid.UUID
    email: EmailStr
    first_name: str
    last_name: str
    full_name: str
    organization_name: str
    client_id: uuid.UUID | None
    phone_country_code: str
    phone_number: str
    referral_source: ReferralSource | None
    role: UserRole
    is_active: bool


class TokenResponse(BaseSchema):
    access_token: str
    token_type: str = "bearer"
    refresh_token: str | None = None
    expires_in: int | None = None  # access token lifetime in seconds
    user: UserResponse


class RefreshRequest(BaseSchema):
    refresh_token: str