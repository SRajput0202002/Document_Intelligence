"""
Segmentation Profiles API.

CRUD operations for managing document segmentation profiles.
Profiles define patterns for detecting document boundaries in multi-document PDFs.
"""

import logging
import re
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..database.models import SegmentationProfile, User
from ..auth import get_current_user, get_current_user_required

logger = logging.getLogger(__name__)

# Note: redirect_slashes=False prevents 307 redirects when behind a reverse proxy
# that terminates SSL (like Azure Container Apps), which would redirect to HTTP
router = APIRouter(redirect_slashes=False)


# =============================================================================
# Pydantic Models
# =============================================================================

class VetoField(BaseModel):
    """Veto field - if matched on consecutive pages, they're the same document."""
    name: str = Field(..., description="Field name, e.g., 'be_number'")
    pattern: str = Field(..., description="Regex pattern to extract the field value")
    bidirectional: bool = Field(default=False, description="Try matching in both directions")
    enabled: bool = Field(default=True, description="Whether this field is active")


class SectionPattern(BaseModel):
    """Section pattern for PART-based splitting within documents."""
    pattern: str = Field(..., description="Regex pattern to match section headers")
    capture_group: int = Field(default=1, description="Which group captures the section name")


class StartKeyword(BaseModel):
    """Keyword indicating document start."""
    pattern: str = Field(..., description="Regex pattern for the keyword")
    confidence: float = Field(default=0.75, ge=0.0, le=1.0, description="Base confidence score")


class SupportingField(BaseModel):
    """Supporting field - helps identify same document but not definitive."""
    name: str
    pattern: str


class SegmentationProfileCreate(BaseModel):
    """Request model for creating/updating a segmentation profile."""
    name: str = Field(..., min_length=1, max_length=100, description="Unique profile identifier")
    display_name: str = Field(..., min_length=1, max_length=255, description="Human-readable name")
    description: Optional[str] = Field(None, description="Profile description")
    veto_fields: List[VetoField] = Field(default_factory=list)
    section_patterns: List[SectionPattern] = Field(default_factory=list)
    start_keywords: List[StartKeyword] = Field(default_factory=list)
    supporting_fields: List[SupportingField] = Field(default_factory=list)
    continuity_patterns: List[str] = Field(default_factory=list)
    enable_section_splitting: bool = Field(default=False)
    default_detection_method: Optional[str] = Field(
        None,
        description="Default detection method to use in production (e.g., 'Heuristics Only', 'Full ML-Enhanced (TF-IDF)')"
    )
    ocr_method: Optional[str] = Field(
        None,
        description="Default OCR method for this profile (e.g., 'auto', 'pymupdf', 'mistral')"
    )


class SegmentationProfileResponse(BaseModel):
    """Response model for a segmentation profile."""
    id: str
    name: str
    display_name: str
    description: Optional[str]
    veto_fields: List[dict]
    section_patterns: List[dict]
    start_keywords: List[dict]
    supporting_fields: List[dict]
    continuity_patterns: List[str]
    enable_section_splitting: bool
    default_detection_method: Optional[str]
    ocr_method: Optional[str]
    is_builtin: bool
    created_by: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]

    class Config:
        from_attributes = True


class PatternTestRequest(BaseModel):
    """Request model for testing a regex pattern."""
    pattern: str = Field(..., description="Regex pattern to test")
    sample_text: str = Field(..., description="Sample text to test against")
    flags: Optional[str] = Field(default="im", description="Regex flags (i=ignorecase, m=multiline)")


class PatternTestResponse(BaseModel):
    """Response model for pattern test results."""
    valid: bool
    error: Optional[str] = None
    matches: List[str] = []
    groups: List[List[str]] = []
    match_count: int = 0


class BulkPatternTestRequest(BaseModel):
    """Request model for testing multiple patterns against sample text."""
    patterns: List[VetoField]
    sample_text: str


class BulkPatternTestResponse(BaseModel):
    """Response model for bulk pattern test results."""
    results: List[dict]


# =============================================================================
# API Endpoints
# =============================================================================

