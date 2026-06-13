import os
import pytest
import pandas as pd
from unittest.mock import MagicMock, patch
from smart_accounting.app.services.parser import (
    normalize_date,
    normalize_amount,
    detect_file_type,
    parse_document,
    ParserError,
    UnsupportedFileError
)

# --- Date Normalization Tests ---
def test_normalize_date():
    assert normalize_date("10/12/2026") == "2026-12-10"
    assert normalize_date("10-12-2026") == "2026-12-10"
    assert normalize_date("2026-12-10") == "2026-12-10"
    assert normalize_date("10 Dec 2026") == "2026-12-10"
    assert normalize_date("10 December 2026") == "2026-12-10"
    assert normalize_date("10-Dec-2026") == "2026-12-10"
    assert normalize_date("") == ""
    assert normalize_date(None) == ""


# --- Amount Normalization Tests ---
def test_normalize_amount():
    assert normalize_amount("1,234.56") == 1234.56
    assert normalize_amount("(1,234.56)") == 1234.56
    assert normalize_amount("AED 500.00") == 500.00
    assert normalize_amount(" - 50.25 ") == 50.25
    assert normalize_amount(100.5) == 100.5
    assert normalize_amount(None) == 0.0


# --- Excel Mock Generators ---
@pytest.fixture
def temp_dir(tmp_path):
    return tmp_path


def create_mock_excel(path, columns, data, sheet_name="Sheet1"):
    df = pd.DataFrame(data, columns=columns)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)


# --- Test Excel Parsers ---

def test_network_international_parser(temp_dir):
    file_path = os.path.join(temp_dir, "ni_statement.xlsx")
    columns = ["Transaction Date", "Merchant ID", "Gross Amount", "Net Amount"]
    data = [
        ["10/12/2026", "MID123", "100.00", "98.50"],
        ["11/12/2026", "MID123", "200.00", "197.00"]
    ]
    create_mock_excel(file_path, columns, data)
    
    fmt, source = detect_file_type(file_path)
    assert fmt == "excel"
    assert source == "network_international"
    
    rows = parse_document(file_path)
    assert len(rows) == 2
    assert rows[0]["date"] == "2026-12-10"
    assert rows[0]["amount"] == 98.50
    assert rows[0]["type"] == "credit"
    assert rows[0]["source_file"] == "ni_statement.xlsx"


def test_nomod_parser(temp_dir):
    file_path = os.path.join(temp_dir, "nomod_statement.xlsx")
    columns = ["Created At", "Customer", "Amount", "Fee", "Net"]
    data = [
        ["12-Dec-2026", "John Doe", "150.00", "3.00", "147.00"],
        ["13-Dec-2026", "Jane Smith", "250.00", "5.00", "245.00"]
    ]
    create_mock_excel(file_path, columns, data)
    
    fmt, source = detect_file_type(file_path)
    assert fmt == "excel"
    assert source == "nomod"
    
    rows = parse_document(file_path)
    assert len(rows) == 2
    assert rows[0]["date"] == "2026-12-12"
    assert rows[0]["amount"] == 147.00
    assert rows[0]["type"] == "credit"


def test_purchases_parser(temp_dir):
    file_path = os.path.join(temp_dir, "purchases.xlsx")
    columns = ["Invoice Date", "Supplier", "Total Amount"]
    data = [
        ["2026-12-14", "Supplier A", "5000.00"],
        ["2026-12-15", "Supplier B", "12000.00"]
    ]
    create_mock_excel(file_path, columns, data, sheet_name="Purchases")
    
    fmt, source = detect_file_type(file_path)
    assert fmt == "excel"
    assert source == "purchases"
    
    rows = parse_document(file_path)
    assert len(rows) == 2
    assert rows[0]["date"] == "2026-12-14"
    assert rows[0]["amount"] == 5000.00
    assert rows[0]["type"] == "debit"


def test_expenses_parser(temp_dir):
    file_path = os.path.join(temp_dir, "expenses.xlsx")
    columns = ["Expense Date", "Merchant", "Category", "Amount"]
    data = [
        ["2026-12-16", "Amazon Web Services", "Hosting", "450.00"],
        ["2026-12-17", "Google Workspace", "Software", "60.00"]
    ]
    create_mock_excel(file_path, columns, data, sheet_name="Expenses")
    
    fmt, source = detect_file_type(file_path)
    assert fmt == "excel"
    assert source == "expenses"
    
    rows = parse_document(file_path)
    assert len(rows) == 2
    assert rows[0]["date"] == "2026-12-16"
    assert rows[0]["amount"] == 450.00
    assert rows[0]["type"] == "debit"


