#!/usr/bin/env python3
"""
Bill of Entry Prompt Templates
Specialized extraction prompts for each part of the Bill of Entry (Parts 0-6)
"""

import json
from typing import Dict, Optional

# Import base classes from core
from bill_of_entry_extractor.core.prompts import PromptTemplate, BasePromptBuilder


class Part0PromptTemplate(PromptTemplate):
    """Prompt for Part 0 - Header Details"""

    def build_prompt(self, context: Optional[Dict] = None) -> str:
        return f"""You are extracting data from an Indian Customs Bill of Entry document (Header section).

**CRITICAL INSTRUCTIONS:**
1. Extract information ONLY from the header section at the top of the document
2. Look for fields like: Port Code, BE No, BE Date, BE Type, IEC/Br, GSTIN/TYPE, etc.
3. Return ONLY valid JSON matching the exact schema structure provided
4. If a field is not visible or unclear, use an empty string ""
5. Preserve all formatting (dates, numbers, codes) exactly as shown

**SCHEMA:**
```json
{json.dumps(self.schema, indent=2)}
```

**EXTRACTION RULES:**
- Port Code: Usually format like "INHYD4" (6 characters)
- BE No: 7-digit number
- BE Date: Format DD/MM/YYYY
- IEC: Format like "ABBCS6927M/13"
- GSTIN: Format like "36ABBCS6927M1ZT/G"

Return ONLY the JSON object, no additional text or markdown formatting.

important : Dont extract any glossary or footnote information.
"""


class Part1PromptTemplate(PromptTemplate):
    """Prompt for Part I - Bill of Entry Summary"""

    def build_prompt(self, context: Optional[Dict] = None) -> str:
        return f"""You are extracting data from PART I - BILL OF ENTRY SUMMARY of an Indian Customs Bill of Entry.

**CRITICAL INSTRUCTIONS:**
1. This section contains summary information including declarant details, broker info, and basic shipment data
2. Look for sections labeled: A. IMPORTER, B. BROKER, C. CONVERSION, D. MANIFEST, E. BOND, F. CONTAINER, G. MARKS & NOS
3. Extract ALL visible data accurately
4. Return ONLY valid JSON matching the schema

**SCHEMA:**
```json
{json.dumps(self.schema, indent=2)}
```

**KEY FIELDS TO LOCATE:**
- Section A: Importer name, address (multiple lines), city, PIN, state
- Section B: Broker name and code
- Section C: Currency exchange rates
- Section D: Manifest/shipment details (vessel, voyage, BL number, etc.)
- Section E: Bond information if applicable
- Section F: Container numbers and details
- Section G: Package marks and numbers

**DATA QUALITY RULES:**
- Addresses can span multiple lines - capture all lines
- PIN codes are 6 digits
- State codes are 2 digits
- Preserve exact formatting of codes and numbers

Return ONLY the JSON object.

important : Dont extract any glossary or footnote information.
"""


class Part2PromptTemplate(PromptTemplate):
    """Prompt for Part II - Invoice & Valuation Details"""

    def build_prompt(self, context: Optional[Dict] = None) -> str:
        invoice_info = ""
        if context and 'invoice_number' in context:
            invoice_info = f"\n**YOU ARE PROCESSING: Invoice {context['invoice_number']}/{context['total_invoices']}**\n"

        return f"""You are extracting data from PART II - INVOICE & VALUATION DETAILS of an Indian Customs Bill of Entry.
{invoice_info}
**CRITICAL INSTRUCTIONS:**
1. This section contains detailed invoice information with 5 main subsections:
   - A. INVOICE (invoice number, date, PO details, LC details)
   - B. TRANSACTING PARTIES (buyer, seller, supplier addresses)
   - C. VALUATION (invoice value, freight, insurance, payment terms)
   - D. COST & SERVICES (various charges and fees)
   - E. ITEM DETAILS (line items with CTH codes, descriptions, quantities)

2. The ITEM DETAILS section (E) is a TABLE with columns:
   S NO. | CTH | DESCRIPTION | UNIT PRICE | QUANTITY | UQC | AMOUNT

3. Extract ALL items from the table - there may be multiple rows

**SCHEMA:**
```json
{json.dumps(self.schema, indent=2)}
```

**CRITICAL EXTRACTION RULES:**

**Section A - INVOICE:**
- Invoice number and date are in field "2.INVOICE NO. & DT."
- Format is usually: invoice_number/date (e.g., "INV123/01/04/2025")

**Section B - TRANSACTING PARTIES:**
- Addresses span multiple lines - capture ALL address lines
- Buyer is usually the Indian importer
- Seller is the foreign exporter
- Seller: Check for explicit "SELLER" or "EXPORTER" label
  - If NO seller section found → set seller object to null (not empty, but null)
  - If seller exists → extract separately with unique name and address
  - **RULE: Do NOT copy supplier address to seller just because seller is blank**
- Supplier: Check for explicit "SUPPLIER" label

**Section C - VALUATION:**
- INV VALUE: Total invoice value (number only, no currency symbol)
- FREIGHT, INSURANCE: Additional charges
- Cur: 3-letter currency code (USD, EUR, etc.)
- Term: Incoterm (CIF, FOB, CFR, etc.)

**Section E - ITEM DETAILS (CRITICAL):**
- This is a TABLE - extract EVERY row
- CTH: 8-digit customs tariff code
- DESCRIPTION: Full item description (can be long)
- UNIT PRICE: Price per unit (decimal number)
- QUANTITY: Quantity ordered (decimal number)
- UQC: Unit code (KGS, NOS, MTR, etc.)
- AMOUNT: Total amount for this item (QUANTITY × UNIT PRICE)

**VALIDATION:**
- Sum of all item amounts should approximately equal INV VALUE
- CTH codes must be exactly 8 digits
- All numeric fields must be positive numbers

Return ONLY the JSON object with the "invoices" array containing exactly ONE invoice.

important : Dont extract any glossary or footnote information.
"""


