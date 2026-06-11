import logging
import time
from datetime import datetime
from typing import List, Dict, Any, Tuple
import httpx
from sqlalchemy.orm import Session
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from smart_accounting.app.config import settings
from smart_accounting.app.models import ProcessingLog
from smart_accounting.app.services.oauth import get_valid_access_token

logger = logging.getLogger(__name__)

# Cache structure: Key = (zoho_org_id, access_token), Value = (timestamp, list of accounts)
_accounts_cache: Dict[Tuple[str, str], Tuple[float, List[Dict[str, Any]]]] = {}

# Cache structure: Key = (zoho_org_id, access_token, account_name), Value = (timestamp, bank_account_id)
_bank_accounts_cache: Dict[Tuple[str, str, str], Tuple[float, str]] = {}



class ZohoAPIError(Exception):
    """Raised for Zoho API error responses."""
    pass

class ZohoRateLimitError(ZohoAPIError):
    """Raised when Zoho Books rate limits the client (HTTP 429)."""
    pass


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=15),
    retry=retry_if_exception_type(ZohoRateLimitError),
    reraise=True
)
def _execute_zoho_post(access_token: str, zoho_org_id: str, zoho_module: str, fields: Dict[str, Any]) -> str:
    """
    Executes a POST request to Zoho Books REST API.
    Retries automatically with exponential backoff on Rate Limit (HTTP 429) errors.
    """
    # If credentials are not set, return a mock Zoho transaction ID
    if not settings.ZOHO_CLIENT_ID or settings.ZOHO_CLIENT_ID == "your-zoho-client-id" or access_token.startswith("mock_"):
        logger.info(f"[Mock Zoho POST] Module: {zoho_module}, Fields: {fields}")
        return f"mock_zoho_{zoho_module}_{int(datetime.utcnow().timestamp())}"

    url = f"{settings.ZOHO_BOOKS_URL}/v3/{zoho_module}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-com-zoho-books-organizationid": zoho_org_id,
        "Content-Type": "application/json;charset=UTF-8"
    }

    try:
        print(f"[ZOHO REQUEST] url: {url} | payload: {fields}", flush=True)
        response = httpx.post(url, json=fields, headers=headers, timeout=10.0)
        
        if response.status_code == 429:
            try:
                res_json = response.json()
                if res_json.get("code") == 45 or "maximum call rate limit" in res_json.get("message", "").lower():
                    raise ZohoAPIError(f"Zoho API daily rate limit exceeded: {res_json.get('message')}")
            except ValueError:
                pass
            logger.warning("Zoho API Rate Limit Hit (429). Retrying...")
            raise ZohoRateLimitError("Rate limit exceeded")
            
        res_json = response.json()
        if response.status_code not in [200, 201] or res_json.get("code") != 0:
            err_msg = res_json.get("message", "Unknown Zoho API Error")
            raise ZohoAPIError(f"Zoho API error: {err_msg} (code: {res_json.get('code')})")
            
        # Extract record ID from response based on the module
        # Zoho returns something like {"code": 0, "message": "...", "expense": {"expense_id": "..."}}
        module_singular = zoho_module.rstrip('s')
        if module_singular == "banktransaction":
            module_singular = "banktransaction" # in Zoho it might be transaction or similar
        
        # Look for keys ending in _id
        data_block = res_json.get(module_singular, res_json)
        if isinstance(data_block, dict):
            for k, v in data_block.items():
                if k.endswith("_id"):
                    return str(v)
        
        return res_json.get("transaction_id", f"zoho_auto_{int(datetime.utcnow().timestamp())}")
        
    except httpx.RequestError as e:
        raise ZohoAPIError(f"Network error contacting Zoho: {e}")


