"""
Document Type Profiles for Segmentation.

Defines document-type-specific patterns for boundary detection.
Each profile specifies:
- Key fields that uniquely identify documents of that type (veto-level)
- Supporting fields that help but aren't definitive
- Document start keywords specific to that type
- Expected page patterns

Usage:
    from .document_profiles import get_profile, get_merged_profile

    # Single type
    profile = get_profile("invoice")

    # Multiple types (merges all patterns)
    profile = get_merged_profile(["invoice", "packing_list"])
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class DocumentProfile:
    """
    Profile defining how to detect boundaries for a document type.

    Attributes:
        name: Profile identifier
        display_name: Human-readable name
        description: What documents this profile covers

        veto_fields: Key fields that UNIQUELY identify a document.
                     If these match between pages, they are DEFINITELY same document.
                     Format: field_name -> (regex_pattern, is_bidirectional)

        supporting_fields: Fields that help identify same document but aren't definitive.
                          Multiple matches increase confidence.

        start_keywords: Keywords that indicate start of this document type.
                       Format: (pattern, confidence)

        boundary_boosters: Patterns that strongly indicate a NEW document starts.
                          These INCREASE boundary confidence.

        continuity_patterns: Patterns that indicate page continuity (same document).
                            These DECREASE boundary confidence.

        section_patterns: Patterns for SECTION-BASED segmentation within a document.
                         When enabled, creates boundaries at section headers even if
                         they're part of the same logical document.
                         Format: (pattern, section_name_group_index)
                         Example: (r"PART\\s*[-:]?\\s*([IVX\\d]+)", 1) extracts "I", "II", etc.

        enable_section_splitting: If True, section_patterns create boundaries.
                                 If False, sections are ignored and only document
                                 boundaries are detected.
    """
    name: str
    display_name: str
    description: str

    # Veto-level fields (matching = definitely same document)
    veto_fields: Dict[str, Tuple[str, bool]] = field(default_factory=dict)
    # Format: field_name -> (pattern, is_bidirectional)
    # is_bidirectional=True means try both "label value" and "value label" matching

    # Supporting fields (matching = probably same document)
    supporting_fields: Dict[str, str] = field(default_factory=dict)

    # Keywords indicating document start
    start_keywords: List[Tuple[str, float]] = field(default_factory=list)
    # Format: (regex_pattern, base_confidence)

    # Patterns that boost boundary confidence
    boundary_boosters: List[Tuple[str, float]] = field(default_factory=list)

    # Patterns that indicate continuity (reduce boundary confidence)
    continuity_patterns: List[str] = field(default_factory=list)

    # Section-based segmentation patterns
    section_patterns: List[Tuple[str, int]] = field(default_factory=list)
    # Format: (regex_pattern, group_index_for_section_name)
    # Example: (r"PART\s*[-:]?\s*([IVX\d]+)", 1) captures "I", "II", "1", "2" etc.

    # Whether to split by sections (default False for backward compatibility)
    enable_section_splitting: bool = False


# =============================================================================
# Built-in Document Profiles
# =============================================================================

PROFILES: Dict[str, DocumentProfile] = {}


def _register(profile: DocumentProfile) -> DocumentProfile:
    """Register a profile in the global registry."""
    PROFILES[profile.name] = profile
    return profile


# -----------------------------------------------------------------------------
# Generic / Default Profile
# -----------------------------------------------------------------------------
_register(DocumentProfile(
    name="generic",
    display_name="Generic Document",
    description="Default profile for unknown document types. Uses basic heuristics.",

    veto_fields={},  # No veto fields for generic - be conservative

    supporting_fields={
        "reference_number": r"(?:Ref|Reference)\s*(?:No\.?|Number|#)?\.?\s*[:=]?\s*([A-Z0-9][-A-Z0-9/]{5,})",
    },

    start_keywords=[
        # Very generic - only trigger on explicit document type headers
        (r"^\s*(?:PAGE|COVER)\s+(?:1|ONE)\b", 0.70),
    ],

    boundary_boosters=[],
    continuity_patterns=[],
))


# -----------------------------------------------------------------------------
# Commercial Invoice Profile
# -----------------------------------------------------------------------------
_register(DocumentProfile(
    name="invoice",
    display_name="Commercial Invoice",
    description="Commercial invoices, export invoices, proforma invoices",

    veto_fields={
        "invoice_number": (r"(?:Invoice|Inv)\.?\s*(?:No|Number|#)?\.?\s*[:=]?\s*([A-Z0-9][-A-Z0-9/]+[A-Z0-9])", False),
        "irn": (r"IRN\s*[:=]?\s*([a-f0-9]{64})", False),
        "ack_number": (r"Ack\.?\s*(?:No|Number)?\.?\s*[:=]?\s*(\d{10,})", False),
    },

    supporting_fields={
        "po_number": r"(?:P\.?O\.?|Purchase\s*Order)\s*(?:No|#)?\.?\s*[:=]?\s*([A-Z0-9][-A-Z0-9/]+[A-Z0-9])",
        "gstin": r"GSTIN\s*[:=]?\s*(\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z\d][A-Z])",
        "date": r"(?:Invoice|Inv)\s*Date\s*[:=]?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
    },

    start_keywords=[
        (r"\bINVOICE\b", 0.75),
        (r"\bTAX\s+INVOICE\b", 0.85),
        (r"\bPROFORMA\s+INVOICE\b", 0.85),
        (r"\bCOMMERCIAL\s+INVOICE\b", 0.85),
        (r"\bEXPORT\s+INVOICE\b", 0.85),
    ],

    boundary_boosters=[
        (r"ORIGINAL\s+FOR\s+(?:RECIPIENT|BUYER)", 0.60),
    ],

    continuity_patterns=[
        r"(?:Page|Pg\.?)\s*\d+\s*(?:of|/)\s*\d+",  # Page X of Y
        r"Continued\s+(?:on|from)\s+(?:next|previous)",
    ],
))


# -----------------------------------------------------------------------------
# Telecom Bill Profile
# -----------------------------------------------------------------------------
_register(DocumentProfile(
    name="telecom_bill",
    display_name="Telecom Bill",
    description="Telephone bills, mobile bills, ISP invoices (Batelco, Airtel, Jio, etc.)",

    veto_fields={
        # These uniquely identify a telecom bill
        "bill_profile": (r"Bill\s*Profile\s*[:=]?\s*(\d{10})", True),  # Bidirectional
        "account_number": (r"Account\s*(?:No\.?|Number|#)?\.?\s*[:=]?\s*(\d{10})", True),
        "bill_number": (r"Bill\s*(?:No\.?|Number|#)?\.?\s*[:=]?\s*(\d{10,})", True),
        "customer_id": (r"Customer\s*(?:ID|No\.?|Number)?\.?\s*[:=]?\s*([A-Z0-9]{6,})", False),
        "customer_tax_reg": (r"(?:Customer\s*)?Tax\s*Registration\s*(?:No\.?|Number)?\.?\s*[:=]?\s*(\d{8,})", False),
        "subscriber_number": (r"Subscriber\s*(?:No\.?|Number|ID)?\.?\s*[:=]?\s*([A-Z0-9]{6,})", False),
        "service_number": (r"Service\s*(?:No\.?|Number|ID)?\.?\s*[:=]?\s*([A-Z0-9]{6,})", False),
    },

    supporting_fields={
        "billing_period": r"(?:Billing|Bill)\s*Period\s*[:=]?\s*(.+?)(?:\n|$)",
        "due_date": r"(?:Due|Payment)\s*Date\s*[:=]?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
    },

    start_keywords=[
        (r"\bBILL\s+SUMMARY\b", 0.80),
        (r"\bTAX\s+INVOICE\b", 0.75),
        (r"\bMONTHLY\s+(?:BILL|STATEMENT)\b", 0.80),
        (r"\bTELECOM(?:MUNICATIONS?)?\s+BILL\b", 0.85),
    ],

    boundary_boosters=[],

    continuity_patterns=[
        r"Bill\s*Profile\s*Charges",  # Continuation of charges section
        r"(?:Previous|Current)\s*Balance",
    ],
))


# -----------------------------------------------------------------------------
# Shipping Documents Profile (generic - B/L, AWB, etc.)
# -----------------------------------------------------------------------------
_register(DocumentProfile(
    name="shipping",
    display_name="Shipping Documents",
    description="Bill of Lading, Airway Bill, Delivery Note (NOT Indian Shipping Bill)",

    veto_fields={
        "bl_number": (r"(?:B/?L|Bill\s*of\s*Lading)\s*(?:No\.?|Number|#)?\.?\s*[:=]?\s*([A-Z0-9]{6,})", False),
        "awb_number": (r"(?:AWB|Air\s*(?:Way)?bill)\s*(?:No\.?|Number|#)?\.?\s*[:=]?\s*(\d{3}[-\s]?\d{8})", False),
        "container_number": (r"Container\s*(?:No\.?|Number|#)?\.?\s*[:=]?\s*([A-Z]{4}\d{7})", False),
    },

    supporting_fields={
        "vessel_name": r"(?:Vessel|Ship)\s*(?:Name)?\.?\s*[:=]?\s*([A-Z][A-Z\s]+)",
        "voyage_number": r"Voyage\s*(?:No\.?|Number|#)?\.?\s*[:=]?\s*([A-Z0-9]+)",
        "port_of_loading": r"(?:Port\s*of\s*)?Loading\s*[:=]?\s*([A-Z][A-Z\s,]+)",
        "port_of_discharge": r"(?:Port\s*of\s*)?Discharge\s*[:=]?\s*([A-Z][A-Z\s,]+)",
    },

    start_keywords=[
        (r"\bBILL\s+OF\s+LADING\b", 0.90),
        (r"\bAIR(?:WAY)?\s*BILL\b", 0.90),
        (r"\bDELIVERY\s+(?:NOTE|ORDER)\b", 0.85),
        (r"\bSEA\s+WAYBILL\b", 0.90),
        (r"\bFREIGHT\s+(?:INVOICE|NOTE)\b", 0.80),
    ],

    boundary_boosters=[
        (r"ORIGINAL\s*$", 0.50),
        (r"(?:SHIPPER|CONSIGNEE)(?:'S)?\s+COPY", 0.60),
    ],

    continuity_patterns=[
        r"(?:Cont(?:inued)?|C['']?td)\.?\s*(?:on|from)",
    ],
))


# -----------------------------------------------------------------------------
# Indian Shipping Bill Profile (with PART section splitting)
# -----------------------------------------------------------------------------
_register(DocumentProfile(
    name="shipping_bill",
    display_name="Indian Shipping Bill",
    description="Indian Customs Shipping Bill with PART sections (I, II, III, etc.)",

    veto_fields={
        # These identify the SAME shipping bill (but we want to split by parts)
        "sb_number": (r"(?:SB\s*No|Shipping\s*Bill\s*(?:No\.?|Number)?)\s*[:=]?\s*(\d{7,})", False),
    },

    supporting_fields={
        "sb_date": r"(?:SB\s*Date|Shipping\s*Bill\s*Date)\s*[:=]?\s*(\d{1,2}[-/]\w{3}[-/]\d{2,4})",
        "iec_code": r"IEC\s*(?:Code|No\.?)?\.?\s*[:=]?\s*(\d{10})",
        "port_code": r"Port\s*Code\s*[:=]?\s*([A-Z]{5,})",
    },

    start_keywords=[
        (r"\bSHIPPING\s+BILL\b", 0.90),
        (r"\bINDIAN\s+CUSTOMS\s+EDI\b", 0.95),
        (r"\bCENTRAL\s+BOARD\s+OF\s+INDIRECT\s+TAXES\b", 0.90),
    ],

    boundary_boosters=[],

    continuity_patterns=[],

    # SECTION PATTERNS - These detect PART boundaries within the shipping bill
    # Each PART (I, II, III, IV, V, VI) becomes a separate segment
    # User must enable with split_by_sections=True to use these
    section_patterns=[
        # "PART - I - SHIPPING BILL SUMMARY", "PART - II - INVOICE", etc.
        (r"PART\s*[-:.]?\s*([IVX]+|\d+)\s*[-:.]?\s*", 1),
        # Also handle "PART I", "PART 1" without separator
        (r"PART\s+([IVX]+|\d+)\b", 1),
    ],

    # Section splitting is OFF by default - user must enable with split_by_sections=True
    enable_section_splitting=False,
))


# -----------------------------------------------------------------------------
# Packing List Profile
# -----------------------------------------------------------------------------
_register(DocumentProfile(
    name="packing_list",
    display_name="Packing List",
    description="Packing lists, weight lists, cargo lists",

    veto_fields={
        "packing_list_number": (r"(?:Packing\s*List|P/?L)\s*(?:No\.?|Number|#)?\.?\s*[:=]?\s*([A-Z0-9][-A-Z0-9/]+)", False),
        "invoice_ref": (r"(?:Invoice|Inv)\s*(?:Ref|No\.?|Number|#)?\.?\s*[:=]?\s*([A-Z0-9][-A-Z0-9/]+)", False),
    },

    supporting_fields={
        "total_packages": r"(?:Total\s*)?(?:Packages?|Cartons?|Cases?)\s*[:=]?\s*(\d+)",
        "gross_weight": r"(?:Gross|Total)\s*Weight\s*[:=]?\s*([\d,.]+)\s*(?:KG|LBS?)",
        "net_weight": r"Net\s*Weight\s*[:=]?\s*([\d,.]+)\s*(?:KG|LBS?)",
    },

    start_keywords=[
        (r"\bPACKING\s+LIST\b", 0.90),
        (r"\bWEIGHT\s+LIST\b", 0.85),
        (r"\bCARGO\s+LIST\b", 0.85),
        (r"\bDETAILED\s+PACKING\b", 0.85),
    ],

    boundary_boosters=[],

    continuity_patterns=[
        r"(?:Page|Sheet)\s*\d+\s*(?:of|/)\s*\d+",
        r"(?:Cont(?:inued)?|C['']?td)",
    ],
))


# -----------------------------------------------------------------------------
# Certificate Profile
# -----------------------------------------------------------------------------
_register(DocumentProfile(
    name="certificate",
    display_name="Certificate",
    description="Certificate of Origin, Quality Certificate, Insurance Certificate, etc.",

    veto_fields={
        "certificate_number": (r"Certificate\s*(?:No\.?|Number|#)?\.?\s*[:=]?\s*([A-Z0-9][-A-Z0-9/]+)", False),
        "serial_number": (r"(?:Serial|Sr\.?)\s*(?:No\.?|Number|#)?\.?\s*[:=]?\s*([A-Z0-9]+)", False),
    },

    supporting_fields={
        "issue_date": r"(?:Date\s*of\s*)?Issue\s*[:=]?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
        "expiry_date": r"(?:Valid\s*(?:Until|Till)|Expir(?:y|es?))\s*[:=]?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
        "issuing_authority": r"(?:Issued\s*By|Authority|Chamber)\s*[:=]?\s*(.+?)(?:\n|$)",
    },

    start_keywords=[
        (r"\bCERTIFICATE\s+OF\s+ORIGIN\b", 0.90),
        (r"\bCERTIFICATE\s+OF\s+(?:QUALITY|INSPECTION)\b", 0.90),
        (r"\bINSURANCE\s+CERTIFICATE\b", 0.90),
        (r"\bHEALTH\s+CERTIFICATE\b", 0.90),
        (r"\bPHYTOSANITARY\s+CERTIFICATE\b", 0.90),
        (r"\bFUMIGATION\s+CERTIFICATE\b", 0.90),
        (r"\bCERTIFICATE\b", 0.70),  # Generic certificate
    ],

    boundary_boosters=[
        (r"THIS\s+IS\s+TO\s+CERTIFY", 0.70),
        (r"WE\s+HEREBY\s+CERTIFY", 0.70),
    ],

    continuity_patterns=[],
))


# -----------------------------------------------------------------------------
# Bill of Entry Profile (Customs)
# -----------------------------------------------------------------------------
_register(DocumentProfile(
    name="bill_of_entry",
    display_name="Bill of Entry",
    description="Customs Bill of Entry, Import Declaration",

    veto_fields={
        # BE Number - very flexible patterns for table-extracted text
        # Handles: "BE No|3487893", "BE No 3487893", "3487893|BE No", etc.
        "be_number": (r"(?:B/?E|BE)\s*(?:No\.?|Number|#)?[.\s|:=]*(\d{7,})", True),
        # IEC Code - 10 digit identifier, also flexible
        "iec_code": (r"IEC[/Br.\s|:=]*(\d{10})", True),
        # GSTIN - standard 15 char format
        "gstin": (r"GSTIN[/TYPE.\s|:=]*(\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z\d][A-Z])", True),
        # CB Code (Customs Broker)
        "cb_code": (r"CB\s*CODE[.\s|:=]*([A-Z0-9]{10,})", True),
    },

    supporting_fields={
        "port_code": r"Port\s*(?:Code)?[.\s|:=]*([A-Z]{5,})",
        "cha_name": r"CHA\s*(?:Name)?[.\s|:=]*(.+?)(?:\n|$)",
        "igst_amount": r"IGST[.\s|:=]*([\d,.]+)",
        "be_date": r"(?:B/?E|BE)\s*Date[.\s|:=]*(\d{1,2}[-/]\w{3,}[-/]\d{2,4})",
    },

    start_keywords=[
        # Lower confidence - these appear on EVERY page of a multi-page BOE
        # We rely on veto fields to suppress false boundaries
        (r"\bBILL\s+OF\s+ENTRY\b", 0.50),
        (r"\bIMPORT\s+DECLARATION\b", 0.50),
        (r"\bCUSTOMS\s+ENTRY\b", 0.50),
    ],

    boundary_boosters=[],

    continuity_patterns=[
        r"(?:Page|Sheet)\s*\d+\s*(?:of|/)\s*\d+",
        r"Page\s+\d+\s+Of\s+\d+",  # "Page 74 Of 201"
    ],

    # SECTION PATTERNS - These detect PART boundaries within the bill of entry
    # Each PART (I, II, III, IV, V) becomes a separate segment
    # User must enable with split_by_sections=True to use these
    section_patterns=[
        # "PART - I", "PART - II", "PART-III", etc.
        (r"PART\s*[-:.]?\s*([IVX]+|\d+)\s*[-:.]?\s*", 1),
        # Also handle "PART I", "PART 1" without separator
        (r"PART\s+([IVX]+|\d+)\b", 1),
    ],

    # Section splitting is OFF by default - user must enable with split_by_sections=True
    enable_section_splitting=False,
))


# -----------------------------------------------------------------------------
# Purchase Order Profile
# -----------------------------------------------------------------------------
_register(DocumentProfile(
    name="purchase_order",
    display_name="Purchase Order",
    description="Purchase Orders, POs",

    veto_fields={
        "po_number": (r"(?:P\.?O\.?|Purchase\s*Order)\s*(?:No\.?|Number|#)?\.?\s*[:=]?\s*([A-Z0-9][-A-Z0-9/]+)", False),
    },

    supporting_fields={
        "po_date": r"(?:P\.?O\.?|Order)\s*Date\s*[:=]?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
        "delivery_date": r"(?:Delivery|Required)\s*(?:Date|By)\s*[:=]?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
        "buyer_name": r"(?:Buyer|Purchaser)\s*[:=]?\s*(.+?)(?:\n|$)",
    },

    start_keywords=[
        (r"\bPURCHASE\s+ORDER\b", 0.90),
        (r"^\s*P\.?O\.?\s*(?:No\.?|#)", 0.85),
    ],

    boundary_boosters=[],

    continuity_patterns=[
        r"(?:Page|Sheet)\s*\d+\s*(?:of|/)\s*\d+",
    ],
))


# -----------------------------------------------------------------------------
# Contract Profile
# -----------------------------------------------------------------------------
_register(DocumentProfile(
    name="contract",
    display_name="Contract/Agreement",
    description="Contracts, Agreements, Terms & Conditions",

    veto_fields={
        "contract_number": (r"Contract\s*(?:No\.?|Number|#)?\.?\s*[:=]?\s*([A-Z0-9][-A-Z0-9/]+)", False),
        "agreement_number": (r"Agreement\s*(?:No\.?|Number|#)?\.?\s*[:=]?\s*([A-Z0-9][-A-Z0-9/]+)", False),
    },

    supporting_fields={
        "effective_date": r"Effective\s*Date\s*[:=]?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
        "parties": r"(?:Between|Party)\s*[:=]?\s*(.+?)(?:\n|$)",
    },

    start_keywords=[
        (r"\bCONTRACT\b", 0.75),
        (r"\bAGREEMENT\b", 0.75),
        (r"\bTERMS\s+(?:AND|&)\s+CONDITIONS\b", 0.80),
        (r"\bMEMORANDUM\s+OF\s+(?:UNDERSTANDING|AGREEMENT)\b", 0.85),
    ],

    boundary_boosters=[
        (r"THIS\s+(?:CONTRACT|AGREEMENT)\s+(?:IS\s+)?MADE", 0.80),
    ],

    continuity_patterns=[
        r"(?:Page|Sheet)\s*\d+\s*(?:of|/)\s*\d+",
        r"Article\s+\d+",
        r"Clause\s+\d+",
    ],
))


# =============================================================================
# Profile Access Functions
# =============================================================================

# Profile name aliases
PROFILE_ALIASES = {
    "inv": "invoice",
    "commercial_invoice": "invoice",
    "tax_invoice": "invoice",
    "proforma": "invoice",
    "telecom": "telecom_bill",
    "phone_bill": "telecom_bill",
    "mobile_bill": "telecom_bill",
    "bl": "shipping",
    "bill_of_lading": "shipping",
    "awb": "shipping",
    "airway_bill": "shipping",
    "pl": "packing_list",
    "coo": "certificate",
    "certificate_of_origin": "certificate",
    "be": "bill_of_entry",
    "boe": "bill_of_entry",
    "po": "purchase_order",
    "order": "purchase_order",
}


def _convert_db_profile_to_document_profile(db_profile) -> DocumentProfile:
    """Convert a database SegmentationProfile to a DocumentProfile."""
    # Convert veto fields from list of dicts to dict of tuples
    veto_fields = {}
    for f in (db_profile.veto_fields or []):
        if f.get("enabled", True):
            veto_fields[f["name"]] = (f["pattern"], f.get("bidirectional", False))

    # Convert section patterns from list of dicts to list of tuples
    section_patterns = [
        (p["pattern"], p.get("capture_group", 1))
        for p in (db_profile.section_patterns or [])
    ]

    # Convert start keywords from list of dicts to list of tuples
    start_keywords = [
        (k["pattern"], k.get("confidence", 0.75))
        for k in (db_profile.start_keywords or [])
    ]

    # Convert supporting fields from list of dicts to dict
    supporting_fields = {
        f["name"]: f["pattern"]
        for f in (db_profile.supporting_fields or [])
    }

    return DocumentProfile(
        name=db_profile.name,
        display_name=db_profile.display_name,
        description=db_profile.description or "",
        veto_fields=veto_fields,
        section_patterns=section_patterns,
        start_keywords=start_keywords,
        supporting_fields=supporting_fields,
        continuity_patterns=db_profile.continuity_patterns or [],
        enable_section_splitting=db_profile.enable_section_splitting,
    )


def get_profile_from_db(name: str):
    """
    Load a profile from the database.

    Args:
        name: Profile name

    Returns:
        DocumentProfile or None if not found
    """
    try:
        from api.database.engine import SessionLocal
        from api.database.models import SegmentationProfile

        db = SessionLocal()
        try:
            # Resolve alias first
            name_lower = name.lower().strip()
            resolved_name = PROFILE_ALIASES.get(name_lower, name_lower)

            db_profile = db.query(SegmentationProfile).filter(
                SegmentationProfile.name == resolved_name
            ).first()

            if db_profile:
                return _convert_db_profile_to_document_profile(db_profile)
            return None
        finally:
            db.close()
    except Exception:
        # If database is not available, return None to fall back to code profiles
        return None


def get_profile(name: str, use_db: bool = True) -> DocumentProfile:
    """
    Get a document profile by name.

    Priority:
    1. Database (user-configurable) if use_db=True
    2. Code-defined profiles (fallback)

    Args:
        name: Profile name (e.g., "invoice", "shipping", "certificate")
        use_db: Whether to check database first (default True)

    Returns:
        DocumentProfile or generic profile if not found
    """
    # Normalize name
    name_lower = name.lower().strip()

    # Try database first if enabled
    if use_db:
        db_profile = get_profile_from_db(name_lower)
        if db_profile:
            return db_profile

    # Direct match in code profiles
    if name_lower in PROFILES:
        return PROFILES[name_lower]

    # Try aliases
    if name_lower in PROFILE_ALIASES:
        return PROFILES[PROFILE_ALIASES[name_lower]]

    # Return generic
    return PROFILES["generic"]


def get_merged_profile(names: List[str], use_db: bool = True) -> DocumentProfile:
    """
    Merge multiple profiles into one.

    Combines all veto fields, supporting fields, and keywords from all profiles.
    Useful when processing documents with multiple expected types.

    Args:
        names: List of profile names to merge
        use_db: Whether to check database first (default True)

    Returns:
        Merged DocumentProfile
    """
    if not names:
        return get_profile("generic", use_db=use_db)

    if len(names) == 1:
        return get_profile(names[0], use_db=use_db)

    # Merge all profiles
    merged = DocumentProfile(
        name="merged",
        display_name="Mixed Documents",
        description=f"Merged profile for: {', '.join(names)}",
    )

    for name in names:
        profile = get_profile(name, use_db=use_db)

        # Merge veto fields
        for field_name, pattern_info in profile.veto_fields.items():
            if field_name not in merged.veto_fields:
                merged.veto_fields[field_name] = pattern_info

        # Merge supporting fields
        for field_name, pattern in profile.supporting_fields.items():
            if field_name not in merged.supporting_fields:
                merged.supporting_fields[field_name] = pattern

        # Merge keywords (avoiding duplicates)
        existing_patterns = {k[0] for k in merged.start_keywords}
        for keyword_info in profile.start_keywords:
            if keyword_info[0] not in existing_patterns:
                merged.start_keywords.append(keyword_info)

        # Merge boosters
        existing_boosters = {b[0] for b in merged.boundary_boosters}
        for booster in profile.boundary_boosters:
            if booster[0] not in existing_boosters:
                merged.boundary_boosters.append(booster)

        # Merge continuity patterns
        for pattern in profile.continuity_patterns:
            if pattern not in merged.continuity_patterns:
                merged.continuity_patterns.append(pattern)

        # Merge section patterns
        existing_section_patterns = {p[0] for p in merged.section_patterns}
        for section_pattern in profile.section_patterns:
            if section_pattern[0] not in existing_section_patterns:
                merged.section_patterns.append(section_pattern)

        # If any profile has section splitting enabled, enable it for merged
        if profile.enable_section_splitting:
            merged.enable_section_splitting = True

    return merged


def list_profiles() -> List[Dict[str, str]]:
    """
    List all available document profiles.

    Returns:
        List of dicts with name, display_name, description
    """
    return [
        {
            "name": p.name,
            "display_name": p.display_name,
            "description": p.description,
        }
        for p in PROFILES.values()
    ]


def create_custom_profile(
    name: str,
    veto_field_patterns: Dict[str, str],
    start_keywords: Optional[List[str]] = None,
) -> DocumentProfile:
    """
    Create a custom profile with user-specified patterns.

    This allows users to specify their own key fields for document types
    that aren't built-in.

    Args:
        name: Profile name
        veto_field_patterns: Dict of field_name -> regex pattern
        start_keywords: Optional list of keywords that indicate document start

    Returns:
        Custom DocumentProfile
    """
    profile = DocumentProfile(
        name=name,
        display_name=f"Custom: {name}",
        description=f"User-defined profile for {name}",
    )

    # Add veto fields (assume not bidirectional for custom)
    for field_name, pattern in veto_field_patterns.items():
        profile.veto_fields[field_name] = (pattern, False)

    # Add keywords with default confidence
    if start_keywords:
        for kw in start_keywords:
            profile.start_keywords.append((kw, 0.80))

    return profile