def test_petty_cash_parser(temp_dir):
    file_path = os.path.join(temp_dir, "petty_cash.xlsx")
    columns = ["Date", "Particulars", "Receipt", "Payment"]
    data = [
        ["2026-12-18", "Office Stationeries", "", "150.00"],
        ["2026-12-19", "Received from Main Cash", "1000.00", ""],
        ["2026-12-20", "Total Sum", "1000.00", "150.00"]  # should be skipped
    ]
    create_mock_excel(file_path, columns, data, sheet_name="Petty Cash")
    
    fmt, source = detect_file_type(file_path)
    assert fmt == "excel"
    assert source == "petty_cash"
    
    rows = parse_document(file_path)
    assert len(rows) == 2  # Total Sum row should be skipped
    
    assert rows[0]["date"] == "2026-12-18"
    assert rows[0]["amount"] == 150.00
    assert rows[0]["type"] == "debit"
    
    assert rows[1]["date"] == "2026-12-19"
    assert rows[1]["amount"] == 1000.00
    assert rows[1]["type"] == "credit"


# --- Test PDF Parsers using Mocks ---

@patch("pdfplumber.open")
def test_wio_pdf_parser(mock_pdfplumber_open):
    # Set up mock PDF structure
    mock_pdf = MagicMock()
    mock_page = MagicMock()
    mock_pdf.pages = [mock_page]
    mock_pdfplumber_open.return_value.__enter__.return_value = mock_pdf
    
    # 1. Mock first page extract_text for detection
    mock_page.extract_text.return_value = "Wio Bank Statement for ABC Corp\nDate Range..."
    
    # 2. Mock extract_tables
    # Wio columns: Date | Description | Amount | Type
    mock_page.extract_tables.return_value = [
        [
            ["Transaction Date", "Description", "Amount", "Type"],
            ["22/12/2026", "Invoice Payment", "5000.00", "Credit"],
            ["23/12/2026", "Office Rent", "1500.00", "Debit"]
        ]
    ]
    
    file_path = "mock_wio.pdf"
    
    # Test detection
    with patch("os.path.exists", return_value=True):
        fmt, source = detect_file_type(file_path)
        assert fmt == "pdf"
        assert source == "wio"
        
        # Test parsing
        rows = parse_document(file_path)
        assert len(rows) == 2
        assert rows[0]["date"] == "2026-12-22"
        assert rows[0]["amount"] == 5000.00
        assert rows[0]["type"] == "credit"
        assert rows[0]["source_file"] == "mock_wio.pdf"
        
        assert rows[1]["date"] == "2026-12-23"
        assert rows[1]["amount"] == 1500.00
        assert rows[1]["type"] == "debit"


@patch("pdfplumber.open")
def test_mashreq_pdf_parser(mock_pdfplumber_open):
    # Set up mock PDF structure
    mock_pdf = MagicMock()
    mock_page = MagicMock()
    mock_pdf.pages = [mock_page]
    mock_pdfplumber_open.return_value.__enter__.return_value = mock_pdf
    
    # 1. Mock first page extract_text for detection
    mock_page.extract_text.return_value = "Welcome to Mashreqbank Statement\n..."
    
    # 2. Mock extract_tables
    # Mashreq columns: Txn Date | Value Date | Description | Debit | Credit | Balance
    mock_page.extract_tables.return_value = [
        [
            ["Txn Date", "Value Date", "Description", "Debit", "Credit", "Balance"],
            ["24-Dec-2026", "24-Dec-2026", "Supplier Payment", "350.00", "", "10000.00"],
            ["25-Dec-2026", "25-Dec-2026", "Client Direct Transfer", "", "1800.00", "11800.00"]
        ]
    ]
    
    file_path = "mock_mashreq.pdf"
    
    # Test detection
    with patch("os.path.exists", return_value=True):
        fmt, source = detect_file_type(file_path)
        assert fmt == "pdf"
        assert source == "mashreq"
        
        # Test parsing
        rows = parse_document(file_path)
        assert len(rows) == 2
        assert rows[0]["date"] == "2026-12-24"
        assert rows[0]["amount"] == 350.00
        assert rows[0]["type"] == "debit"
        
        assert rows[1]["date"] == "2026-12-25"
        assert rows[1]["amount"] == 1800.00
        assert rows[1]["type"] == "credit"


