#!/usr/bin/env python3
"""
Shipping Bill Prompt Templates
Specialized extraction prompts for each part of the Shipping Bill (Part 0, Parts I-V)
"""

import json
from typing import Dict, Optional

# Import base classes from core
from bill_of_entry_extractor.core.prompts import PromptTemplate, BasePromptBuilder


class Part0PromptTemplate(PromptTemplate):
    """Prompt for Part 0 - Header Information"""

    def build_prompt(self, context: Optional[Dict] = None) -> str:
        return f"""Extract data from PART 0 - HEADER INFORMATION of a Shipping Bill.

**SCHEMA:**
```json
{json.dumps(self.schema, indent=2)}
```

**EXTRACT THESE FIELDS:**
- Port Name: Full name and address of the customs port/ICD
- Port Code: 6-character code (e.g., INSNF6)
- SB No: Shipping Bill number
- SB Date: Date in DD-MMM-YY format
- IEC/Br: Importer Exporter Code with branch
- GSTIN/TYPE: GSTIN number with type designation
- CB CODE: Customs Broker Code
- TYPE: Type of Shipping Bill
- Nos: Document counts (INV, ITEM, CONT)
- PKG: Number of packages
- G.WT KGS: Gross weight in kilograms
- QR CODE: QR code data if present

Return ONLY valid JSON matching the schema."""


class Part1PromptTemplate(PromptTemplate):
    """Prompt for Part I - Shipping Bill Summary"""

    def build_prompt(self, context: Optional[Dict] = None) -> str:
        return f"""Extract data from PART I - SHIPPING BILL SUMMARY of a Shipping Bill.

**SCHEMA:**
```json
{json.dumps(self.schema, indent=2)}
```

**SECTION A - STATUS:**
Extract: mode, assess, exmn, jobbing, meis, dbk, rodtp, rosl, licence, deec/dfia, dfrc, re_exp, lut, port_of_loading, country_of_final_destination, state_of_origin, port_of_final_destination, port_of_discharge, country_of_discharge

**CRITICAL RULES FOR STATUS SECTION:**
**For RODTP-type documents:**
- Field 7: Extract as "rodtp" (Y/N value)
- Field 8: Extract as "licence" (Y/N value)
- Set "rosl" to null and "deec/dfia" to null

**For ROSL-type documents:**
- Field 7: Extract as "rosl" (Y/N value)
- Field 8: Extract as "deec/dfia" (Y/N value)
- Set "rodtp" to null and "licence" to null

**SECTION B - DECLARAN DETAILS:**
Extract exporter name & address, type, ad_code, rbi_waiver_no & date, cb_name, aeo, consignee name & address, gstin_type, forex_bank_ac_no, dbk_bank_ac_no, ifsc_no

**SECTION C - VALUE SUMMARY:**
Extract: fob_value, freight, insurance, discount, commission, deductions, packing_charges, duty, cess

**SECTION D - EXPORT PROMOTIONS:**
Extract: dbk_claim, igst_amt, cess_amt, igst_value, rodtep_amt, rosctl_amt

**SECTION E - MANIFEST DETAILS:**
Extract: mawb_no, mawb_date, hawb_no, hawb_date, noc, cin_no, cin_date, cin_site_id

**SECTION F - INVOICE SUMMARY:**
Extract array of invoices with: s_no, invoice_no, inv_amt, currency

**SECTION G - EQUIPMENT DETAILS:**
Extract: container, seal, date, s_no

**SECTION H - CHALLAN DETAILS:**
Extract array with: sr_no, challan_no, payment_date, amount

**SECTION I - ANNEX DETAILS:**
Extract: seal_type, nature_of_cargo, no_of_packets, no_of_containers, loose_packets, marks_and_numbers

**SECTION J - PROCESS DETAILS:**
Extract events array (event_number: "5", "7", or "9"; event: "Submission", "Assessment", "Examination", or "LEO"; date, time)
Also extract: leo_no, leo_date, brc_realisation_date

Return ONLY valid JSON matching the schema.

important : Dont extract any glossary or footnote information.
"""