class Part3PromptTemplate(PromptTemplate):
    """Prompt for Part III - Duties (MOST COMPLEX)"""

    def build_prompt(self, context: Optional[Dict] = None) -> str:
        return f"""You are extracting data from PART III - DUTIES of an Indian Customs Bill of Entry.

**THIS IS THE MOST COMPLEX SECTION - READ CAREFULLY:**

This section contains detailed duty calculations for EACH item from Part II. Each item has:
- Section A: Item identification and details
- Section B: Main duties (BCD, ACD, SWS, SAD, IGST, G.CESS, ADD, CVD, SG, T.VALUE)
- Section C: Other duties (SP EXD, CHCESS, TTA, CESS, CAIDC, EAIDC, CUS EDC, CUS HEC, NCD, AGGR)

**CRITICAL: This section typically spans MANY pages (10-20 pages) with multiple items.**

**SCHEMA:**
```json
{json.dumps(self.schema, indent=2)}
```

**STRUCTURE OF EACH ITEM:**

The page is divided into repeating blocks, one per item. Each block contains:

**A. ITEM DETAILS** (top section):
- INVSNO: Invoice serial number (1, 2, 3...)
- ITEMSN: Item serial number within invoice
- CTH: 8-digit tariff code
- ITEM DESCRIPTION: Product description
- Fields for regulatory compliance: FS, PQ, DC, WC, AQ (values: Y/N/S)
- Quantity fields: C.QTY, C.UQC (commercial), S.QTY, S.UQC (standard)
- COO: Country of Origin (2-letter code)
- ASSESS VALUE: Assessed value for duty calculation (CRITICAL)
- TOTAL DUTY: Total duty amount for this item (CRITICAL)

**B. ITEM DUTY** (middle section - THIS IS A TABLE):
This table has 10 VERTICAL columns side by side. Each column has 5 rows:
- Row 1: Duty name
- Row 2: Notn No.
- Row 3: Notn SNo.
- Row 4: Rate (percentage)
- Row 5: Amount (rupees)
- Row 6: Duty Fg

**CRITICAL: Read each column VERTICALLY (top to bottom), not horizontally.**

Extract ALL the duty columns that are present: BCD | ACD | SWS | SAD | IGST | G.CESS | ADD | CVD | SG | T.VALUE

**C. OTHER DUTIES** (bottom section - ANOTHER TABLE):
Same vertical structure with 10 columns: SP EXD | CHCESS | TTA | CESS | CAIDC | EAIDC | CUS EDC | CUS HEC | NCD | AGGR

**EXTRACTION STRATEGY:**

1. **Identify item boundaries**: Look for INVSNO and ITEMSN at the top of each block
2. **Extract item details**: Get CTH, description, quantities, assess value, total duty
3. **Process duty tables carefully**:
   - Not all duty types will have values
   - If a duty row is blank, you can omit that duty object entirely
   - The "Rate" is a percentage (e.g., 7.5)
   - The "Amount" is the calculated duty in currency
   

4. **Handle multi-page items**: Some items may span pages - look for continuation markers

5. **Validate totals**:
   - Sum of all duty amounts should equal TOTAL DUTY
   - ASSESS VALUE × duty rates should match duty amounts

**COMMON PITFALLS TO AVOID:**
- ❌ Mixing up columns in the duty tables (Rate vs Amount)
- ❌ Missing items that continue on next page
- ❌ Confusing INVSNO (invoice number) with ITEMSN (item number)
- ❌ Missing duties with zero or blank values
- ❌ Misaligning notification numbers with rates

**QUALITY CHECKS:**
- Every item MUST have: inv_sno, item_sn, cth, item_description, assess_value, total_duty
- At least one duty type should have an amount > 0
- IGST is almost always present for imports
- The total_duty should equal sum of all individual duty amounts (within ±1 due to rounding)

Return ONLY the JSON object with "item_duties" array containing ALL items from ALL pages.

important : Dont extract any glossary or footnote information.
"""