@router.get("", response_model=List[SegmentationProfileResponse])
async def list_profiles(
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    """
    List all segmentation profiles.

    Returns builtin profiles first, then custom profiles sorted by display name.
    """
    profiles = db.query(SegmentationProfile).order_by(
        SegmentationProfile.is_builtin.desc(),
        SegmentationProfile.display_name
    ).all()

    return [p.to_dict() for p in profiles]


@router.get("/{profile_id}", response_model=SegmentationProfileResponse)
async def get_profile(
    profile_id: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    """Get a segmentation profile by ID."""
    profile = db.query(SegmentationProfile).filter(
        SegmentationProfile.id == profile_id
    ).first()

    if not profile:
        # Also try by name
        profile = db.query(SegmentationProfile).filter(
            SegmentationProfile.name == profile_id
        ).first()

    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    return profile.to_dict()


@router.post("", response_model=SegmentationProfileResponse)
async def create_profile(
    profile_data: SegmentationProfileCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    Create a new segmentation profile.

    The profile name must be unique.
    """
    # Check name uniqueness
    existing = db.query(SegmentationProfile).filter(
        SegmentationProfile.name == profile_data.name
    ).first()

    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Profile with name '{profile_data.name}' already exists"
        )

    # Validate all regex patterns
    validation_errors = _validate_profile_patterns(profile_data)
    if validation_errors:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid regex patterns: {'; '.join(validation_errors)}"
        )

    # Create profile
    db_profile = SegmentationProfile(
        name=profile_data.name,
        display_name=profile_data.display_name,
        description=profile_data.description,
        veto_fields=[f.dict() for f in profile_data.veto_fields],
        section_patterns=[p.dict() for p in profile_data.section_patterns],
        start_keywords=[k.dict() for k in profile_data.start_keywords],
        supporting_fields=[f.dict() for f in profile_data.supporting_fields],
        continuity_patterns=profile_data.continuity_patterns,
        enable_section_splitting=profile_data.enable_section_splitting,
        default_detection_method=profile_data.default_detection_method,
        ocr_method=profile_data.ocr_method,
        is_builtin=False,
        created_by=current_user.id,
    )

    db.add(db_profile)
    db.commit()
    db.refresh(db_profile)

    logger.info(f"Created segmentation profile: {profile_data.name} by {current_user.username}")

    return db_profile.to_dict()


@router.put("/{profile_id}", response_model=SegmentationProfileResponse)
async def update_profile(
    profile_id: str,
    profile_data: SegmentationProfileCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    Update a segmentation profile.

    Builtin profiles can be modified but retain their builtin status.
    """
    profile = db.query(SegmentationProfile).filter(
        SegmentationProfile.id == profile_id
    ).first()

    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    # Check name uniqueness if name is changing
    if profile_data.name != profile.name:
        existing = db.query(SegmentationProfile).filter(
            SegmentationProfile.name == profile_data.name,
            SegmentationProfile.id != profile_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Profile with name '{profile_data.name}' already exists"
            )

    # Validate all regex patterns
    validation_errors = _validate_profile_patterns(profile_data)
    if validation_errors:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid regex patterns: {'; '.join(validation_errors)}"
        )

    # Update fields
    profile.name = profile_data.name
    profile.display_name = profile_data.display_name
    profile.description = profile_data.description
    profile.veto_fields = [f.dict() for f in profile_data.veto_fields]
    profile.section_patterns = [p.dict() for p in profile_data.section_patterns]
    profile.start_keywords = [k.dict() for k in profile_data.start_keywords]
    profile.supporting_fields = [f.dict() for f in profile_data.supporting_fields]
    profile.continuity_patterns = profile_data.continuity_patterns
    profile.enable_section_splitting = profile_data.enable_section_splitting
    profile.default_detection_method = profile_data.default_detection_method
    profile.ocr_method = profile_data.ocr_method
    profile.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(profile)

    logger.info(f"Updated segmentation profile: {profile.name} by {current_user.username}")

    return profile.to_dict()


@router.delete("/{profile_id}")
async def delete_profile(
    profile_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    Delete a segmentation profile.

    Builtin profiles cannot be deleted.
    """
    profile = db.query(SegmentationProfile).filter(
        SegmentationProfile.id == profile_id
    ).first()

    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    if profile.is_builtin:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete builtin profiles. You can modify them instead."
        )

    db.delete(profile)
    db.commit()

    logger.info(f"Deleted segmentation profile: {profile.name} by {current_user.username}")

    return {"status": "deleted", "name": profile.name}


@router.post("/test-pattern", response_model=PatternTestResponse)
async def test_pattern(
    request: PatternTestRequest,
    current_user: Optional[User] = Depends(get_current_user),
):
    """
    Test a regex pattern against sample text.

    Returns matches and captured groups.
    """
    try:
        # Build regex flags
        flags = 0
        if 'i' in request.flags.lower():
            flags |= re.IGNORECASE
        if 'm' in request.flags.lower():
            flags |= re.MULTILINE

        regex = re.compile(request.pattern, flags)

        # Find all matches
        matches = regex.findall(request.sample_text)

        # Get detailed match info with groups
        groups = []
        for match in regex.finditer(request.sample_text):
            match_groups = list(match.groups())
            if match_groups:
                groups.append(match_groups)
            else:
                groups.append([match.group(0)])

        # Convert matches to strings (handles tuple returns from findall)
        match_strings = []
        for m in matches:
            if isinstance(m, tuple):
                match_strings.append(m[0] if m else "")
            else:
                match_strings.append(str(m))

        return PatternTestResponse(
            valid=True,
            matches=match_strings,
            groups=groups,
            match_count=len(matches)
        )

    except re.error as e:
        return PatternTestResponse(
            valid=False,
            error=f"Invalid regex: {str(e)}"
        )


@router.post("/test-patterns-bulk", response_model=BulkPatternTestResponse)
async def test_patterns_bulk(
    request: BulkPatternTestRequest,
    current_user: Optional[User] = Depends(get_current_user),
):
    """
    Test multiple patterns against sample text.

    Returns match results for each pattern.
    """
    results = []

    for field in request.patterns:
        try:
            regex = re.compile(field.pattern, re.IGNORECASE | re.MULTILINE)
            matches = regex.findall(request.sample_text)

            # Get first match value
            value = None
            if matches:
                m = matches[0]
                value = m[0] if isinstance(m, tuple) and m else str(m)

            results.append({
                "field_name": field.name,
                "pattern": field.pattern,
                "matched": bool(matches),
                "value": value,
                "match_count": len(matches),
                "error": None
            })

        except re.error as e:
            results.append({
                "field_name": field.name,
                "pattern": field.pattern,
                "matched": False,
                "value": None,
                "match_count": 0,
                "error": str(e)
            })

    return BulkPatternTestResponse(results=results)


@router.post("/reseed")
async def reseed_profiles(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    Re-seed builtin profiles from code definitions.

    Only adds new profiles; existing profiles are not overwritten.
    Requires admin role.
    """
    from ..database.engine import seed_segmentation_profiles

    # Check admin role
    if current_user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only admins can reseed builtin profiles"
        )

    seed_segmentation_profiles()

    return {"status": "success", "message": "Builtin profiles reseeded"}


# =============================================================================
# Helper Functions
# =============================================================================

def _validate_profile_patterns(profile_data: SegmentationProfileCreate) -> List[str]:
    """Validate all regex patterns in a profile."""
    errors = []

    # Validate veto field patterns
    for field in profile_data.veto_fields:
        try:
            re.compile(field.pattern)
        except re.error as e:
            errors.append(f"veto_field '{field.name}': {e}")

    # Validate section patterns
    for i, pattern in enumerate(profile_data.section_patterns):
        try:
            re.compile(pattern.pattern)
        except re.error as e:
            errors.append(f"section_pattern[{i}]: {e}")

    # Validate start keywords
    for i, keyword in enumerate(profile_data.start_keywords):
        try:
            re.compile(keyword.pattern)
        except re.error as e:
            errors.append(f"start_keyword[{i}]: {e}")

    # Validate supporting fields
    for field in profile_data.supporting_fields:
        try:
            re.compile(field.pattern)
        except re.error as e:
            errors.append(f"supporting_field '{field.name}': {e}")

    # Validate continuity patterns
    for i, pattern in enumerate(profile_data.continuity_patterns):
        try:
            re.compile(pattern)
        except re.error as e:
            errors.append(f"continuity_pattern[{i}]: {e}")

    return errors
