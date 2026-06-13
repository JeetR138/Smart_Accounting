import os
import sys
import json
import logging
from typing import List, Dict, Any
from anthropic import Anthropic, APIError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from smart_accounting.app.config import settings

logger = logging.getLogger(__name__)

# System instructions with detailed schema and rules
SYSTEM_PROMPT = """
You are an expert accounting AI assistant. Your task is to classify parsed financial transaction rows and map them to the correct Zoho Books modules and fields.

Available Zoho Modules and Rules:
1. "banktransactions"
   - Match: Bank statement rows (e.g., WIO, Mashreq, Standard Chartered, Emirates NBD, or any other bank statements).
   - Required zoho_fields:
     - "date": "YYYY-MM-DD"
     - "amount": float
     - "transaction_type": "deposit" (if credit/incoming) or "withdrawal" (if debit/outgoing)
     - "description": string (original description or cleaned version)
     - "payment_mode": "bank_transfer", "card", "cash", or "other"

2. "customerpayments"
   - Match: Network International payments and NOMOD payments.
   - Required zoho_fields:
     - "date": "YYYY-MM-DD"
     - "amount": float
     - "description": string
     - "payment_mode": "credit_card" or "online"
     - "customer_name": string (infer from description or source, default to "General Customer")

3. "bills"
   - Match: Purchases sheet rows.
   - Required zoho_fields:
     - "date": "YYYY-MM-DD"
     - "amount": float
     - "supplier_name": string (infer from supplier/vendor details)
     - "bill_number": string (invoice/bill number if available, else empty string)
     - "description": string

4. "expenses"
   - Match: Petty Cash sheet rows and Expenses sheet rows.
   - Required zoho_fields:
     - "date": "YYYY-MM-DD"
     - "amount": float
     - "description": string
     - "account_name": string (the Zoho expense category, e.g., "Office Supplies", "Hosting", "Software Expense", "Travel Expenses", "Meals and Entertainment", "Rent", "Utilities" - choose the most logical one)
     - "paid_through_account": "Petty Cash" (if source is petty cash), "WIO Bank" (if source is WIO), "Mashreq Bank" (if source is Mashreq), or "Other"

Confidence Scoring:
- Set "confidence" to "high" if the module is clear and all required zoho_fields can be populated with high certainty.
- Set "confidence" to "low" if:
  - The description is extremely vague (e.g. "cash", "payment", "payout")
  - The transaction details are missing essential information (like supplier name for a bill, or a category for an expense)
  - The transaction details seem irregular (e.g., petty cash expense > 2000 AED)
- If confidence is "low", specify a short, descriptive reason in "flag_reason". If confidence is "high", set "flag_reason" to "".

Response Format:
You MUST respond with a valid JSON array of objects. Each object corresponds to an input row and MUST contain these keys:
- "row_index": integer (0-indexed match to input rows)
- "zoho_module": string ("banktransactions" | "customerpayments" | "bills" | "expenses")
- "zoho_fields": object
- "confidence": string ("high" | "low")
- "flag_reason": string

CRITICAL JSON FORMATTING RULES:
1. The response must be a single, valid JSON array of objects.
2. Absolutely no markdown blocks (like ```json), conversational intro, or outro text.
3. Ensure all double quotes (") inside text values (such as descriptions or names) are properly escaped as \\" (e.g., "description": "ATM WITHDRAWAL \\"SELF-SWITCH\\"") so the JSON remains syntactically valid.
4. Escape all backslashes (\\) inside text values as \\\\.
5. Do not include any comments in the JSON.
6. Return the complete list of classifications. Do not truncate the output.

Few-Shot Examples:
Input:
[
  {"date": "2026-12-10", "description": "Amazon Web Services cloud hosting", "amount": 450.00, "type": "debit", "source_file": "expenses.xlsx"},
  {"date": "2026-12-11", "description": "NOMOD Payout Ref 123", "amount": 147.00, "type": "credit", "source_file": "nomod_statement.xlsx"},
  {"date": "2026-12-12", "description": "Lunch with client AED 150", "amount": 150.00, "type": "debit", "source_file": "petty_cash.xlsx"},
  {"date": "2026-12-13", "description": "Cash withdrawal", "amount": 5000.00, "type": "debit", "source_file": "wio_statement.pdf"},
  {"date": "2026-12-14", "description": "Payment", "amount": 100.00, "type": "debit", "source_file": "purchases.xlsx"}
]

Output:
[
  {
    "row_index": 0,
    "zoho_module": "expenses",
    "zoho_fields": {
      "date": "2026-12-10",
      "amount": 450.00,
      "description": "Amazon Web Services cloud hosting",
      "account_name": "Software Expense",
      "paid_through_account": "WIO Bank"
    },
    "confidence": "high",
    "flag_reason": ""
  },
  {
    "row_index": 1,
    "zoho_module": "customerpayments",
    "zoho_fields": {
      "date": "2026-12-11",
      "amount": 147.00,
      "description": "NOMOD Payout Ref 123",
      "payment_mode": "online",
      "customer_name": "General Customer"
    },
    "confidence": "high",
    "flag_reason": ""
  },
  {
    "row_index": 2,
    "zoho_module": "expenses",
    "zoho_fields": {
      "date": "2026-12-12",
      "amount": 150.00,
      "description": "Lunch with client AED 150",
      "account_name": "Meals and Entertainment",
      "paid_through_account": "Petty Cash"
    },
    "confidence": "high",
    "flag_reason": ""
  },
  {
    "row_index": 3,
    "zoho_module": "banktransactions",
    "zoho_fields": {
      "date": "2026-12-13",
      "amount": 5000.00,
      "transaction_type": "withdrawal",
      "description": "Cash withdrawal",
      "payment_mode": "cash"
    },
    "confidence": "low",
    "flag_reason": "High value bank withdrawal without clear recipient/payment mode details"
  },
  {
    "row_index": 4,
    "zoho_module": "bills",
    "zoho_fields": {
      "date": "2026-12-14",
      "amount": 100.00,
      "supplier_name": "",
      "bill_number": "",
      "description": "Payment"
    },
    "confidence": "low",
    "flag_reason": "Vague description 'Payment' in purchases sheet; missing supplier details"
  }
]
"""

