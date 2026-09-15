#!/usr/bin/env python3
"""
Bill of Entry Specific Validation
Handles BE-specific validation rules beyond generic schema validation
"""

from typing import Dict, List, Tuple
from bill_of_entry_extractor.validation.validator import (
    SchemaValidator,
    ValidationError,
    ValidationResult
)


class BillOfEntryValidator(SchemaValidator):
    """
    Bill of Entry specific validator
    Extends base SchemaValidator with BE-specific validation rules
    """

    def __init__(self, schema_dir: str = "schema/bill_of_entry"):
        """
        Initialize BE validator

        Args:
            schema_dir: Directory containing BE schema files
        """
        super().__init__(schema_dir=schema_dir)

    def _validate_part_specific(self, data: Dict, part_name: str) -> Tuple[List[ValidationError], List[ValidationError]]:
        """
        Bill of Entry specific validation logic
        Overrides base implementation to add BE-specific rules

        Args:
            data: Extracted data
            part_name: Part name (e.g., 'part-2')

        Returns:
            Tuple of (errors, warnings) lists
        """
        errors = []
        warnings = []

        # Call base implementation first
        base_errors, base_warnings = super()._validate_part_specific(data, part_name)
        errors.extend(base_errors)
        warnings.extend(base_warnings)

        # Add BE-specific validation rules
        if part_name == 'part-0':
            errors_p0, warnings_p0 = self._validate_part0(data)
            errors.extend(errors_p0)
            warnings.extend(warnings_p0)

        elif part_name == 'part-1':
            errors_p1, warnings_p1 = self._validate_part1(data)
            errors.extend(errors_p1)
            warnings.extend(warnings_p1)

        return errors, warnings

    def _validate_part0(self, data: Dict) -> Tuple[List[ValidationError], List[ValidationError]]:
        """Validate Part 0 (Header) specific rules"""
        errors = []
        warnings = []

        # Validate BE number format (7 digits)
        header = data.get('header_details', {})
        be_no = header.get('be_no', '')
        if be_no and not be_no.isdigit():
            warnings.append(ValidationError(
                severity="warning",
                field="header_details.be_no",
                message=f"BE number should be numeric: {be_no}",
                part="part-0"
            ))

        # Validate port code format (6 characters starting with IN)
        port_code = header.get('port_code', '')
        if port_code and (len(port_code) != 6 or not port_code.startswith('IN')):
            warnings.append(ValidationError(
                severity="warning",
                field="header_details.port_code",
                message=f"Port code format unusual: {port_code} (expected INxxxxx)",
                part="part-0"
            ))

        return errors, warnings

    def _validate_part1(self, data: Dict) -> Tuple[List[ValidationError], List[ValidationError]]:
        """Validate Part 1 (Summary) specific rules"""
        errors = []
        warnings = []

        # Validate duty summary calculations if present
        summary = data.get('part_1_summary', {})
        duty_summary = summary.get('duty_summary', {})

        # Check if total duties field exists and is numeric
        total_duty = duty_summary.get('total_duty', 0)
        if total_duty and not isinstance(total_duty, (int, float)):
            warnings.append(ValidationError(
                severity="warning",
                field="part_1_summary.duty_summary.total_duty",
                message=f"Total duty should be numeric: {total_duty}",
                part="part-1"
            ))

        return errors, warnings


# Convenience function
def validate_bill_of_entry(data: Dict, part_name: str, schema_dir: str = "schema/bill_of_entry") -> ValidationResult:
    """
    Validate Bill of Entry data

    Args:
        data: Extracted data
        part_name: Part name (e.g., 'part-2')
        schema_dir: Schema directory

    Returns:
        ValidationResult
    """
    validator = BillOfEntryValidator(schema_dir=schema_dir)
    return validator.validate(data, part_name)