@patch("pdfplumber.open")
def test_standard_chartered_pdf_parser(mock_pdfplumber_open):
    # Set up mock PDF structure
    mock_pdf = MagicMock()
    mock_page = MagicMock()
    mock_pdf.pages = [mock_page]
    mock_pdfplumber_open.return_value.__enter__.return_value = mock_pdf
    
    # Mock extract_text
    mock_page.extract_text.return_value = (
        "IFSC: SCBL0036078\n"
        "16 Jun 19 16 Jun 19 BALANCE FORWARD 114,453.65\n"
        "17 Jun 19 16 Jun 19 ATM WITHDRAWAL SELF-SWITCH 1,500.00 112,953.65\n"
        "AT NFS 04:54:54\n"
        "18 Jun 19 18 Jun 19 ATM WITHDRAWAL SELF-SWITCH 1,500.00 111,453.65\n"
        "CRADJ/UPI/AXB/916616736180/2019-06- 1,035.49 112,489.14\n"
    )
    
    file_path = "ebrcpt_file_5e37ba9973e09.pdf"
    
    with patch("os.path.exists", return_value=True):
        fmt, source = detect_file_type(file_path)
        assert fmt == "pdf"
        assert source == "standard_chartered"
        
        rows = parse_document(file_path)
        assert len(rows) == 3
        
        assert rows[0]["date"] == "2019-06-17"
        assert rows[0]["amount"] == 1500.00
        assert rows[0]["type"] == "debit"
        assert "AT NFS" in rows[0]["description"]
        
        assert rows[1]["date"] == "2019-06-18"
        assert rows[1]["amount"] == 1500.00
        assert rows[1]["type"] == "debit"
        
        assert rows[2]["date"] == "2019-06-18"
        assert rows[2]["amount"] == 1035.49
        assert rows[2]["type"] == "credit"


def test_general_ledger_parser(temp_dir):
    file_path = os.path.join(temp_dir, "General-Ledger.xlsx")
    columns = ["GLID", "TxnDate", "AccountNumber", "AccountName", "Debit", "Credit", "Description", "Currency"]
    data = [
        ["GL000000", "2024-05-05", 4000, "Sales Revenue", 0.00, 2505.15, "AutoPost 0", "GBP"],
        ["GL000001", "2024-06-23", 5000, "COGS", 1184.73, 0.00, "AutoPost 1", "GBP"]
    ]
    create_mock_excel(file_path, columns, data)
    
    fmt, source = detect_file_type(file_path)
    assert fmt == "excel"
    assert source == "general_ledger"
    
    rows = parse_document(file_path)
    assert len(rows) == 2
    
    assert rows[0]["date"] == "2024-05-05"
    assert rows[0]["amount"] == 2505.15
    assert rows[0]["type"] == "credit"
    assert "Sales Revenue" in rows[0]["description"]
    
    assert rows[1]["date"] == "2024-06-23"
    assert rows[1]["amount"] == 1184.73
    assert rows[1]["type"] == "debit"
    assert "COGS" in rows[1]["description"]


def test_currency_detection(temp_dir):
    from smart_accounting.app.services.parser import detect_currency_from_file, parse_document
    
    # 1. Test detection from filename
    assert detect_currency_from_file("statement_usd_2026.xlsx") == "USD"
    assert detect_currency_from_file("aed_report.xlsx") == "AED"
    assert detect_currency_from_file("eur.xlsx") == "EUR"
    
    # 2. Test detection from excel content mock
    excel_path = os.path.join(temp_dir, "test_curr_detect_expenses.xlsx")
    columns = ["Expense Date", "Merchant", "Category", "Amount", "Currency Code"]
    data = [
        ["2026-12-10", "Sales fee", "Hosting", "100.00", "EUR"],
        ["2026-12-11", "Payout", "Hosting", "200.00", "EUR"]
    ]
    create_mock_excel(excel_path, columns, data, sheet_name="Expenses")
    assert detect_currency_from_file(excel_path) == "EUR"
    
    # 3. Test parse_document stamping currency
    rows = parse_document(excel_path, default_currency="AED")
    assert len(rows) == 2
    assert rows[0]["currency"] == "EUR"


