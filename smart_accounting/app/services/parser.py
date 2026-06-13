import os
import re
from datetime import datetime
from typing import List, Dict, Any, Tuple
import pandas as pd
import pdfplumber

class ParserError(Exception):
    """Base exception for parsing errors."""
    pass

class UnsupportedFileError(ParserError):
    """Raised when the file format or type is unsupported."""
    pass

def normalize_date(date_val: Any) -> str:
    """Helper to convert various date formats to YYYY-MM-DD."""
    if pd.isna(date_val) or not date_val:
        return ""
    
    date_str = str(date_val).strip().split('\n')[0].strip()
    
    # Common format patterns
    formats = [
        "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", 
        "%d/%m/%y", "%d-%m-%y", "%d %b %Y", "%d %B %Y",
        "%d-%b-%Y", "%d-%B-%Y", "%Y/%m/%d"
    ]
    
    # Try parsing directly
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
            
    # Try using pandas parser as a fallback
    try:
        parsed_dt = pd.to_datetime(date_str, errors='raise')
        return parsed_dt.strftime("%Y-%m-%d")
    except:
        pass
        
    return date_str

def normalize_amount(amount_val: Any) -> float:
    """Helper to convert currency string or numeric values to absolute float."""
    if pd.isna(amount_val) or amount_val is None:
        return 0.0
        
    if isinstance(amount_val, (int, float)):
        return float(abs(amount_val))
        
    val_str = str(amount_val).strip().replace("\n", "").replace(",", "")
    
    # Check for parentheses: (1,234.56) -> negative representation
    if val_str.startswith("(") and val_str.endswith(")"):
        val_str = val_str[1:-1]
        
    # Remove currency abbreviations like AED, USD, etc. and non-numeric chars
    val_str = re.sub(r"[^\d\.\-]", "", val_str)
    
    try:
        amount = float(val_str)
        return float(abs(amount))
    except ValueError:
        return 0.0

VALID_CURRENCY_CODES = {
    "AED", "AFN", "ALL", "AMD", "ANG", "AOA", "ARS", "AUD", "AWG", "AZN", "BAM", "BBD", "BDT", "BGN", "BHD", "BIF",
    "BMD", "BND", "BOB", "BRL", "BSD", "BTN", "BWP", "BYN", "BZD", "CAD", "CDF", "CHF", "CLP", "CNY", "COP", "CRC",
    "CUP", "CVE", "CZK", "DJF", "DKK", "DOP", "DZD", "EGP", "ERN", "ETB", "EUR", "FJD", "FKP", "GBP", "GEL", "GHS",
    "GIP", "GMD", "GNF", "GTQ", "GYD", "HKD", "HNL", "HRK", "HTG", "HUF", "IDR", "ILS", "INR", "IQD", "IRR", "ISK",
    "JMD", "JOD", "JPY", "KES", "KGS", "KHR", "KMF", "KPW", "KRW", "KWD", "KYD", "KZT", "LAK", "LBP", "LKR", "LRD",
    "LSL", "LYD", "MAD", "MDL", "MGA", "MKD", "MMK", "MNT", "MOP", "MRU", "MUR", "MVR", "MWK", "MXN", "MYR", "MZN",
    "NAD", "NGN", "NIO", "NOK", "NPR", "NZD", "OMR", "PAB", "PEN", "PGK", "PHP", "PKR", "PLN", "PYG", "QAR", "RON",
    "RSD", "RUB", "RWF", "SAR", "SBD", "SCR", "SDG", "SEK", "SGD", "SHP", "SLL", "SOS", "SRD", "SSP", "STN", "SVC",
    "SYP", "SZL", "THB", "TJS", "TMT", "TND", "TOP", "TRY", "TTD", "TWD", "TZS", "UAH", "UGX", "USD", "UYU", "UZS",
    "VES", "VND", "VUV", "WST", "XAF", "XCD", "XOF", "XPF", "YER", "ZAR", "ZMW", "ZWL"
}

