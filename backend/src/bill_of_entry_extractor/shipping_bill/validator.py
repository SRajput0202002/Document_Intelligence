#!/usr/bin/env python3
"""
Shipping Bill Specific Validation
Handles SB-specific validation rules beyond generic schema validation
"""

from typing import Dict, List, Tuple
from bill_of_entry_extractor.validation.validator import (
    SchemaValidator,
    ValidationError,
    ValidationResult
)


class ShippingBillValidator(SchemaValidator):
    """
    Shipping Bill specific validator
    Extends base SchemaValidator with SB-specific validation rules
    """

    def __init__(self, schema_dir: str = "schema/shipping_bill"):
        """
        Initialize SB validator

        Args:
            schema_dir: Directory containing SB schema files
        """
        super().__init__(schema_dir=schema_dir)

    def _validate_part_specific(self, data: Dict, part_name: str) -> Tuple[List[ValidationError], List[ValidationError]]:
        """
        Shipping Bill specific validation logic
        Overrides base implementation to add SB-specific rules

        Args:
            data: Extracted data
            part_name: Part name (e.g., 'part-1')

        Returns:
            Tuple of (errors, warnings) lists
        """
        errors = []
        warnings = []

        # Call base implementation first
        base_errors, base_warnings = super()._validate_part_specific(data, part_name)
        errors.extend(base_errors)
        warnings.extend(base_warnings)

        # Add SB-specific validation rules
        if part_name == 'part-0':
            errors_p0, warnings_p0 = self._validate_part0(data)
            errors.extend(errors_p0)
            warnings.extend(warnings_p0)

        elif part_name == 'part-1':
            errors_p1, warnings_p1 = self._validate_part1(data)
            errors.extend(errors_p1)
            warnings.extend(warnings_p1)

        elif part_name == 'part-2':
            errors_p2, warnings_p2 = self._validate_part2(data)
            errors.extend(errors_p2)
            warnings.extend(warnings_p2)

        elif part_name == 'part-3':
            errors_p3, warnings_p3 = self._validate_part3(data)
            errors.extend(errors_p3)
            warnings.extend(warnings_p3)

        elif part_name == 'part-4':
            errors_p4, warnings_p4 = self._validate_part4(data)
            errors.extend(errors_p4)
            warnings.extend(warnings_p4)

        elif part_name == 'part-5':
            errors_p5, warnings_p5 = self._validate_part5(data)
            errors.extend(errors_p5)
            warnings.extend(warnings_p5)

        return errors, warnings

    def _validate_part0(self, data: Dict) -> Tuple[List[ValidationError], List[ValidationError]]:
        """Validate Part 0 (Header Information) specific rules"""
        errors = []
        warnings = []

        header = data.get('shipping_bill_part_0', {})

        # Validate required fields
        required_fields = ['port_code', 'sb_no', 'sb_date', 'iec_br']
        for field in required_fields:
            if not header.get(field):
                errors.append(ValidationError(
                    field=f'part-0.{field}',
                    message=f'Required field {field} is missing',
                    severity='error'
                ))

        # Validate port code format (6 characters starting with "IN")
        port_code = header.get('port_code', '')
        if port_code and (len(port_code) != 6 or not port_code.startswith('IN')):
            warnings.append(ValidationError(
                field='part-0.port_code',
                message=f'Port code should be 6 characters starting with "IN", got: {port_code}',
                severity='warning'
            ))

        # Validate numeric fields
        if 'pkg' in header and header['pkg'] is not None:
            if not isinstance(header['pkg'], (int, float)) or header['pkg'] < 0:
                errors.append(ValidationError(
                    field='part-0.pkg',
                    message='Package count must be a non-negative number',
                    severity='error'
                ))

        if 'g_wt_kgs' in header and header['g_wt_kgs'] is not None:
            if not isinstance(header['g_wt_kgs'], (int, float)) or header['g_wt_kgs'] < 0:
                errors.append(ValidationError(
                    field='part-0.g_wt_kgs',
                    message='Gross weight must be a non-negative number',
                    severity='error'
                ))

        # Validate nos object
        nos = header.get('nos', {})
        if nos:
            for field in ['inv', 'item', 'cont']:
                if field in nos and nos[field] is not None:
                    if not isinstance(nos[field], int) or nos[field] < 0:
                        warnings.append(ValidationError(
                            field=f'part-0.nos.{field}',
                            message=f'{field} count must be a non-negative integer',
                            severity='warning'
                        ))

        return errors, warnings

    def _validate_part1(self, data: Dict) -> Tuple[List[ValidationError], List[ValidationError]]:
        """Validate Part 1 (Summary) specific rules"""
        errors = []
        warnings = []

        summary = data.get('part_1_summary', {})

        # Validate status section
        status = summary.get('status', {})

        # SB number format (7 digits)
        sb_no = status.get('sb_no', '')
        if sb_no and (not sb_no.isdigit() or len(sb_no) != 7):
            warnings.append(ValidationError(
                severity="warning",
                field="part_1_summary.status.sb_no",
                message=f"SB number should be 7 digits: {sb_no}",
                part="part-1"
            ))

        # Port code format (6 characters starting with IN)
        port_code = status.get('port_code', '')
        if port_code and (len(port_code) != 6 or not port_code.startswith('IN')):
            warnings.append(ValidationError(
                severity="warning",
                field="part_1_summary.status.port_code",
                message=f"Port code format unusual: {port_code} (expected INxxxxx)",
                part="part-1"
            ))

        # IEC format (at least 10 digits)
        iec = status.get('iec_br', '')
        if iec and len(iec) < 10:
            warnings.append(ValidationError(
                severity="warning",
                field="part_1_summary.status.iec_br",
                message=f"IEC should be at least 10 digits: {iec}",
                part="part-1"
            ))

        # GSTIN format (15 characters)
        gstin = status.get('gstin', '')
        if gstin and len(gstin) != 15:
            warnings.append(ValidationError(
                severity="warning",
                field="part_1_summary.status.gstin",
                message=f"GSTIN should be 15 characters: {gstin}",
                part="part-1"
            ))

        # Validate value summary
        value_summary = summary.get('value_summary', {})
        fob_value = value_summary.get('total_fob_value', 0)
        if fob_value and not isinstance(fob_value, (int, float)):
            errors.append(ValidationError(
                severity="error",
                field="part_1_summary.value_summary.total_fob_value",
                message=f"FOB value must be numeric: {fob_value}",
                part="part-1"
            ))

        # Validate FOB value is positive for exports
        if isinstance(fob_value, (int, float)) and fob_value <= 0:
            errors.append(ValidationError(
                severity="error",
                field="part_1_summary.value_summary.total_fob_value",
                message=f"FOB value must be positive for exports: {fob_value}",
                part="part-1"
            ))

        return errors, warnings

    def _validate_part2(self, data: Dict) -> Tuple[List[ValidationError], List[ValidationError]]:
        """Validate Part 2 (Invoice Details) specific rules"""
        errors = []
        warnings = []

        invoices = data.get('part_2_invoice_valuation', {}).get('invoices', [])

        if not invoices:
            errors.append(ValidationError(
                severity="error",
                field="part_2_invoice_valuation.invoices",
                message="At least one invoice must be present",
                part="part-2"
            ))
            return errors, warnings

        for idx, invoice in enumerate(invoices):
            invoice_prefix = f"part_2_invoice_valuation.invoices[{idx}]"

            # Validate invoice value
            inv_value = invoice.get('invoice_value', 0)
            if inv_value and not isinstance(inv_value, (int, float)):
                errors.append(ValidationError(
                    severity="error",
                    field=f"{invoice_prefix}.invoice_value",
                    message=f"Invoice value must be numeric: {inv_value}",
                    part="part-2"
                ))

            # Validate buyer country is present
            buyer = invoice.get('buyer', {})
            if not buyer.get('country'):
                warnings.append(ValidationError(
                    severity="warning",
                    field=f"{invoice_prefix}.buyer.country",
                    message="Buyer country should be specified for export",
                    part="part-2"
                ))

            # Validate FOB value consistency
            valuation = invoice.get('valuation', {})
            fob_value = valuation.get('fob_value', 0)
            fob_value_inr = valuation.get('fob_value_inr', 0)
            exchange_rate = valuation.get('exchange_rate', 0)

            if fob_value and fob_value_inr and exchange_rate:
                expected_inr = fob_value * exchange_rate
                variance = abs(expected_inr - fob_value_inr) / expected_inr if expected_inr else 0
                if variance > 0.05:  # 5% tolerance
                    warnings.append(ValidationError(
                        severity="warning",
                        field=f"{invoice_prefix}.valuation",
                        message=f"FOB currency conversion inconsistent: {fob_value} × {exchange_rate} ≠ {fob_value_inr}",
                        part="part-2"
                    ))

        return errors, warnings

    def _validate_part3(self, data: Dict) -> Tuple[List[ValidationError], List[ValidationError]]:
        """Validate Part 3 (Item Details) specific rules"""
        errors = []
        warnings = []

        item_details = data.get('part_3_item_details', {})
        items = item_details.get('items', [])

        if not items:
            errors.append(ValidationError(
                severity="error",
                field="part_3_item_details.items",
                message="At least one item must be present",
                part="part-3"
            ))
            return errors, warnings

        total_fob_calculated = 0

        for idx, item in enumerate(items):
            item_prefix = f"part_3_item_details.items[{idx}]"

            # Validate HS code format (8 digits)
            hs_code = item.get('hs_code', '')
            if hs_code and (not hs_code.isdigit() or len(hs_code) != 8):
                warnings.append(ValidationError(
                    severity="warning",
                    field=f"{item_prefix}.hs_code",
                    message=f"HS code should be 8 digits: {hs_code}",
                    part="part-3"
                ))

            # Validate quantity is positive
            quantity = item.get('quantity', 0)
            if quantity and not isinstance(quantity, (int, float)):
                errors.append(ValidationError(
                    severity="error",
                    field=f"{item_prefix}.quantity",
                    message=f"Quantity must be numeric: {quantity}",
                    part="part-3"
                ))
            elif isinstance(quantity, (int, float)) and quantity <= 0:
                errors.append(ValidationError(
                    severity="error",
                    field=f"{item_prefix}.quantity",
                    message=f"Quantity must be positive: {quantity}",
                    part="part-3"
                ))

            # Validate FOB value is positive
            fob_value_inr = item.get('fob_value_inr', 0)
            if fob_value_inr and not isinstance(fob_value_inr, (int, float)):
                errors.append(ValidationError(
                    severity="error",
                    field=f"{item_prefix}.fob_value_inr",
                    message=f"FOB value must be numeric: {fob_value_inr}",
                    part="part-3"
                ))
            elif isinstance(fob_value_inr, (int, float)):
                if fob_value_inr <= 0:
                    errors.append(ValidationError(
                        severity="error",
                        field=f"{item_prefix}.fob_value_inr",
                        message=f"FOB value must be positive: {fob_value_inr}",
                        part="part-3"
                    ))
                else:
                    total_fob_calculated += fob_value_inr

        # Validate summary totals
        summary = item_details.get('summary', {})
        summary_total = summary.get('total_fob_value_inr', 0)

        if summary_total and total_fob_calculated:
            variance = abs(summary_total - total_fob_calculated) / summary_total if summary_total else 0
            if variance > 0.01:  # 1% tolerance
                warnings.append(ValidationError(
                    severity="warning",
                    field="part_3_item_details.summary.total_fob_value_inr",
                    message=f"Summary FOB ({summary_total}) doesn't match sum of items ({total_fob_calculated})",
                    part="part-3"
                ))

        return errors, warnings

    def _validate_part4(self, data: Dict) -> Tuple[List[ValidationError], List[ValidationError]]:
        """Validate Part 4 (Export Scheme Details) specific rules"""
        errors = []
        warnings = []

        scheme_details = data.get('part_4_export_scheme_details', {})

        # Validate Duty Drawback
        dbk = scheme_details.get('duty_drawback', {})
        if dbk.get('claimed') and not dbk.get('dbk_amount'):
            warnings.append(ValidationError(
                severity="warning",
                field="part_4_export_scheme_details.duty_drawback.dbk_amount",
                message="DBK claimed but amount is missing or zero",
                part="part-4"
            ))

        # Validate RODTEP
        rodtep = scheme_details.get('rodtep', {})
        if rodtep.get('claimed') and not rodtep.get('rodtep_amount'):
            warnings.append(ValidationError(
                severity="warning",
                field="part_4_export_scheme_details.rodtep.rodtep_amount",
                message="RODTEP claimed but amount is missing or zero",
                part="part-4"
            ))

        # Validate DFIA
        dfia = scheme_details.get('dfia', {})
        if dfia.get('applicable') and not dfia.get('license_number'):
            errors.append(ValidationError(
                severity="error",
                field="part_4_export_scheme_details.dfia.license_number",
                message="DFIA applicable but license number is missing",
                part="part-4"
            ))

        # Validate Status Holder
        status_holder = scheme_details.get('status_holder_benefits', {})
        if status_holder.get('status_holder') and not status_holder.get('certificate_number'):
            warnings.append(ValidationError(
                severity="warning",
                field="part_4_export_scheme_details.status_holder_benefits.certificate_number",
                message="Status holder claimed but certificate number is missing",
                part="part-4"
            ))

        return errors, warnings

    def _validate_part5(self, data: Dict) -> Tuple[List[ValidationError], List[ValidationError]]:
        """Validate Part 5 (Declarations) specific rules"""
        errors = []
        warnings = []

        declarations_data = data.get('part_5_declarations', {})

        # Validate signatory is present (required)
        signatory = declarations_data.get('signatory', {})
        if not signatory:
            errors.append(ValidationError(
                severity="error",
                field="part_5_declarations.signatory",
                message="Authorized signatory details are required",
                part="part-5"
            ))
            return errors, warnings

        # Validate signatory required fields
        if not signatory.get('name'):
            errors.append(ValidationError(
                severity="error",
                field="part_5_declarations.signatory.name",
                message="Signatory name is required",
                part="part-5"
            ))

        if not signatory.get('designation'):
            warnings.append(ValidationError(
                severity="warning",
                field="part_5_declarations.signatory.designation",
                message="Signatory designation should be specified",
                part="part-5"
            ))

        if not signatory.get('date'):
            errors.append(ValidationError(
                severity="error",
                field="part_5_declarations.signatory.date",
                message="Signatory date is required",
                part="part-5"
            ))

        if not signatory.get('place'):
            warnings.append(ValidationError(
                severity="warning",
                field="part_5_declarations.signatory.place",
                message="Place of signing should be specified",
                part="part-5"
            ))

        # Validate at least one declaration is present
        declarations = declarations_data.get('declarations', [])
        if not declarations:
            warnings.append(ValidationError(
                severity="warning",
                field="part_5_declarations.declarations",
                message="At least one declaration statement should be present",
                part="part-5"
            ))

        # Validate self-sealing declaration consistency
        self_sealing = declarations_data.get('self_sealing_declaration', {})
        if self_sealing.get('applicable'):
            containers = self_sealing.get('container_numbers', [])
            if not containers:
                warnings.append(ValidationError(
                    severity="warning",
                    field="part_5_declarations.self_sealing_declaration.container_numbers",
                    message="Self-sealing claimed but no container numbers provided",
                    part="part-5"
                ))

        return errors, warnings


# Convenience function
def validate_shipping_bill(data: Dict, part_name: str, schema_dir: str = "schema/shipping_bill") -> ValidationResult:
    """
    Validate Shipping Bill data

    Args:
        data: Extracted data
        part_name: Part name (e.g., 'part-1')
        schema_dir: Schema directory

    Returns:
        ValidationResult
    """
    validator = ShippingBillValidator(schema_dir=schema_dir)
    return validator.validate(data, part_name)
