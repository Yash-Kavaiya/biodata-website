"""
Biodata models - Pydantic schemas for data validation.
Follows Single Responsibility Principle.
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum
import uuid


class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"


class MaritalStatus(str, Enum):
    SINGLE = "single"
    MARRIED = "married"
    DIVORCED = "divorced"
    WIDOWED = "widowed"


class OCRStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    APPROVED = "approved"
    REJECTED = "rejected"


class BiodataBase(BaseModel):
    """Base biodata fields extracted from OCR."""
    name: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[Gender] = None
    date_of_birth: Optional[str] = None
    height: Optional[str] = None
    weight: Optional[str] = None
    complexion: Optional[str] = None
    blood_group: Optional[str] = None

    # Education & Career
    education: Optional[str] = None
    occupation: Optional[str] = None
    income: Optional[str] = None
    company: Optional[str] = None

    # Family Details
    father_name: Optional[str] = None
    father_occupation: Optional[str] = None
    mother_name: Optional[str] = None
    mother_occupation: Optional[str] = None
    siblings: Optional[str] = None

    # Location
    native_place: Optional[str] = None
    current_city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None

    # Religion & Caste
    religion: Optional[str] = None
    caste: Optional[str] = None
    subcaste: Optional[str] = None
    gotra: Optional[str] = None

    # Horoscope
    rashi: Optional[str] = None
    nakshatra: Optional[str] = None
    manglik: Optional[str] = None

    # Contact
    contact_number: Optional[str] = None
    email: Optional[str] = None

    # Preferences
    marital_status: Optional[MaritalStatus] = None
    partner_preferences: Optional[str] = None

    # Additional
    hobbies: Optional[str] = None
    about: Optional[str] = None


class BiodataCreate(BiodataBase):
    """Schema for creating biodata manually."""
    pass


class BiodataUpdate(BiodataBase):
    """Schema for updating biodata."""
    pass


class BiodataInDB(BiodataBase):
    """Biodata as stored in database."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    file_path: Optional[str] = None
    original_filename: Optional[str] = None
    ocr_status: OCRStatus = OCRStatus.PENDING
    ocr_confidence: Optional[float] = None
    raw_ocr_text: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    is_approved: bool = False

    class Config:
        from_attributes = True


class BiodataResponse(BiodataInDB):
    """Response schema for biodata."""
    pass


class BiodataListResponse(BaseModel):
    """Response for listing biodatas."""
    total: int
    items: List[BiodataResponse]
    page: int = 1
    page_size: int = 10


class UploadResponse(BaseModel):
    """Response for file upload."""
    id: str
    filename: str
    status: OCRStatus
    message: str


class BulkUploadResponse(BaseModel):
    """Response for bulk file upload."""
    total: int
    successful: int
    failed: int
    uploads: List[UploadResponse]


class OCRValidationRequest(BaseModel):
    """Request for validating/updating OCR results."""
    biodata_id: str
    action: str  # "approve", "reject", "edit", "re-ocr"
    updated_data: Optional[BiodataUpdate] = None


class SearchPreferences(BaseModel):
    """Preferences for match finding."""
    min_age: Optional[int] = None
    max_age: Optional[int] = None
    gender: Optional[Gender] = None
    religion: Optional[str] = None
    caste: Optional[str] = None
    education: Optional[str] = None
    occupation: Optional[str] = None
    location: Optional[str] = None
    marital_status: Optional[MaritalStatus] = None


class MatchResult(BaseModel):
    """Result of similarity matching."""
    biodata: BiodataResponse
    similarity_score: float
    match_reasons: List[str]