def get_or_create_zoho_bank_account(access_token: str, zoho_org_id: str, statement_source: str) -> str:
    """
    Fetches the bank account list from Zoho.
    If an account matching the statement source exists, returns its ID.
    Otherwise, creates it and returns the new ID.
    Uses caching to avoid redundant API calls.
    """
    source_lower = statement_source.lower() if statement_source else ""
    if "wio" in source_lower:
        account_name = "WIO Bank"
    elif "mashreq" in source_lower:
        account_name = "Mashreq Bank"
    elif "standard_chartered" in source_lower or "ebrcpt" in source_lower:
        account_name = "Standard Chartered Bank"
    else:
        account_name = "General Operating Bank Account"

    # Support mock flow
    if not settings.ZOHO_CLIENT_ID or settings.ZOHO_CLIENT_ID == "your-zoho-client-id" or access_token.startswith("mock_"):
        return f"mock_bank_account_id_{account_name.replace(' ', '_')}"

    cache_key = (zoho_org_id, access_token, account_name)
    now = time.time()
    if cache_key in _bank_accounts_cache:
        ts, cached_id = _bank_accounts_cache[cache_key]
        if now - ts < 300:  # 5 min cache
            return cached_id

    list_url = f"{settings.ZOHO_BOOKS_URL}/v3/bankaccounts"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-com-zoho-books-organizationid": zoho_org_id
    }
    
    try:
        res = httpx.get(list_url, headers=headers)
        if res.status_code == 429:
            raise ZohoAPIError("Zoho API rate limit exceeded while listing bank accounts")
            
        res_json = {}
        try:
            res_json = res.json()
        except ValueError:
            pass
            
        if res.status_code != 200 or res_json.get("code") != 0:
            err_msg = res_json.get("message", "Unknown error listing bank accounts")
            err_code = res_json.get("code")
            if err_code == 45 or "rate limit" in err_msg.lower() or "maximum call rate limit" in err_msg.lower():
                raise ZohoAPIError(f"Zoho API daily rate limit exceeded: {err_msg}")
            raise ZohoAPIError(f"Zoho API error: {err_msg} (code: {err_code})")
            
        # Search for exact match
        for account in res_json.get("bankaccounts", []):
            if account.get("account_name").lower() == account_name.lower():
                acc_id = account.get("account_id")
                _bank_accounts_cache[cache_key] = (now, acc_id)
                return acc_id
                        
        # Create the account if not found in list
        create_url = f"{settings.ZOHO_BOOKS_URL}/v3/bankaccounts"
        payload = {
            "account_name": account_name,
            "account_type": "bank",
            "currency_code": "INR"
        }
        create_res = httpx.post(create_url, json=payload, headers=headers)
        if create_res.status_code == 429:
            raise ZohoAPIError("Zoho API rate limit exceeded while creating bank account")
            
        create_json = {}
        try:
            create_json = create_res.json()
        except ValueError:
            pass
            
        if create_res.status_code in [200, 201] and create_json.get("code") == 0:
            acc_id = create_json.get("bankaccount", {}).get("account_id")
            if acc_id:
                _bank_accounts_cache[cache_key] = (now, acc_id)
                return acc_id
                
        # Handle create error or check for rate limit
        err_msg = create_json.get("message", "Unknown error creating bank account")
        err_code = create_json.get("code")
        if err_code == 45 or "rate limit" in err_msg.lower() or "maximum call rate limit" in err_msg.lower():
            raise ZohoAPIError(f"Zoho API daily rate limit exceeded: {err_msg}")
            
        # Fallback to any cash/bank account found if creation fails for standard reasons
        accounts = res_json.get("bankaccounts", [])
        if accounts:
            acc_id = accounts[0].get("account_id")
            _bank_accounts_cache[cache_key] = (now, acc_id)
            return acc_id
                
        raise ZohoAPIError(f"Failed to find or create bank account '{account_name}' in Zoho Books (create code: {err_code}, msg: {err_msg})")
    except Exception as e:
        logger.error(f"Error in get_or_create_zoho_bank_account: {e}")
        raise


