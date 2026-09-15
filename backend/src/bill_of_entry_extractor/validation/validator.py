#!/usr/bin/env python3
"""
Schema Validation and Cross-Validation System
Validates extracted data against schemas and performs cross-part validation
"""

import json
import jsonschema
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ValidationError:
    """Represents a validation error"""
    severity: str  # 'critical', 'warning', 'info'
    field: str
    message: str
    part: Optional[str] = None

    def __repr__(self):
        prefix = "❌" if self.severity == "critical" else "⚠️" if self.severity == "warning" else "ℹ️"
        part_str = f"[{self.part}] " if self.part else ""
        return f"{prefix} {part_str}{self.field}: {self.message}"


@dataclass
class ValidationResult:
    """Result of validation"""
    is_valid: bool
    errors: List[ValidationError]
    warnings: List[ValidationError]
    info: List[ValidationError]

    def has_critical_errors(self) -> bool:
        return len(self.errors) > 0

    def __repr__(self):
        status = "✅ VALID" if self.is_valid else "❌ INVALID"
        summary = f"{status}\n"
        summary += f"  Critical Errors: {len(self.errors)}\n"
        summary += f"  Warnings: {len(self.warnings)}\n"
        summary += f"  Info: {len(self.info)}\n"

        if self.errors:
            summary += "\nCritical Errors:\n"
            for err in self.errors:
                summary += f"  {err}\n"

        if self.warnings:
            summary += "\nWarnings:\n"
            for warn in self.warnings[:5]:  # Show max 5 warnings
                summary += f"  {warn}\n"
            if len(self.warnings) > 5:
                summary += f"  ... and {len(self.warnings) - 5} more warnings\n"

        return summary


class SchemaValidator:
    """Validates data against JSON schemas"""

    def __init__(self, schema_dir: str = "schema"):
        self.schema_dir = Path(schema_dir)

    def load_schema(self, part_name: str) -> Dict:
        """Load schema for a specific part"""
        schema_path = self.schema_dir / f"{part_name}.json"
        with open(schema_path, 'r') as f:
            return json.load(f)

    def validate(self, data: Dict, part_name: str) -> ValidationResult:
        """
        Validate data against schema for a specific part

        Args:
            data: Extracted data to validate
            part_name: Part name (e.g., 'part-1', 'part-2')

        Returns:
            ValidationResult
        """
        errors = []
        warnings = []
        info = []

        try:
            # Load schema
            schema = self.load_schema(part_name)

            # Validate against schema
            validator = jsonschema.Draft7Validator(schema)
            schema_errors = list(validator.iter_errors(data))

            for err in schema_errors:
                field_path = ".".join(str(p) for p in err.path) if err.path else "root"
                errors.append(ValidationError(
                    severity="critical",
                    field=field_path,
                    message=err.message,
                    part=part_name
                ))

            # Part-specific validation
            part_errors, part_warnings = self._validate_part_specific(data, part_name)
            errors.extend(part_errors)
            warnings.extend(part_warnings)

        except FileNotFoundError:
            errors.append(ValidationError(
                severity="critical",
                field="schema",
                message=f"Schema file not found for {part_name}",
                part=part_name
            ))
        except json.JSONDecodeError as e:
            errors.append(ValidationError(
                severity="critical",
                field="json",
                message=f"Invalid JSON: {str(e)}",
                part=part_name
            ))
        except Exception as e:
            errors.append(ValidationError(
                severity="critical",
                field="validation",
                message=f"Validation error: {str(e)}",
                part=part_name
            ))

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            info=info
        )

    def _validate_part_specific(self, data: Dict, part_name: str) -> Tuple[List[ValidationError], List[ValidationError]]:
        """Part-specific validation logic"""
        errors = []
        warnings = []

        if part_name == 'part-2':
            errors_p2, warnings_p2 = self._validate_part2(data)
            errors.extend(errors_p2)
            warnings.extend(warnings_p2)

        elif part_name == 'part-3':
            errors_p3, warnings_p3 = self._validate_part3(data)
            errors.extend(errors_p3)
            warnings.extend(warnings_p3)

        return errors, warnings

    def _validate_part2(self, data: Dict) -> Tuple[List[ValidationError], List[ValidationError]]:
        """Validate Part II specific logic"""
        errors = []
        warnings = []

        # Get invoices array
        invoices = data.get('part_2_invoice_valuation', {}).get('invoices', [])

        for i, invoice in enumerate(invoices):
            # Validate items exist (check both 'items' and 'item_details' for compatibility)
            items = invoice.get('items', []) or invoice.get('item_details', [])
            if not items:
                errors.append(ValidationError(
                    severity="critical",
                    field=f"invoices[{i}].items",
                    message="Invoice must have at least one item",
                    part="part-2"
                ))
                continue

            # Validate invoice value matches item amounts
            valuation = invoice.get('valuation', {})
            # Try both 'inv_value' and 'invoice_value' for compatibility
            inv_value = valuation.get('inv_value', 0) or valuation.get('invoice_value', 0)

            total_item_amount = sum(item.get('amount', 0) for item in items)

            # Allow 1% tolerance for rounding
            tolerance = max(inv_value * 0.01, 1.0)
            if abs(inv_value - total_item_amount) > tolerance:
                warnings.append(ValidationError(
                    severity="warning",
                    field=f"invoices[{i}].valuation.inv_value",
                    message=f"Invoice value ({inv_value}) doesn't match sum of items ({total_item_amount})",
                    part="part-2"
                ))

            # Validate item calculations
            for j, item in enumerate(items):
                unit_price = item.get('unit_price', 0)
                quantity = item.get('quantity', 0)
                amount = item.get('amount', 0)

                expected_amount = unit_price * quantity
                if abs(amount - expected_amount) > 0.01:
                    warnings.append(ValidationError(
                        severity="warning",
                        field=f"invoices[{i}].items[{j}].amount",
                        message=f"Amount ({amount}) doesn't match unit_price × quantity ({expected_amount})",
                        part="part-2"
                    ))

        return errors, warnings

    def _validate_part3(self, data: Dict) -> Tuple[List[ValidationError], List[ValidationError]]:
        """Validate Part III specific logic"""
        errors = []
        warnings = []

        # Get item duties
        item_duties = data.get('part_3_duties', {}).get('item_duties', [])

        for i, item in enumerate(item_duties):
            # Validate total duty calculation
            total_duty = item.get('total_duty', 0)

            # Sum all duty amounts
            duty_sum = 0
            duty_fields = ['bcd', 'acd', 'sws', 'sad', 'igst', 'g_cess', 'add', 'cvd', 'sg',
                          'sp_exd', 'chcess', 'tta', 'cess', 'caidc', 'eaidc',
                          'cus_edc', 'cus_hec', 'ncd']

            for duty_field in duty_fields:
                duty_obj = item.get(duty_field, {})
                if isinstance(duty_obj, dict):
                    duty_sum += duty_obj.get('amount', 0)

            # Add aggregate if present
            duty_sum += item.get('aggr', 0)

            # Allow small tolerance for rounding
            if abs(total_duty - duty_sum) > 1.0:
                warnings.append(ValidationError(
                    severity="warning",
                    field=f"item_duties[{i}].total_duty",
                    message=f"Total duty ({total_duty}) doesn't match sum of duties ({duty_sum})",
                    part="part-3"
                ))

            # Warn if no duties found
            if duty_sum == 0 and total_duty > 0:
                warnings.append(ValidationError(
                    severity="warning",
                    field=f"item_duties[{i}]",
                    message="Total duty > 0 but no individual duties found",
                    part="part-3"
                ))

        return errors, warnings