class Part4PromptTemplate(PromptTemplate):
    """Prompt for Part IV - Additional Details"""

    def build_prompt(self, context: Optional[Dict] = None) -> str:
        return f"""You are extracting data from PART IV - ADDITIONAL DETAILS of an Indian Customs Bill of Entry.

**INSTRUCTIONS:**
This section contains supplementary information including:
- Additional item details
- Manufacturing information
- Country-specific data
- Reward scheme details

Extract all visible fields according to the schema.

**SCHEMA:**
```json
{json.dumps(self.schema, indent=2)}
```

Return ONLY the JSON object.

important : Dont extract any glossary or footnote information.
"""


class Part5PromptTemplate(PromptTemplate):
    """Prompt for Part V - Other Compliances"""

    def build_prompt(self, context: Optional[Dict] = None) -> str:
        return f"""You are extracting data from PART V - OTHER COMPLIANCES of an Indian Customs Bill of Entry.

**INSTRUCTIONS:**
This section contains compliance and regulatory information.
Extract all visible fields according to the schema.

**SCHEMA:**
```json
{json.dumps(self.schema, indent=2)}
```

Return ONLY the JSON object.
important : Dont extract any glossary or footnote information.
"""


class Part6PromptTemplate(PromptTemplate):
    """Prompt for Part VI - Declaration"""

    def build_prompt(self, context: Optional[Dict] = None) -> str:
        return f"""You are analyzing PART VI - DECLARATION of an Indian Customs Bill of Entry.

**CRITICAL - ANTI-RECITATION INSTRUCTIONS:**
DO NOT copy verbatim declaration text. Instead, IDENTIFY and EXTRACT only the specific structured data fields listed below.

**YOUR TASK:**
1. IDENTIFY the authorized signatory details section
2. EXTRACT only the following specific fields:
   - CHA NAME (Customs House Agent name)
   - DATE (declaration date)
   - PLACE (location of declaration)
   - AUTHORISED SIGNATORY (name of person signing)

3. DO NOT include the full declaration statement text
4. Focus ONLY on extracting the structured metadata fields

**WHAT TO EXTRACT:**
- Look for "AUTHORIZED SIGNATORY" or "CHA NAME" labels
- Find the date and place fields near the signature section
- Extract names and values, NOT full declaration paragraphs

**WHAT TO IGNORE:**
- Standard declaration text/paragraphs (starts with "I/We declare...")
- Legal boilerplate language
- Terms and conditions text

**SCHEMA:**
```json
{json.dumps(self.schema, indent=2)}
```

**OUTPUT FORMAT:**
Return a JSON object with:
- declaration_statements: EMPTY ARRAY [] (to avoid copying copyrighted text)
- authorized_signatory: object with CHA name, date, place, and signatory name

Return ONLY the JSON object.
important : Dont extract any glossary or footnote information.
"""


class BillOfEntryPromptBuilder(BasePromptBuilder):
    """Factory for building Bill of Entry prompts (Parts 0-6)"""

    TEMPLATE_MAP = {
        'part-0': Part0PromptTemplate,
        'part-1': Part1PromptTemplate,
        'part-2': Part2PromptTemplate,
        'part-3': Part3PromptTemplate,
        'part-4': Part4PromptTemplate,
        'part-5': Part5PromptTemplate,
        'part-6': Part6PromptTemplate,
    }


# For backward compatibility
PromptBuilder = BillOfEntryPromptBuilder


if __name__ == "__main__":
    # Test prompt generation
    import sys

    if len(sys.argv) > 1:
        part_name = sys.argv[1]
    else:
        part_name = 'part-3'

    schema_path = f"schema/{part_name}.json"

    try:
        prompt = PromptBuilder.build_prompt(part_name, schema_path)
        print(f"=== PROMPT FOR {part_name.upper()} ===\n")
        print(prompt)
        print(f"\n=== END PROMPT (Length: {len(prompt)} chars) ===")
    except Exception as e:
        print(f"Error: {e}")