def detect_currency_from_file(file_path: str, default_currency: str = "AED") -> str:
    """
    Attempts to auto-detect the currency of the financial statement file.
    Checks filename keywords first, then searches the file's text content for currency codes and symbols.
    """
    filename_lower = os.path.basename(file_path).lower()
    
    # 1. Check filename for common currency codes
    for ccy in ["usd", "aed", "eur", "gbp", "inr", "sar", "sgd", "cad", "aud"]:
        if ccy in filename_lower:
            return ccy.upper()
            
    # Extract text content
    text_content = ""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        try:
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages[:3]: # Scan first 3 pages
                    text_content += (page.extract_text() or "") + "\n"
        except Exception:
            pass
    elif ext in [".xlsx", ".xls"]:
        try:
            df = pd.read_excel(file_path, nrows=100)
            text_content = df.to_string()
        except Exception:
            pass
            
    if not text_content:
        return default_currency
        
    text_lower = text_content.lower()
    
    # 2. Look for pattern "currency: XXX" or "currency code: XXX" or "ccy: XXX"
    matches = re.findall(r"(?:currency|curr|ccy|valuta)\s*[:\-\s\.]+\s*([a-zA-Z]{3})", text_lower)
    if matches:
        for match in matches:
            val = match.upper()
            if val in VALID_CURRENCY_CODES:
                return val

    # 3. Check for specific symbols or unique words
    if "₹" in text_content or "rs." in text_lower or "rupee" in text_lower or "inr" in text_lower:
        return "INR"
    if "€" in text_content or "euro" in text_lower or "eur" in text_lower:
        return "EUR"
    if "£" in text_content or "pound" in text_lower or "sterling" in text_lower or "gbp" in text_lower:
        return "GBP"
    if "dhs" in text_lower or "dirham" in text_lower or "aed" in text_lower:
        return "AED"
    if "us$" in text_lower or "dollar" in text_lower or "usd" in text_lower:
        return "USD"
    if "sar" in text_lower or "riyal" in text_lower:
        return "SAR"
    if "sgd" in text_lower:
        return "SGD"
    if "cad" in text_lower:
        return "CAD"
    if "aud" in text_lower:
        return "AUD"

    # 4. Fallback: Search for any valid 3-letter currency code in the text
    # Prioritize finding uppercase matches because currency codes in files are usually capitalized (e.g. USD, EUR)
    for code in VALID_CURRENCY_CODES:
        if re.search(r"\b" + code + r"\b", text_content):
            return code
            
    # Try lowercase word boundaries as a final resort
    for code in VALID_CURRENCY_CODES:
        if re.search(r"\b" + code.lower() + r"\b", text_lower):
            return code
            
    return default_currency


