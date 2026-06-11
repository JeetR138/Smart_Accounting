import json
import pytest
from unittest.mock import MagicMock, patch
from smart_accounting.app.services.classification import (
    classify_transactions,
    mock_classification,
    SYSTEM_PROMPT
)

def test_mock_classification_wio():
    rows = [
        {
            "date": "2026-12-10",
            "description": "Standard business supplier payment",
            "amount": 1200.00,
            "type": "debit",
            "source_file": "wio_statement.pdf"
        },
        {
            "date": "2026-12-11",
            "description": "Cash withdrawal",
            "amount": 5000.00,
            "type": "debit",
            "source_file": "wio_statement.pdf"
        }
    ]
    
    results = mock_classification(rows)
    assert len(results) == 2
    
    # First row check
    assert results[0]["zoho_module"] == "banktransactions"
    assert results[0]["confidence"] == "high"
    assert results[0]["zoho_fields"]["amount"] == 1200.00
    assert results[0]["zoho_fields"]["transaction_type"] == "withdrawal"
    
    # Second row check (cash withdrawal should be flagged/low confidence)
    assert results[1]["zoho_module"] == "banktransactions"
    assert results[1]["confidence"] == "low"
    assert "cash" in results[1]["flag_reason"].lower()


def test_mock_classification_expenses():
    rows = [
        {
            "date": "2026-12-15",
            "description": "AWS Web Hosting",
            "amount": 250.00,
            "type": "debit",
            "source_file": "expenses.xlsx"
        },
        {
            "date": "2026-12-16",
            "description": "Office Stationeries voucher",
            "amount": 2500.00,  # High amount for petty cash
            "type": "debit",
            "source_file": "petty_cash.xlsx"
        }
    ]
    
    results = mock_classification(rows)
    assert len(results) == 2
    
    assert results[0]["zoho_module"] == "expenses"
    assert results[0]["zoho_fields"]["account_name"] == "Software Expense"
    assert results[0]["confidence"] == "high"
    
    assert results[1]["zoho_module"] == "expenses"
    assert results[1]["confidence"] == "low"
    assert "high petty cash" in results[1]["flag_reason"].lower()


@patch("smart_accounting.app.services.classification.Anthropic")
def test_classify_transactions_api_success(mock_anthropic_class):
    # Set up mock client & response
    mock_client = MagicMock()
    mock_anthropic_class.return_value = mock_client
    
    mock_message = MagicMock()
    mock_client.messages.create.return_value = mock_message
    
    # Mock return JSON content from Claude
    claude_response_list = [
        {
            "row_index": 0,
            "zoho_module": "expenses",
            "zoho_fields": {
                "date": "2026-12-10",
                "amount": 450.00,
                "description": "AWS Hosting",
                "account_name": "Software Expense",
                "paid_through_account": "WIO Bank"
            },
            "confidence": "high",
            "flag_reason": ""
        }
    ]
    mock_message.content = [MagicMock(text=json.dumps(claude_response_list))]
    
    rows = [{
        "date": "2026-12-10",
        "description": "AWS Hosting",
        "amount": 450.00,
        "type": "debit",
        "source_file": "expenses.xlsx"
    }]
    
    # Force use of API flow (with settings loaded and use_mock=False)
    with patch("smart_accounting.app.services.classification.settings") as mock_settings:
        mock_settings.ANTHROPIC_API_KEY = "real-api-key"
        
        results = classify_transactions(rows, use_mock=False)
        
        assert len(results) == 1
        assert results[0]["zoho_module"] == "expenses"
        assert results[0]["confidence"] == "high"
        assert results[0]["zoho_fields"]["account_name"] == "Software Expense"
        
        # Verify Anthropic create call
        mock_client.messages.create.assert_called_once()
        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["system"] == SYSTEM_PROMPT
        assert "AWS Hosting" in call_kwargs["messages"][0]["content"]