class Part2PromptTemplate(PromptTemplate):
    """Prompt for Part II - Invoice Details"""

    def build_prompt(self, context: Optional[Dict] = None) -> str:
        return f"""Extract data from PART II - INVOICE DETAILS of a Shipping Bill.

**IMPORTANT: MULTIPLE INVOICES**
A Shipping Bill can have MULTIPLE invoices. Each invoice appears on a SEPARATE page in PART-II.
You MUST extract ALL invoices from all pages. Each invoice has its own sections A, B, C, and D.

**SCHEMA:**
```json
{json.dumps(self.schema, indent=2)}
```

**FOR EACH INVOICE, EXTRACT:**

**SECTION A - REFERENCE:**
Extract: s_no, invoice_no, invoice_date, po_no, po_date, loc_no, loc_date, contract_no, contract_date, ad_code, inv_term

**SECTION B - TRANSACTION PARTIES:**
Extract exporter (name, address), buyer (name, address, ACN, ABN if present), third_party (if applicable), buyer_aeo_status

**SECTION C - VALUATION DETAILS:**
Extract: invoice_value, invoice_currency, fob_value, fob_currency, freight, freight_currency, insurance, insurance_currency, discount, commission, deduction, packing_charges
Exchange rate as object: rate, from_currency, to_currency, conversion_string

**SECTION D - ITEM DETAILS:**
Extract array of items with: item_sno, hs_code (8 digits), description, quantity, uqc, rate, value_fc

**CRITICAL INSTRUCTIONS:**
1. Look for multiple pages with "PART - II - INVOICE DETAILS" header
2. Each page represents ONE invoice (check the S.No field in section A)
3. Extract ALL invoices - do not stop after the first one
4. Return an "invoices" array containing all invoice objects
5. Do NOT extract glossary or footnote information

Return ONLY valid JSON matching the schema with ALL invoices in the "invoices" array.
"""


class Part3PromptTemplate(PromptTemplate):
    """Prompt for Part III - Item Details"""

    def build_prompt(self, context: Optional[Dict] = None) -> str:
        return f"""Extract data from PART III - ITEM DETAILS of a Shipping Bill.

**SCHEMA:**
```json
{json.dumps(self.schema, indent=2)}
```

**EXTRACT ITEM TABLE:**
This is a table with 29 columns. Extract each row as an item with ALL these fields:

1. inv_sn - Invoice serial number
2. item_sn - Item serial number
3. hs_code - 8-digit HS code
4. description - Full item description
5. quantity - Quantity value
6. uqc - Unit quantity code
7. rate - Rate per unit (foreign currency)
8. value_fc - Value in foreign currency
9. fob_inr - FOB value in INR
10. pmv - Present Market Value
11. duty_amt - Duty amount
12. cess_rt - Cess rate
13. cess_amt - Cess amount
14. dbk_clmd - Drawback claimed (Y/N)
15. igst_stat - IGST status (LUT/PAID/BOND/EXEMPTED)
16. igst_value - IGST value
17. igst_amount - IGST amount
18. sch_cod - Scheme code
19. scheme_description - Scheme name
20. sqc_msr - Standard quantity measurement
21. sqc_uqc - Standard quantity unit
22. state_of_origin - Origin state
23. district_of_origin - Origin district
24. pt_abroad - Preferential treatment code
25. comp_cess - Compensatory cess
26. comp_cess_currency - Cess currency
27. end_use - End use code
28. fta_benefit_availed - FTA benefit (Y/N)
29. reward_benefit - Reward benefit (Yes/No)
30. third_party_item - Third party indicator (Y/N)

Return invoice_items array with all items. Include invoice_reference object if visible.

Return ONLY valid JSON matching the schema.

important : Dont extract any glossary or footnote information.
"""


