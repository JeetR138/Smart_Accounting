import sys
import json
from smart_accounting.app.services.parser import parse_document, ParserError

def main():
    if len(sys.argv) < 2:
        print("Usage: python run_parser.py <path_to_statement_or_sheet>")
        sys.exit(1)
        
    file_path = sys.argv[1]
    print(f"Parsing file: {file_path}")
    
    try:
        rows = parse_document(file_path)
        print(f"\nSuccessfully parsed {len(rows)} rows:")
        print(json.dumps(rows, indent=2, default=str))
    except ParserError as e:
        print(f"\nParser Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