def detect_file_type(file_path: str) -> Tuple[str, str]:
    """
    Detects the transaction source and format.
    Returns: Tuple[format_type, source_type]
             e.g., ("pdf", "wio"), ("excel", "petty_cash")
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
        
    ext = os.path.splitext(file_path)[1].lower()
    filename_lower = os.path.basename(file_path).lower()
    
    if ext == ".pdf":
        try:
            with pdfplumber.open(file_path) as pdf:
                if not pdf.pages:
                    raise ParserError("PDF file is empty")
                
                # Check first two pages for keywords
                text_sample = ""
                for page in pdf.pages[:2]:
                    text_sample += (page.extract_text() or "") + "\n"
                
                text_lower = text_sample.lower()
                
                if "wio" in text_lower or "wio" in filename_lower:
                    return "pdf", "wio"
                elif "mashreq" in text_lower or "mashreq" in filename_lower:
                    return "pdf", "mashreq"
                elif "scbl" in text_lower or "standard chartered" in text_lower or "seenivasan" in text_lower or "ebrcpt" in filename_lower:
                    return "pdf", "standard_chartered"
                else:
                    return "pdf", "unknown"
        except Exception as e:
            if isinstance(e, ParserError):
                raise
            raise ParserError(f"Failed to open PDF file: {e}")
            
    elif ext in [".xlsx", ".xls"]:
        try:
            # Check sheet names first
            try:
                xl = pd.ExcelFile(file_path)
                sheet_names = [s.lower() for s in xl.sheet_names]
            except Exception as e:
                raise ParserError(f"Failed to read sheet names from Excel: {e}")
                
            # Read first few lines of the first sheet to check column headers
            df = pd.read_excel(file_path, nrows=5)
            headers = [str(col).lower().strip() for col in df.columns]
            headers_str = " ".join(headers)
            
            # File name or sheet name heuristics first
            if "network" in filename_lower or "ni_statement" in filename_lower:
                return "excel", "network_international"
            elif "nomod" in filename_lower:
                return "excel", "nomod"
            elif "petty" in filename_lower or "petty_cash" in filename_lower or "petty cash" in sheet_names:
                return "excel", "petty_cash"
            elif "purchase" in filename_lower or "purchases" in sheet_names:
                return "excel", "purchases"
            elif "expense" in filename_lower or "expenses" in sheet_names:
                return "excel", "expenses"
            elif "ledger" in filename_lower or "general_ledger" in filename_lower or "general ledger" in sheet_names:
                return "excel", "general_ledger"
                
            # Column-based fallback heuristics
            if "merchant id" in headers_str or "terminal id" in headers_str or "card type" in headers_str:
                return "excel", "network_international"
            elif "payout id" in headers_str or ("customer" in headers_str and "fee" in headers_str and "net" in headers_str):
                return "excel", "nomod"
            elif "particulars" in headers_str or "voucher" in headers_str or ("receipt" in headers_str and "payment" in headers_str):
                return "excel", "petty_cash"
            elif "supplier" in headers_str or "invoice number" in headers_str:
                return "excel", "purchases"
            elif "category" in headers_str and ("merchant" in headers_str or "merchant name" in headers_str):
                return "excel", "expenses"
            elif "glid" in headers_str or ("debit" in headers_str and "credit" in headers_str and ("accountname" in headers_str or "account name" in headers_str)):
                return "excel", "general_ledger"
            else:
                return "excel", "unknown"
        except Exception as e:
            if isinstance(e, ParserError):
                raise
            raise ParserError(f"Failed to open Excel file: {e}")
    else:
        raise UnsupportedFileError(f"File extension {ext} is not supported. Only PDF and Excel are allowed.")


class WioPDFParser:
    """Parser for Wio Bank PDF Statements."""
    def parse(self, file_path: str) -> List[Dict[str, Any]]:
        rows = []
        source_file = os.path.basename(file_path)
        
        with pdfplumber.open(file_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                # Try table extraction first
                tables = page.extract_tables()
                if tables:
                    for table in tables:
                        for row in table:
                            if not row or len(row) < 3:
                                continue
                            
                            # Clean the cells
                            cleaned_row = [str(cell).strip() if cell else "" for cell in row]
                            
                            # Skip headers: check if row looks like WIO headers
                            row_str = " ".join(cleaned_row).lower()
                            if "transaction date" in row_str or "booking date" in row_str or "balance" in row_str:
                                continue
                            
                            # Heuristic for Wio: Usually Transaction Date is at index 0
                            # WIO statement columns: Date | Description | Amount | Type | Balance
                            # Let's check if index 0 has a parseable date
                            parsed_date = normalize_date(cleaned_row[0])
                            if not parsed_date:
                                continue
                                
                            # Description is index 1
                            desc = cleaned_row[1] if len(cleaned_row) > 1 else ""
                            if not desc or desc.lower() == "description":
                                continue
                                
                            # Amount is index 2, Type index 3 (or standard credit/debit sign)
                            amount_val = 0.0
                            t_type = "unknown"
                            
                            if len(cleaned_row) > 3:
                                amount_val = normalize_amount(cleaned_row[2])
                                type_indicator = cleaned_row[3].lower()
                                if "debit" in type_indicator or "out" in type_indicator or "-" in type_indicator:
                                    t_type = "debit"
                                elif "credit" in type_indicator or "in" in type_indicator or "+" in type_indicator:
                                    t_type = "credit"
                            elif len(cleaned_row) > 2:
                                # Sign based amount detection
                                raw_amt = cleaned_row[2]
                                amount_val = normalize_amount(raw_amt)
                                if "-" in raw_amt:
                                    t_type = "debit"
                                else:
                                    t_type = "credit"
                                    
                            if amount_val > 0:
                                rows.append({
                                    "date": parsed_date,
                                    "description": desc,
                                    "amount": amount_val,
                                    "type": t_type,
                                    "source_file": source_file
                                })
                else:
                    # Fallback text extraction line-by-line if table fails
                    text = page.extract_text() or ""
                    for line in text.split("\n"):
                        # Sample line regex check
                        # Looks for Date (DD-MM-YYYY or similar) + text + amount
                        # Example: 10/12/2025 Opening Balance 1000.00
                        match = re.search(r"(\d{2}[/\-]\d{2}[/\-]\d{4})\s+(.+?)\s+(-?[\d,]+\.\d{2})", line)
                        if match:
                            dt_str, desc_str, amt_str = match.groups()
                            parsed_date = normalize_date(dt_str)
                            amount_val = normalize_amount(amt_str)
                            t_type = "debit" if "-" in amt_str else "credit"
                            rows.append({
                                "date": parsed_date,
                                "description": desc_str.strip(),
                                "amount": amount_val,
                                "type": t_type,
                                "source_file": source_file
                            })
                            
        return rows


class MashreqPDFParser:
    """Parser for Mashreq Bank PDF Statements."""
    def parse(self, file_path: str) -> List[Dict[str, Any]]:
        rows = []
        source_file = os.path.basename(file_path)
        
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        if not row or len(row) < 4:
                            continue
                        
                        cleaned_row = [str(cell).strip() if cell else "" for cell in row]
                        row_str = " ".join(cleaned_row).lower()
                        
                        # Skip header rows
                        if "value date" in row_str or "particulars" in row_str or "running balance" in row_str:
                            continue
                        
                        # Mashreq columns: Txn Date | Value Date | Description | Debit | Credit | Balance
                        # Columns count is usually 6. Let's extract based on column positions.
                        parsed_date = normalize_date(cleaned_row[0])
                        if not parsed_date:
                            # Let's try value date at index 1
                            parsed_date = normalize_date(cleaned_row[1]) if len(cleaned_row) > 1 else ""
                            if not parsed_date:
                                continue
                                
                        desc = cleaned_row[2] if len(cleaned_row) > 2 else ""
                        if not desc:
                            continue
                            
                        debit_val = 0.0
                        credit_val = 0.0
                        
                        if len(cleaned_row) >= 5:
                            debit_val = normalize_amount(cleaned_row[3])
                            credit_val = normalize_amount(cleaned_row[4])
                        elif len(cleaned_row) == 4:
                            # If only 4 columns, maybe: Date, Description, Amount, Type
                            amount_val = normalize_amount(cleaned_row[2])
                            type_indicator = cleaned_row[3].lower()
                            if "dr" in type_indicator or "debit" in type_indicator or "-" in type_indicator:
                                debit_val = amount_val
                            else:
                                credit_val = amount_val
                                
                        if debit_val > 0:
                            rows.append({
                                "date": parsed_date,
                                "description": desc,
                                "amount": debit_val,
                                "type": "debit",
                                "source_file": source_file
                            })
                        elif credit_val > 0:
                            rows.append({
                                "date": parsed_date,
                                "description": desc,
                                "amount": credit_val,
                                "type": "credit",
                                "source_file": source_file
                            })
        return rows


class NetworkInternationalExcelParser:
    """Parser for Network International Merchant Statements."""
    def parse(self, file_path: str) -> List[Dict[str, Any]]:
        rows = []
        source_file = os.path.basename(file_path)
        
        df = pd.read_excel(file_path)
        # Standardize column header strings
        df.columns = [str(col).strip().lower() for col in df.columns]
        
        # Look for date column (e.g., "transaction date", "date", "txn_date")
        date_col = next((col for col in df.columns if "date" in col), None)
        # Look for description column (e.g., "description", "merchant", "details")
        desc_col = next((col for col in df.columns if "desc" in col or "merchant" in col or "details" in col), None)
        
        # Look for amount column: Priority is net amount, then gross/total/amount
        amount_col = next((col for col in df.columns if "net" in col), None) or next((col for col in df.columns if "amount" in col or "total" in col), None)
        
        if not date_col or not amount_col:
            # Fallback to column index mapping
            if len(df.columns) >= 3:
                date_col = df.columns[0]
                desc_col = df.columns[1]
                amount_col = df.columns[2]
            else:
                raise ParserError("Network International spreadsheet does not have required columns")
                
        for idx, r in df.iterrows():
            date_val = r[date_col]
            parsed_date = normalize_date(date_val)
            if not parsed_date:
                continue
                
            desc_val = r[desc_col] if desc_col else "Network International Payout"
            desc = str(desc_val).strip() if not pd.isna(desc_val) else "Network International Payout"
            
            amount_val = normalize_amount(r[amount_col])
            if amount_val > 0:
                rows.append({
                    "date": parsed_date,
                    "description": desc,
                    "amount": amount_val,
                    "type": "credit",  # Network International payouts are deposits/credits
                    "source_file": source_file
                })
        return rows


class NomodExcelParser:
    """Parser for Nomod Statements."""
    def parse(self, file_path: str) -> List[Dict[str, Any]]:
        rows = []
        source_file = os.path.basename(file_path)
        
        df = pd.read_excel(file_path)
        df.columns = [str(col).strip().lower() for col in df.columns]
        
        date_col = next((col for col in df.columns if "created" in col or "date" in col), None)
        desc_col = next((col for col in df.columns if "customer" in col or "desc" in col or "reference" in col), None)
        
        # Priority is net amount, then gross/total/amount
        amount_col = next((col for col in df.columns if "net" in col), None) or next((col for col in df.columns if "amount" in col or "total" in col), None)
        
        if not date_col or not amount_col:
            if len(df.columns) >= 3:
                date_col = df.columns[0]
                desc_col = df.columns[1]
                amount_col = df.columns[2]
            else:
                raise ParserError("Nomod spreadsheet does not have required columns")
                
        for idx, r in df.iterrows():
            date_val = r[date_col]
            parsed_date = normalize_date(date_val)
            if not parsed_date:
                continue
                
            desc_val = r[desc_col] if desc_col else "Nomod Deposit"
            desc = str(desc_val).strip() if not pd.isna(desc_val) else "Nomod Deposit"
            
            amount_val = normalize_amount(r[amount_col])
            if amount_val > 0:
                rows.append({
                    "date": parsed_date,
                    "description": desc,
                    "amount": amount_val,
                    "type": "credit",  # Nomod payments are deposits/credits
                    "source_file": source_file
                })
        return rows


class PurchasesExcelParser:
    """Parser for Purchases Sheets."""
    def parse(self, file_path: str) -> List[Dict[str, Any]]:
        rows = []
        source_file = os.path.basename(file_path)
        
        df = pd.read_excel(file_path)
        df.columns = [str(col).strip().lower() for col in df.columns]
        
        date_col = next((col for col in df.columns if "date" in col), None)
        desc_col = next((col for col in df.columns if "supplier" in col or "vendor" in col or "desc" in col), None)
        amount_col = next((col for col in df.columns if "amount" in col or "total" in col or "net" in col), None)
        
        if not date_col or not amount_col:
            if len(df.columns) >= 3:
                date_col = df.columns[0]
                desc_col = df.columns[1]
                amount_col = df.columns[2]
            else:
                raise ParserError("Purchases spreadsheet does not have required columns")
                
        for idx, r in df.iterrows():
            date_val = r[date_col]
            parsed_date = normalize_date(date_val)
            if not parsed_date:
                continue
                
            desc_val = r[desc_col] if desc_col else "Supplier Purchase"
            desc = str(desc_val).strip() if not pd.isna(desc_val) else "Supplier Purchase"
            
            amount_val = normalize_amount(r[amount_col])
            if amount_val > 0:
                rows.append({
                    "date": parsed_date,
                    "description": f"Purchase: {desc}",
                    "amount": amount_val,
                    "type": "debit",  # Purchases are outgoing payments/debits
                    "source_file": source_file
                })
        return rows


class ExpensesExcelParser:
    """Parser for Expenses Sheets."""
    def parse(self, file_path: str) -> List[Dict[str, Any]]:
        rows = []
        source_file = os.path.basename(file_path)
        
        df = pd.read_excel(file_path)
        df.columns = [str(col).strip().lower() for col in df.columns]
        
        date_col = next((col for col in df.columns if "date" in col), None)
        desc_col = next((col for col in df.columns if "category" in col or "merchant" in col or "desc" in col), None)
        amount_col = next((col for col in df.columns if "amount" in col or "total" in col), None)
        
        if not date_col or not amount_col:
            if len(df.columns) >= 3:
                date_col = df.columns[0]
                desc_col = df.columns[1]
                amount_col = df.columns[2]
            else:
                raise ParserError("Expenses spreadsheet does not have required columns")
                
        for idx, r in df.iterrows():
            date_val = r[date_col]
            parsed_date = normalize_date(date_val)
            if not parsed_date:
                continue
                
            desc_val = r[desc_col] if desc_col else "Expense Payment"
            desc = str(desc_val).strip() if not pd.isna(desc_val) else "Expense Payment"
            
            amount_val = normalize_amount(r[amount_col])
            if amount_val > 0:
                rows.append({
                    "date": parsed_date,
                    "description": f"Expense: {desc}",
                    "amount": amount_val,
                    "type": "debit",  # Expenses are outgoing payments/debits
                    "source_file": source_file
                })
        return rows


class PettyCashExcelParser:
    """Parser for Petty Cash Excel Sheets."""
    def parse(self, file_path: str) -> List[Dict[str, Any]]:
        rows = []
        source_file = os.path.basename(file_path)
        
        df = pd.read_excel(file_path)
        df.columns = [str(col).strip().lower() for col in df.columns]
        
        date_col = next((col for col in df.columns if "date" in col), None)
        desc_col = next((col for col in df.columns if "particulars" in col or "desc" in col or "description" in col), None)
        receipt_col = next((col for col in df.columns if "receipt" in col or "credit" in col or "in" in col), None)
        payment_col = next((col for col in df.columns if "payment" in col or "debit" in col or "out" in col or "paid" in col), None)
        
        if not date_col or not desc_col:
            if len(df.columns) >= 4:
                date_col = df.columns[0]
                desc_col = df.columns[1]
                receipt_col = df.columns[2]
                payment_col = df.columns[3]
            else:
                raise ParserError("Petty Cash spreadsheet does not have required columns")
                
        for idx, r in df.iterrows():
            date_val = r[date_col]
            parsed_date = normalize_date(date_val)
            if not parsed_date:
                continue
                
            desc_val = r[desc_col]
            desc = str(desc_val).strip() if not pd.isna(desc_val) else "Petty Cash Entry"
            
            # Skip overall sum/header lines
            if "total" in desc.lower() or "opening balance" in desc.lower():
                continue
                
            receipt_val = normalize_amount(r[receipt_col]) if receipt_col and receipt_col in r else 0.0
            payment_val = normalize_amount(r[payment_col]) if payment_col and payment_col in r else 0.0
            
            if receipt_val > 0:
                rows.append({
                    "date": parsed_date,
                    "description": f"Petty Cash: {desc}",
                    "amount": receipt_val,
                    "type": "credit",
                    "source_file": source_file
                })
            elif payment_val > 0:
                rows.append({
                    "date": parsed_date,
                    "description": f"Petty Cash: {desc}",
                    "amount": payment_val,
                    "type": "debit",
                    "source_file": source_file
                })
        return rows


class GeneralLedgerExcelParser:
    """Parser for General Ledger Excel Sheets."""
    def parse(self, file_path: str) -> List[Dict[str, Any]]:
        rows = []
        source_file = os.path.basename(file_path)
        
        df = pd.read_excel(file_path)
        df.columns = [str(col).strip().lower() for col in df.columns]
        
        # Look for date column: "txndate" or "date"
        date_col = next((col for col in df.columns if "date" in col), None)
        # Look for description column: "description" or "desc"
        desc_col = next((col for col in df.columns if "desc" in col), None)
        # Look for AccountName column: "accountname" or "account_name" or "account name" or col == "account"
        account_name_col = next((col for col in df.columns if "accountname" in col or "account_name" in col or "account name" in col or col == "account"), None)
        # Look for Debit column: "debit" or "dr"
        debit_col = next((col for col in df.columns if "debit" in col or col == "dr"), None)
        # Look for Credit column: "credit" or "cr"
        credit_col = next((col for col in df.columns if "credit" in col or col == "cr"), None)
        
        if not date_col or (not debit_col and not credit_col):
            raise ParserError("General Ledger spreadsheet does not have required columns (Date, Debit/Credit)")
            
        for idx, r in df.iterrows():
            date_val = r[date_col]
            parsed_date = normalize_date(date_val)
            if not parsed_date:
                continue
                
            desc_val = r[desc_col] if desc_col else ""
            desc = str(desc_val).strip() if not pd.isna(desc_val) else ""
            
            acc_name_val = r[account_name_col] if account_name_col else ""
            acc_name = str(acc_name_val).strip() if not pd.isna(acc_name_val) else ""
            
            if acc_name and desc:
                full_desc = f"{acc_name} - {desc}"
            elif acc_name:
                full_desc = acc_name
            else:
                full_desc = desc or "General Ledger Entry"
                
            debit_val = normalize_amount(r[debit_col]) if debit_col and debit_col in r else 0.0
            credit_val = normalize_amount(r[credit_col]) if credit_col and credit_col in r else 0.0
            
            if debit_val > 0:
                rows.append({
                    "date": parsed_date,
                    "description": full_desc,
                    "amount": debit_val,
                    "type": "debit",
                    "source_file": source_file
                })
            elif credit_val > 0:
                rows.append({
                    "date": parsed_date,
                    "description": full_desc,
                    "amount": credit_val,
                    "type": "credit",
                    "source_file": source_file
                })
        return rows


class StandardCharteredPDFParser:
    """Parser for Standard Chartered Bank PDF Statements."""
    def parse(self, file_path: str) -> List[Dict[str, Any]]:
        rows = []
        source_file = os.path.basename(file_path)
        running_balance = None
        current_date = ""
        
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                for line in text.split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                        
                    line_lower = line.lower()
                    
                    # Handle Balance Forward line
                    if "balance forward" in line_lower:
                        match_bal = re.search(r"([\d,]+\.\d{2})\s*$", line)
                        if match_bal:
                            running_balance = normalize_amount(match_bal.group(1))
                        continue
                        
                    # Skip header/footer junk
                    skip_keywords = [
                        "page ", "account statement", "branch :", "statement date :",
                        "currency :", "account type :", "account no. :", "nominee registered :",
                        "branch address:", "micr:", "ifsc:", "phone no.:", "value date", 
                        "date description", "cheque deposit", "withdrawal balance",
                        "bank deposits are covered", "please register the nomination", 
                        "report irregularities", "reward points statement", "scheme opening", 
                        "reward plus", "total ", "dda "
                    ]
                    if any(kw in line_lower for kw in skip_keywords) or "seenivasan" in line_lower:
                        continue
                        
                    # Check if line matches a transaction pattern
                    match_tx = re.search(r"([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s*$", line)
                    if match_tx:
                        amount_str, balance_str = match_tx.groups()
                        amount = normalize_amount(amount_str)
                        balance = normalize_amount(balance_str)
                        
                        desc = line[:match_tx.start()].strip()
                        
                        # Check for leading dates: e.g., 17 Jun 19
                        match_date = re.match(r"^(\d{1,2}\s+[A-Za-z]{3}\s+\d{2})(?:\s+\d{1,2}\s+[A-Za-z]{3}\s+\d{2})?\s*(.*)", desc)
                        if match_date:
                            date_str, rest = match_date.groups()
                            current_date = normalize_date(date_str)
                            desc = rest.strip()
                            
                        t_type = "debit"
                        if running_balance is not None:
                            if balance > running_balance:
                                t_type = "credit"
                                
                        running_balance = balance
                        
                        rows.append({
                            "date": current_date,
                            "description": desc,
                            "amount": amount,
                            "type": t_type,
                            "source_file": source_file
                        })
                    else:
                        # Append description details to last row
                        if rows:
                            rows[-1]["description"] += " " + line
                            
        return rows


AI_PARSER_SYSTEM_PROMPT = """
You are a financial parsing assistant. Your task is to analyze raw text/CSV extracted from a financial document (bank statement, expense spreadsheet, payout report) and extract all transaction rows.