class Part4PromptTemplate(PromptTemplate):
    """Prompt for Part IV - Export Scheme Details"""

    def build_prompt(self, context: Optional[Dict] = None) -> str:
        return f"""Extract data from PART IV - EXPORT SCHEME DETAILS of a Shipping Bill.

**CRITICAL INSTRUCTIONS:**
1. Part IV contains 14 sections (A through N) with multiple tables
2. Tables have numbered column headers (e.g., "1.INV SNO 2.ITEM SNO 3.DBK SNO...")
3. Extract each row of data carefully, matching values to the correct column numbers
4. Some sections may be empty - return empty arrays for those
5. Pay special attention to numeric values - do not mix up columns

**SCHEMA:**
```json
{json.dumps(self.schema, indent=2)}
```

**SECTION A - DRAWBACK & ROSL CLAIM:**
Extract array with: inv_sno, item_sno, dbk_sno, qty_wt, value, rate, dbk_amt, stalev, cenlev, rosctl_amt

**SECTION B - AA/DFIA LICENCE DETAILS:**
Extract array with: inv_sno, item_sno, licence_no, descn_export_item, exp_sno, exp_qty, uqc, fob_value, sion, descn_import_item, imp_sno, imp_qt, imp_uqc, indig_imp

**SECTION C - JOBBING DETAILS:**
Extract array with: be_no, be_date, port_code, descn_imported_goods, qty_imp, qty_used

**SECTION D - SINGLE WINDOW DECLARATION:**
Extract array with: inv_sn, itm_sn, info, qualifier, info_cd, info_text, info_msr, uqc

**SECTION E - SINGLE WINDOW DECLARATION - CONSTITUENTS:**
Extract array with: inv_sn, itm_sno, c_sno, name, code, percentage, yield_pct, ing

**SECTION F - SINGLE WINDOW DECLARATION - CONTROL:**
Extract array with: inv_sn, itm_sno, control_type, location, st_dt, end_dt, res_cd, res_text

**SECTION G - SUPPORTING DOCUMENTS:**
Extract array with: inv_sn, itm_sno, doc_typ_cd, icegate_id, irn, party_cd, issue_pla, iss_dt, exp_dt

**SECTION H - INVOICE DETAILS:**
Extract array with: sno, invoice_no, invoice_amount, currency

**SECTION I - CONTAINER DETAILS:**
Extract array with: sno, container, seal, date

**SECTION J - AR4 DETAILS:**
Extract array with: inv_sn, itm_sn, ar4_number, ar4_date, commissionerate, division, range

**SECTION K - THIRD PARTY DETAILS:**
Extract array with: inv_sn, itm_sn, iec, exporter_name, address, gstn_id_type

**SECTION L - MANUFACTURER/PRODUCER/GROWER DETAILS:**
Extract array with: inv_sn, itm_sn, type, manufact_cd, source_state, trans_cy, address

**SECTION M - RODTEP DETAILS:**
Extract array with: inv_sn, itm_sn, quantity, uqc, no_of_units, value

**SECTION N - REEXPORT DETAILS:**
Extract array with: inv_s, itm_sn, be_site_id, be_number, be_date, be_inv_sno, be_item_s, be_qty, be_uqc

Return ONLY valid JSON matching the schema.

important : Dont extract any glossary or footnote information.
"""


class Part5PromptTemplate(PromptTemplate):
    """Prompt for Part V - Declarations"""

    def build_prompt(self, context: Optional[Dict] = None) -> str:
        return f"""Extract data from PART V - DECLARATIONS of a Shipping Bill.

**SCHEMA:**
```json
{json.dumps(self.schema, indent=2)}
```

**SECTION A - DECLARATION STATEMENT:**
Extract the full declaration text from the declaration statement area. This is typically a large text block containing legal declarations about the accuracy of information provided.

Extract:
- declaration_text: Full text of the declaration
- standard_declarations: Array of individual declaration points if they are itemized

**SECTION B - AUTHORIZED SIGNATORY:**
Extract:
- date: Date of signing (DD-MMM-YY format)
- place: Place where signed (city name)
- authorized_signatory: Object with name, designation, signature, signatory_type
- cha_name: CHA/Customs Broker code
- cha_details: CHA firm details if present (cha_code, cha_pan, cha_gstin, cha_firm_name, cha_address)

Return ONLY valid JSON matching the schema.

important : Dont extract any glossary or footnote information.
"""


class ShippingBillPromptBuilder(BasePromptBuilder):
    """Shipping Bill specific prompt builder for Parts 0, I-V"""

    # Template map for SB parts
    TEMPLATE_MAP = {
        'part-0': Part0PromptTemplate,
        'part-1': Part1PromptTemplate,
        'part-2': Part2PromptTemplate,
        'part-3': Part3PromptTemplate,
        'part-4': Part4PromptTemplate,
        'part-5': Part5PromptTemplate,
    }


# For convenience
def build_sb_prompt(part_name: str, schema_path: str, context: Optional[Dict] = None) -> str:
    """
    Convenience function to build Shipping Bill prompts

    Args:
        part_name: Part identifier (e.g., 'part-1')
        schema_path: Path to schema JSON file
        context: Optional context dict

    Returns:
        Extraction prompt string
    """
    return ShippingBillPromptBuilder.build_prompt(part_name, schema_path, context)