# Retry with exponential backoff on Anthropic API errors
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(APIError),
    reraise=True
)
def _call_claude_api(client: Anthropic, model_name: str, payload_str: str) -> str:
    """Invokes Claude API to classify the batch of transactions."""
    message = client.messages.create(
        model=model_name,
        max_tokens=4000,
        temperature=0.0,  # Deterministic response
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Classify this batch of transaction rows:\n{payload_str}"
            }
        ]
    )
    return message.content[0].text

def mock_classification(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Generates deterministic mocked classification responses for testing/fallback."""
    results = []
    for idx, row in enumerate(rows):
        source = row.get("source_file", "").lower()
        desc = row.get("description", "").lower()
        amt = row.get("amount", 0.0)
        t_type = row.get("type", "unknown")
        dt = row.get("date", "")
        
        # Determine defaults based on filename
        if "wio" in source or "mashreq" in source or "standard_chartered" in source or "ebrcpt" in source or "emirates_nbd" in source or "nbd" in source:
            module = "banktransactions"
            fields = {
                "date": dt,
                "amount": amt,
                "transaction_type": "withdrawal" if t_type == "debit" else "deposit",
                "description": row.get("description", ""),
                "payment_mode": "bank_transfer"
            }
            conf = "high"
            reason = ""
            if "withdrawal" in desc or "cash" in desc:
                conf = "low"
                reason = "Vague cash withdrawal description"
                fields["payment_mode"] = "cash"
        elif "network" in source or "ni_statement" in source or "nomod" in source:
            module = "customerpayments"
            fields = {
                "date": dt,
                "amount": amt,
                "description": row.get("description", ""),
                "payment_mode": "online",
                "customer_name": "General Customer"
            }
            conf = "high"
            reason = ""
        elif "purchase" in source:
            module = "bills"
            supplier = row.get("description", "").replace("Purchase: ", "")
            fields = {
                "date": dt,
                "amount": amt,
                "supplier_name": supplier,
                "bill_number": "",
                "description": row.get("description", "")
            }
            conf = "high"
            reason = ""
            if "payment" in desc or not supplier:
                conf = "low"
                reason = "Missing supplier details"
        elif "ledger" in source or "general_ledger" in source:
            if t_type == "debit":
                module = "expenses"
                account_name = "Other Expenses"
                if "travel" in desc:
                    account_name = "Travel Expense"
                elif "cogs" in desc:
                    account_name = "Cost of Goods Sold"
                elif "payroll" in desc or "salaries" in desc:
                    account_name = "Salaries and Employee Wages"
                
                fields = {
                    "date": dt,
                    "amount": amt,
                    "description": row.get("description", ""),
                    "account_name": account_name,
                    "paid_through_account": "Standard Chartered Bank"
                }
                conf = "high"
                reason = ""
                if amt > 10000:
                    conf = "low"
                    reason = "Transaction value exceeds standard limit threshold"
            else:
                module = "banktransactions"
                fields = {
                    "date": dt,
                    "amount": amt,
                    "transaction_type": "deposit",
                    "description": row.get("description", ""),
                    "payment_mode": "other"
                }
                conf = "high"
                reason = ""
                if amt > 10000:
                    conf = "low"
                    reason = "Transaction value exceeds standard limit threshold"
        elif "expense" in source or "petty" in source:
            module = "expenses"
            account_name = "Office Supplies"
            if "hosting" in desc or "aws" in desc:
                account_name = "Software Expense"
            elif "meal" in desc or "lunch" in desc or "restaurant" in desc:
                account_name = "Meals and Entertainment"
            elif "taxi" in desc or "travel" in desc:
                account_name = "Travel Expenses"
                
            fields = {
                "date": dt,
                "amount": amt,
                "description": row.get("description", ""),
                "account_name": account_name,
                "paid_through_account": "Petty Cash" if "petty" in source else "WIO Bank"
            }
            conf = "high"
            reason = ""
            if amt > 10000:
                conf = "low"
                reason = "Transaction value exceeds standard limit threshold"
            elif amt > 2000 and "petty" in source:
                conf = "low"
                reason = "High petty cash expense value"
        else:
            if t_type == "credit":
                module = "banktransactions"
                fields = {
                    "date": dt,
                    "amount": amt,
                    "transaction_type": "deposit",
                    "description": row.get("description", ""),
                    "payment_mode": "other"
                }
                conf = "low"
                reason = "Unknown statement origin type (defaulted credit to bank transaction)"
            else:
                module = "expenses"
                fields = {
                    "date": dt,
                    "amount": amt,
                    "description": row.get("description", "")
                }
                conf = "low"
                reason = "Unknown statement origin type"
            
        results.append({
            "row_index": idx,
            "zoho_module": module,
            "zoho_fields": fields,
            "confidence": conf,
            "flag_reason": reason
        })
    return results

def classify_transactions(rows: List[Dict[str, Any]], batch_size: int = 50, use_mock: bool = None) -> List[Dict[str, Any]]:
    """
    Groups transaction rows into batches, calls the Claude API for classification, and handles errors.
    Returns classified rows matching the original ordering.
    """
    if not rows:
        return []
        
    if use_mock is None:
        use_mock = os.getenv("TESTING") == "True" or "pytest" in sys.modules
        
    # Check if we should use mock classification (e.g. key is not set or mock requested)
    if use_mock or settings.ANTHROPIC_API_KEY == "mock-key-for-testing" or not settings.ANTHROPIC_API_KEY:
        logger.info("Using mock classification for transaction rows")
        return mock_classification(rows)
        
    results = [None] * len(rows)
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    
    # We will use the model specified in prompt, falling back to configured Claude model
    model_name = settings.CLAUDE_MODEL
    
    # Process in batches
    for start_idx in range(0, len(rows), batch_size):
        batch = rows[start_idx : start_idx + batch_size]
        batch_indices = list(range(start_idx, min(start_idx + batch_size, len(rows))))
        
        # Prepare payload
        payload = [{"date": r["date"], "description": r["description"], "amount": r["amount"], "type": r["type"], "source_file": r["source_file"]} for r in batch]
        payload_str = json.dumps(payload, indent=2)
        
        try:
            logger.info(f"Sending batch {start_idx // batch_size + 1} ({len(batch)} rows) to Claude...")
            response_text = _call_claude_api(client, model_name, payload_str)
            
            # Robust JSON extraction: extract the outermost JSON array block [ ... ]
            clean_response = response_text.strip()
            start_idx_json = clean_response.find('[')
            end_idx_json = clean_response.rfind(']')
            if start_idx_json != -1 and end_idx_json != -1:
                json_str = clean_response[start_idx_json:end_idx_json+1]
            else:
                json_str = clean_response
                
            # Clean up trailing commas from Claude's response (e.g. [1, 2, ]) to make json loads bulletproof
            import re
            json_str = re.sub(r',\s*\]', ']', json_str)
            json_str = re.sub(r',\s*\}', '}', json_str)
            
            parsed_response = json.loads(json_str)
            
            if not isinstance(parsed_response, list):
                raise ValueError("Claude response is not a JSON list")
                
            for res in parsed_response:
                rel_idx = res.get("row_index")
                if rel_idx is not None:
                    # Calculate original global index
                    global_idx = start_idx + rel_idx
                    if global_idx < len(rows):
                        results[global_idx] = {
                            "zoho_module": res.get("zoho_module"),
                            "zoho_fields": res.get("zoho_fields"),
                            "confidence": res.get("confidence", "low"),
                            "flag_reason": res.get("flag_reason", "")
                        }
                        
        except Exception as e:
            logger.error(f"Failed to classify batch starting at index {start_idx}: {e}")
            # Fallback for this batch to avoid blocking processing
            mocked_batch = mock_classification(batch)
            for local_idx, m_res in enumerate(mocked_batch):
                global_idx = batch_indices[local_idx]
                results[global_idx] = {
                    "zoho_module": m_res["zoho_module"],
                    "zoho_fields": m_res["zoho_fields"],
                    "confidence": "low",
                    "flag_reason": f"Classification failed due to error: {str(e)}"
                }
                
    # Fill in any missing rows with default low confidence mapping
    for idx in range(len(rows)):
        if results[idx] is None:
            results[idx] = {
                "zoho_module": "expenses",
                "zoho_fields": {
                    "date": rows[idx]["date"],
                    "amount": rows[idx]["amount"],
                    "description": rows[idx]["description"]
                },
                "confidence": "low",
                "flag_reason": "No response mapping returned"
            }
            
    return results