class CrossValidator:
    """Performs cross-validation across multiple parts"""

    def validate(self, all_parts: Dict[str, Dict]) -> ValidationResult:
        """
        Cross-validate data across multiple parts

        Args:
            all_parts: Dictionary mapping part names to extracted data

        Returns:
            ValidationResult
        """
        errors = []
        warnings = []
        info = []

        # Validate Part II vs Part III item counts
        if 'part-2' in all_parts and 'part-3' in all_parts:
            errors_23, warnings_23 = self._validate_part2_vs_part3(
                all_parts['part-2'],
                all_parts['part-3']
            )
            errors.extend(errors_23)
            warnings.extend(warnings_23)

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            info=info
        )

    def _validate_part2_vs_part3(self, part2_data: Dict, part3_data: Dict) -> Tuple[List[ValidationError], List[ValidationError]]:
        """Validate that Part II and Part III have matching items"""
        errors = []
        warnings = []

        # Count items in Part II
        invoices = part2_data.get('part_2_invoice_valuation', {}).get('invoices', [])
        part2_item_count = sum(len(inv.get('items', [])) for inv in invoices)

        # Count items in Part III
        item_duties = part3_data.get('part_3_duties', {}).get('item_duties', [])
        part3_item_count = len(item_duties)

        if part2_item_count != part3_item_count:
            warnings.append(ValidationError(
                severity="warning",
                field="item_count_mismatch",
                message=f"Part II has {part2_item_count} items but Part III has {part3_item_count} items",
                part="cross-validation"
            ))

        # Validate CTH codes match
        part2_cth_codes = []
        for inv in invoices:
            for item in inv.get('items', []):
                part2_cth_codes.append(item.get('cth', ''))

        part3_cth_codes = [item.get('cth', '') for item in item_duties]

        if part2_cth_codes != part3_cth_codes:
            mismatches = []
            for i, (cth2, cth3) in enumerate(zip(part2_cth_codes, part3_cth_codes)):
                if cth2 != cth3:
                    mismatches.append(f"Item {i+1}: Part II={cth2}, Part III={cth3}")

            if mismatches:
                warnings.append(ValidationError(
                    severity="warning",
                    field="cth_mismatch",
                    message=f"CTH codes don't match: {', '.join(mismatches[:3])}{'...' if len(mismatches) > 3 else ''}",
                    part="cross-validation"
                ))

        return errors, warnings


if __name__ == "__main__":
    # Test validation
    validator = SchemaValidator()

    # Test with a sample Part 2 data
    sample_data = {
        "part_2_invoice_valuation": {
            "invoices": [
                {
                    "invoice_header": {
                        "s_no": 1,
                        "invoice_no": "INV123",
                        "invoice_date": "01/04/2025"
                    },
                    "transacting_parties": {
                        "buyer": {"name": "Test Buyer", "address": {}},
                        "seller": {"name": "Test Seller", "address": {}}
                    },
                    "valuation": {
                        "inv_value": 10000,
                        "valuation_method": "Transaction Value",
                        "cur": "USD",
                        "term": "CIF"
                    },
                    "items": [
                        {
                            "s_no": 1,
                            "cth": "12345678",
                            "description": "Test Item",
                            "unit_price": 100,
                            "quantity": 10,
                            "uqc": "NOS",
                            "amount": 1000
                        }
                    ]
                }
            ]
        }
    }

    result = validator.validate(sample_data, "part-2")
    print(result)