def get_zoho_accounts(access_token: str, zoho_org_id: str) -> List[Dict[str, Any]]:
    """
    Fetches the Chart of Accounts list from Zoho.
    """
    if not settings.ZOHO_CLIENT_ID or settings.ZOHO_CLIENT_ID == "your-zoho-client-id" or access_token.startswith("mock_"):
        # Return dummy list of standard accounts for testing/mock purposes
        return [
            {"account_id": "mock_acc_sales", "account_name": "Sales", "account_type": "income"},
            {"account_id": "mock_acc_office", "account_name": "Office Supplies", "account_type": "expense"},
            {"account_id": "mock_acc_other", "account_name": "Other Expenses", "account_type": "expense"},
            {"account_id": "mock_acc_general", "account_name": "General Income", "account_type": "income"},
            {"account_id": "mock_acc_uncategorized", "account_name": "Uncategorized", "account_type": "expense"},
            {"account_id": "mock_acc_meals", "account_name": "Meals and Entertainment", "account_type": "expense"},
            {"account_id": "mock_acc_travel", "account_name": "Travel Expense", "account_type": "expense"},
            {"account_id": "mock_acc_internet", "account_name": "IT and Internet Expenses", "account_type": "expense"},
            {"account_id": "mock_acc_bank_fees", "account_name": "Bank Fees and Charges", "account_type": "expense"}
        ]

    url = f"{settings.ZOHO_BOOKS_URL}/v3/chartofaccounts"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-com-zoho-books-organizationid": zoho_org_id
    }
    try:
        res = httpx.get(url, headers=headers)
        if res.status_code == 200:
            res_json = res.json()
            if res_json.get("code") == 0:
                return res_json.get("chartofaccounts", [])
    except Exception as e:
        logger.error(f"Error fetching chart of accounts: {e}")
    return []


def get_cached_accounts(access_token: str, zoho_org_id: str) -> List[Dict[str, Any]]:
    cache_key = (zoho_org_id, access_token)
    now = time.time()
    if cache_key in _accounts_cache:
        timestamp, accounts = _accounts_cache[cache_key]
        if now - timestamp < 300:  # 5 min cache
            return accounts
            
    accounts = get_zoho_accounts(access_token, zoho_org_id)
    if accounts:
        _accounts_cache[cache_key] = (now, accounts)
    return accounts


def resolve_account_id(access_token: str, zoho_org_id: str, search_name: str, fallback_type: str) -> str:
    """
    Looks up Chart of Accounts to find the ID corresponding to search_name.
    Prioritizes exact match by name, then matching type, then substring match, and falls back to fallback type.
    """
    accounts = get_cached_accounts(access_token, zoho_org_id)
    search_name_lower = search_name.lower() if search_name else ""
    
    # 1. First priority: Exact match by name
    for acc in accounts:
        acc_name = acc.get("account_name", "").lower()
        if search_name_lower == acc_name:
            return acc.get("account_id")
            
    # 2. Second priority: Substring match by name AND matching account type
    for acc in accounts:
        acc_name = acc.get("account_name", "").lower()
        if search_name_lower and search_name_lower in acc_name:
            if acc.get("account_type") == fallback_type:
                return acc.get("account_id")
                
    # 3. Third priority: Substring match by name (any type)
    for acc in accounts:
        acc_name = acc.get("account_name", "").lower()
        if search_name_lower and search_name_lower in acc_name:
            return acc.get("account_id")
            
    # 4. Fourth priority: Fallback to any account of the fallback type
    for acc in accounts:
        if acc.get("account_type") == fallback_type:
            return acc.get("account_id")
            
    # 5. Last resort fallback
    if accounts:
        return accounts[0].get("account_id")
        
    return f"fallback_acc_{fallback_type}"


def infer_expense_category(description: str) -> str:
    """
    Infers standard Zoho expense account category based on transaction description.
    """
    desc_lower = description.lower() if description else ""
    if "hotel" in desc_lower or "travel" in desc_lower or "flight" in desc_lower or "taxi" in desc_lower or "uber" in desc_lower:
        return "Travel Expense"
    elif "restaurant" in desc_lower or "food" in desc_lower or "meal" in desc_lower or "dining" in desc_lower or "dinner" in desc_lower:
        return "Meals and Entertainment"
    elif "internet" in desc_lower or "aws" in desc_lower or "hosting" in desc_lower or "software" in desc_lower or "cloud" in desc_lower:
        return "IT and Internet Expenses"
    elif "fee" in desc_lower or "charge" in desc_lower or "interest" in desc_lower:
        return "Bank Fees and Charges"
    elif "office" in desc_lower or "supply" in desc_lower or "stationery" in desc_lower:
        return "Office Supplies"
    return "Other Expenses"