For each transaction, you must extract:
- "date": Date in "YYYY-MM-DD" format.
- "description": Description of the transaction.
- "amount": Absolute numeric amount as a float.
- "type": "debit" (if money went out/payment/withdrawal/fee) or "credit" (if money came in/deposit/receipt/payout).

CRITICAL JSON FORMATTING RULES:
1. The response must be a single, valid JSON array of objects.
2. Absolutely no markdown blocks (like ```json), conversational intro, or outro text.
3. Ensure all double quotes (") inside text values (such as descriptions) are properly escaped as \\" (e.g., "description": "ATM WITHDRAWAL \\"SELF-SWITCH\\"") so the JSON remains syntactically valid.
4. Escape all backslashes (\\) inside text values as \\\\.
5. Do not include any comments in the JSON.
6. Return the complete list of transactions. Do not truncate the output.

Example response:
[
  {"date": "2026-06-10", "description": "AWS Cloud Hosting", "amount": 450.00, "type": "debit"},
  {"date": "2026-06-11", "description": "Client payout NOMOD", "amount": 1470.00, "type": "credit"}
]
"""

def parse_document_with_ai(file_path: str) -> List[Dict[str, Any]]:
    """
    Extracts text/CSV content from PDF/Excel, chunks it to handle arbitrary document size,
    and calls Claude to parse each chunk. Merges and returns the results.
    """
    import json
    from anthropic import Anthropic
    from smart_accounting.app.config import settings

    ext = os.path.splitext(file_path)[1].lower()
    chunks = []
    
    if ext == ".pdf":
        try:
            pages_text = []
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    text = (page.extract_text() or "").strip()
                    if text:
                        pages_text.append(text)
            
            # Group pages into chunks of 2 pages
            page_group_size = 2
            for i in range(0, len(pages_text), page_group_size):
                chunk_text = "\n\n--- PAGE BREAK ---\n\n".join(pages_text[i : i + page_group_size])
                chunks.append(chunk_text)
        except Exception as e:
            raise ParserError(f"Failed to extract text from PDF: {e}")
            
    elif ext in [".xlsx", ".xls"]:
        try:
            xls = pd.ExcelFile(file_path)
            all_lines = []
            header_line = ""
            for sheet_name in xls.sheet_names:
                df = pd.read_excel(xls, sheet_name=sheet_name)
                csv_content = df.to_csv(index=False)
                lines = [l.strip() for l in csv_content.splitlines() if l.strip()]
                if lines:
                    if not header_line:
                        header_line = lines[0]
                        all_lines.extend(lines[1:])
                    else:
                        all_lines.extend(lines[1:])
            
            # Chunk CSV lines (e.g. 80 lines per chunk)
            csv_chunk_size = 80
            for i in range(0, len(all_lines), csv_chunk_size):
                chunk_lines = [header_line] + all_lines[i : i + csv_chunk_size]
                chunks.append("\n".join(chunk_lines))
        except Exception as e:
            raise ParserError(f"Failed to extract CSV from Excel: {e}")
    else:
        raise UnsupportedFileError(f"Unsupported file type: {ext}")

    # Process chunks if there are none (empty file)
    if not chunks:
        return []

    # Support mock parser fallback for offline testing
    if not settings.ANTHROPIC_API_KEY or settings.ANTHROPIC_API_KEY == "mock-key-for-testing":
        source_file = os.path.basename(file_path)
        return [{
            "date": datetime.now().strftime("%Y-%m-%d"),
            "description": f"Mock AI Parsed: Transaction from {source_file}",
            "amount": 100.0,
            "type": "debit",
            "source_file": source_file
        }]

    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    all_parsed_rows = []
    source_file = os.path.basename(file_path)

    for idx, chunk_content in enumerate(chunks):
        if not chunk_content.strip():
            continue
            
        try:
            # Call Claude for this chunk
            message = client.messages.create(
                model=settings.CLAUDE_MODEL,
                max_tokens=8000,
                temperature=0.0,
                system=AI_PARSER_SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": f"Extract all transactions from this document chunk (Chunk {idx+1}/{len(chunks)}):\n\n{chunk_content}"
                    }
                ]
            )
            response_text = message.content[0].text.strip()
            
            # Robust JSON extraction: extract the outermost JSON array block [ ... ]
            start_idx = response_text.find('[')
            end_idx = response_text.rfind(']')
            if start_idx != -1 and end_idx != -1:
                json_str = response_text[start_idx:end_idx+1]
            else:
                json_str = response_text
                
            # Clean up trailing commas
            json_str = re.sub(r',\s*\]', ']', json_str)
            json_str = re.sub(r',\s*\}', '}', json_str)
            
            chunk_rows = json.loads(json_str)
            if isinstance(chunk_rows, list):
                for row in chunk_rows:
                    row["source_file"] = source_file
                    row["date"] = normalize_date(row.get("date"))
                    row["amount"] = normalize_amount(row.get("amount"))
                    all_parsed_rows.append(row)
            else:
                print(f"Warning: Chunk {idx+1} did not return a JSON list, skipping.", flush=True)
        except Exception as e:
            raise ParserError(f"AI statement parsing failed on chunk {idx+1}/{len(chunks)}: {e}")

    return all_parsed_rows


def parse_document(file_path: str, default_currency: str = "AED") -> List[Dict[str, Any]]:
    """
    Main orchestration function to detect the file layout and run the appropriate parser.
    If layout parser fails, falls back to AI-based document parsing.
    """
    detected_currency = detect_currency_from_file(file_path, default_currency)
    
    try:
        fmt, source = detect_file_type(file_path)
    except Exception as e:
        print(f"File layout detection failed. Falling back to AI parser: {e}", flush=True)
        rows = parse_document_with_ai(file_path)
        for r in rows:
            r["currency"] = detected_currency
        return rows
    
    rows = []
    try:
        if fmt == "pdf":
            if source == "wio":
                rows = WioPDFParser().parse(file_path)
            elif source == "mashreq":
                rows = MashreqPDFParser().parse(file_path)
            elif source == "standard_chartered":
                rows = StandardCharteredPDFParser().parse(file_path)
            else:
                raise UnsupportedFileError(f"Unknown PDF format: {source}")
        elif fmt == "excel":
            if source == "network_international":
                rows = NetworkInternationalExcelParser().parse(file_path)
            elif source == "nomod":
                rows = NomodExcelParser().parse(file_path)
            elif source == "purchases":
                rows = PurchasesExcelParser().parse(file_path)
            elif source == "expenses":
                rows = ExpensesExcelParser().parse(file_path)
            elif source == "petty_cash":
                rows = PettyCashExcelParser().parse(file_path)
            elif source == "general_ledger":
                rows = GeneralLedgerExcelParser().parse(file_path)
            else:
                raise UnsupportedFileError(f"Unknown Excel layout: {source}")
    except Exception as pe:
        print(f"Standard layout parser failed. Falling back to AI parser: {pe}", flush=True)
        rows = parse_document_with_ai(file_path)
        for r in rows:
            r["currency"] = detected_currency
        return rows

    # Check if standard parser extracted nothing
    if not rows:
        print("Standard layout parser extracted 0 rows. Falling back to AI parser", flush=True)
        rows = parse_document_with_ai(file_path)
        for r in rows:
            r["currency"] = detected_currency
        return rows

    for r in rows:
        r["currency"] = detected_currency

    return rows