def post_row_to_zoho(db: Session, company_id: int, zoho_org_id: str, zoho_module: str, fields: Dict[str, Any], source_file: str = "") -> Tuple[str, str]:
    """
    Helper function that retrieves a valid token, normalizes payloads, and makes the post call.
    Returns (zoho_record_id, actual_zoho_module_posted).
    """
    access_token = get_valid_access_token(db, company_id)
    fields = dict(fields or {})  # Work on a copy to avoid mutating inputs
    
    # Normalize fields for Bank Transactions API
    if zoho_module == "banktransactions":
        bank_acc_id = get_or_create_zoho_bank_account(access_token, zoho_org_id, source_file)
        t_type = fields.get("transaction_type")
        
        if t_type == "withdrawal":
            # Outgoing money: Post as an Expense!
            zoho_module = "expenses"
            desc = fields.get("description", "")
            cat_name = infer_expense_category(desc)
            expense_acc_id = resolve_account_id(access_token, zoho_org_id, cat_name, "expense")
            
            fields = {
                "account_id": expense_acc_id,
                "paid_through_account_id": bank_acc_id,
                "amount": float(fields.get("amount", 0.0)),
                "date": fields.get("date", ""),
                "description": desc
            }
            
        elif t_type == "deposit":
            # Incoming money: Post as bank transaction deposit!
            income_acc_id = resolve_account_id(access_token, zoho_org_id, "Sales", "income")
            
            fields = {
                "from_account_id": income_acc_id,
                "to_account_id": bank_acc_id,
                "transaction_type": "deposit",
                "amount": float(fields.get("amount", 0.0)),
                "date": fields.get("date", ""),
                "description": fields.get("description", "")
            }
            
    elif zoho_module == "expenses":
        # Resolve the expense category account ID
        cat_name = fields.get("account_name", "Other Expenses")
        expense_acc_id = resolve_account_id(access_token, zoho_org_id, cat_name, "expense")
        fields["account_id"] = expense_acc_id
        
        # Resolve the paid through bank account ID
        paid_through = fields.get("paid_through_account", "")
        bank_acc_id = get_or_create_zoho_bank_account(access_token, zoho_org_id, paid_through)
        fields["paid_through_account_id"] = bank_acc_id
        
        # Clean up fields not accepted by Zoho /expenses endpoint
        for key in ["account_name", "paid_through_account"]:
            if key in fields:
                del fields[key]
                
    record_id = _execute_zoho_post(access_token, zoho_org_id, zoho_module, fields)
    return record_id, zoho_module



def post_transactions(
    db: Session,
    company_id: int,
    zoho_org_id: str,
    parsed_rows: List[Dict[str, Any]],
    classified_rows: List[Dict[str, Any]]
) -> Dict[str, int]:
    """
    Orchestrates transaction posting:
    - High confidence rows are posted to Zoho Books.
    - Low confidence rows are flagged for manual review.
    - All outcomes are logged in `processing_log`.
    """
    stats = {"total_rows": len(parsed_rows), "posted": 0, "flagged": 0, "failed": 0}
    abort_posting = False
    abort_reason = ""

    for idx, (p_row, c_row) in enumerate(zip(parsed_rows, classified_rows), 1):
        zoho_module = c_row.get("zoho_module", "expenses")
        zoho_fields = c_row.get("zoho_fields", {})
        confidence = c_row.get("confidence", "low")
        flag_reason = c_row.get("flag_reason", "")
        amount = p_row.get("amount", 0.0)
        source_file = p_row.get("source_file", "unknown")

        log_entry = ProcessingLog(
            company_id=company_id,
            source_file=source_file,
            row_number=idx,
            zoho_module=zoho_module,
            amount=amount,
            raw_data=p_row,
            zoho_fields=zoho_fields
        )

        if confidence == "low":
            log_entry.status = "flagged"
            log_entry.flag_reason = flag_reason or "Low confidence classification"
            db.add(log_entry)
            stats["flagged"] += 1
            continue

        if abort_posting:
            log_entry.status = "failed"
            log_entry.flag_reason = f"Posting skipped: {abort_reason}"
            db.add(log_entry)
            stats["failed"] += 1
            continue

        # Post high confidence row
        try:
            zoho_record_id, actual_module = post_row_to_zoho(db, company_id, zoho_org_id, zoho_module, zoho_fields, source_file=source_file)
            log_entry.status = "posted"
            log_entry.zoho_module = actual_module
            log_entry.zoho_record_id = zoho_record_id
            log_entry.posted_at = datetime.utcnow()
            stats["posted"] += 1
        except Exception as e:
            logger.error(f"Failed to post row {idx} to Zoho: {e}")
            log_entry.status = "failed"
            log_entry.flag_reason = f"Posting failed: {str(e)}"
            stats["failed"] += 1
            
            err_msg_lower = str(e).lower()
            # Daily limit or rate limit
            is_rate_limit = "rate limit" in err_msg_lower or "rate_limit" in err_msg_lower or "maximum call rate limit" in err_msg_lower
            # Authentication failure (expired credentials, invalid token, etc.)
            is_auth_error = "invalid_client" in err_msg_lower or "invalid_token" in err_msg_lower or "code: 57" in err_msg_lower or "authentication failed" in err_msg_lower or "unauthorized" in err_msg_lower or "access_denied" in err_msg_lower
            # Connection/network/timeout errors
            is_network_error = "network error" in err_msg_lower or "connecterror" in err_msg_lower or "timeout" in err_msg_lower or "connection" in err_msg_lower
            
            if is_rate_limit:
                abort_posting = True
                abort_reason = "Zoho API daily rate limit exceeded"
            elif is_auth_error:
                abort_posting = True
                abort_reason = "Zoho authentication failed or token expired"
            elif is_network_error:
                abort_posting = True
                abort_reason = "Network connection to Zoho failed"

        db.add(log_entry)

    db.commit()
    return stats


def approve_flagged_entry(
    db: Session,
    company_id: int,
    entry_id: int,
    overrides: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Approves a previously flagged transaction, posts it to Zoho Books with optional adjustments,
    and updates its status in the processing log.
    """
    # Fetch log entry
    log_entry = db.query(ProcessingLog).filter(
        ProcessingLog.id == entry_id,
        ProcessingLog.company_id == company_id
    ).first()

    if not log_entry:
        raise ValueError(f"Flagged transaction entry {entry_id} not found for this company")

    if log_entry.status == "posted":
        raise ValueError(f"Transaction entry {entry_id} has already been posted to Zoho Books")

    # Fetch organization details
    company = log_entry.company
    if not company:
        raise ValueError(f"Associated company details not found")

    # Merge overrides into fields
    fields = dict(log_entry.zoho_fields or {})
    if overrides:
        fields.update(overrides)
        log_entry.zoho_fields = fields
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(log_entry, "zoho_fields")

    try:
        # Post to Zoho
        zoho_record_id, actual_module = post_row_to_zoho(db, company_id, company.zoho_org_id, log_entry.zoho_module, fields, source_file=log_entry.source_file)
        
        # Update log
        log_entry.status = "posted"
        log_entry.zoho_module = actual_module
        log_entry.zoho_record_id = zoho_record_id
        log_entry.posted_at = datetime.utcnow()
        log_entry.flag_reason = None
        db.commit()
        db.refresh(log_entry)

        return {
            "entry_id": log_entry.id,
            "status": log_entry.status,
            "zoho_record_id": log_entry.zoho_record_id,
            "posted_at": log_entry.posted_at
        }
    except Exception as e:
        logger.error(f"Approval failed for entry {entry_id}: {e}")
        log_entry.status = "failed"
        log_entry.flag_reason = f"Approval posting failed: {str(e)}"
        db.commit()
        raise ZohoAPIError(f"Approval posting failed: {e}")
