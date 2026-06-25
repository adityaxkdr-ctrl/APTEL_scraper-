import os
import re
import csv
import json
import urllib3
import requests
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor, as_completed

# Disable insecure request warning for SSL verification bypass
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.current_row = []
        self.current_cell = []
        self.in_tbody = False
        self.in_tr = False
        self.in_td = False
        self.current_href = None

    def handle_starttag(self, tag, attrs):
        if tag == 'tbody':
            self.in_tbody = True
        elif tag == 'tr' and self.in_tbody:
            self.in_tr = True
            self.current_row = []
        elif tag == 'td' and self.in_tr:
            self.in_td = True
            self.current_cell = []
            self.current_href = None
        elif tag == 'a' and self.in_td:
            attrs_dict = dict(attrs)
            if 'href' in attrs_dict:
                self.current_href = attrs_dict['href']
        elif tag in ('br', 'p', 'div') and self.in_td:
            self.current_cell.append('\n')

    def handle_endtag(self, tag):
        if tag == 'tbody':
            self.in_tbody = False
        elif tag == 'tr' and self.in_tr:
            self.in_tr = False
            self.rows.append(self.current_row)
        elif tag == 'td' and self.in_td:
            self.in_td = False
            text = ''.join(self.current_cell).strip()
            # Clean up newlines: strip individual lines, ignore empty lines
            cleaned_text = '\n'.join([line.strip() for line in text.split('\n') if line.strip()])
            self.current_row.append({
                'text': cleaned_text,
                'href': self.current_href
            })
        elif tag in ('br', 'p', 'div') and self.in_td:
            self.current_cell.append('\n')

    def handle_data(self, data):
        if self.in_td:
            self.current_cell.append(data)


def extract_next_listing_date(html):
    """Extract Next Listing Date from case details page HTML using regex."""
    # Pattern 1: Table row with colspan="3"
    m = re.search(r'Next Listing Date.*?colspan=\"3\">(.*?)</td>', html, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    
    # Pattern 2: Any general td following Next Listing Date
    m = re.search(r'Next Listing Date.*?<td>(.*?)</td>', html, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    
    return "N/A"


# escape_csv_field function removed, python's csv module used instead.


def fetch_row_detail(row, idx, total_count, session, headers):
    """Helper function to fetch the detail page and extract the Next Listing Date for a single row."""
    if len(row) < 7:
        return None

    sl_no = row[0]['text']
    dfr_no = row[1]['text']
    dfr_href = row[1]['href']
    case_no = row[2]['text']
    party_detail = row[3]['text']
    date_of_filing = row[4]['text']
    next_date_listing = row[5]['text']
    status = row[6]['text']

    next_listing_date = "N/A"
    if dfr_href:
        detail_url = f"https://aptel.gov.in{dfr_href}" if not dfr_href.startswith("http") else dfr_href
        # Fetch detailed page with retry logic
        for attempt in range(3):
            try:
                resp = session.get(detail_url, headers=headers, timeout=15)
                resp.raise_for_status()
                next_listing_date = extract_next_listing_date(resp.text)
                break
            except Exception as e:
                if attempt == 2:
                    print(f"      [ERROR] Row {idx+1}/{total_count} DFR {dfr_no}: Failed to fetch detail page ({e})")
                    # Fallback to the main page table value
                    next_listing_date = next_date_listing if next_date_listing != "N/A" else "N/A"
    else:
        # No DFR link, fallback to main page table value
        next_listing_date = next_date_listing if next_date_listing != "N/A" else "N/A"

    return [
        sl_no,
        dfr_no,
        case_no,
        party_detail,
        date_of_filing,
        next_listing_date,
        status
    ]


def scrape_range(from_date, to_date, output_csv_filename):
    """Perform scraping for a single date range."""
    print(f"\n==================================================")
    print(f"STARTING SCRAPING FOR RANGE: {from_date} to {to_date}")
    print(f"==================================================")
    
    session = requests.Session()
    session.verify = False
    
    # Configure connection pool for concurrency
    adapter = requests.adapters.HTTPAdapter(pool_connections=15, pool_maxsize=15)
    session.mount('https://', adapter)
    session.mount('http://', adapter)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    # Step 1: Get the main page to retrieve form_build_id
    main_url = "https://aptel.gov.in/en/casestatusapi/tab4"
    print(f"Fetching search form build ID from {main_url}...")
    try:
        resp = session.get(main_url, headers=headers, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"Error: Failed to fetch search page: {e}")
        return False

    form_build_id_match = re.search(r'name="form_build_id" value="([^"]+)"', resp.text)
    if not form_build_id_match:
        print("Error: Could not extract form_build_id from the main page.")
        return False
    form_build_id = form_build_id_match.group(1)
    print(f"Retrieved form_build_id: {form_build_id}")

    # Step 2: Submit the AJAX POST request
    ajax_url = "https://aptel.gov.in/en/casestatusapi/tab4?ajax_form=1"
    payload = {
        "form_build_id": form_build_id,
        "form_id": "case_order_date_wise_form",
        "from_date": from_date,
        "to_date": to_date,
        "op": "Submit",
        "_triggering_element_name": "op",
        "_triggering_element_value": "Submit"
    }

    ajax_headers = headers.copy()
    ajax_headers.update({
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://aptel.gov.in",
        "Referer": "https://aptel.gov.in/en/casestatusapi/tab4"
    })

    print(f"Posting search query for range {from_date} to {to_date}...")
    try:
        post_resp = session.post(ajax_url, data=payload, headers=ajax_headers, timeout=60)
        post_resp.raise_for_status()
        data = post_resp.json()
    except Exception as e:
        print(f"Error: Failed to post search request: {e}")
        return False

    # Find the insert command containing the HTML table
    html_content = None
    for item in data:
        if item.get("command") == "insert" and item.get("selector") == ".result_message_date":
            html_content = item.get("data")
            break

    if not html_content:
        print("Warning: Search result HTML table not found in AJAX response. No cases in this range?")
        # Let's check if there's any result_message_date content showing "No Record Found"
        return True

    # Step 3: Parse the HTML table
    print("Parsing HTML search results table...")
    parser = TableParser()
    parser.feed(html_content)
    rows = parser.rows
    total_rows = len(rows)
    print(f"Found {total_rows} total cases in this range.")

    if not rows:
        print("No rows found in search results.")
        return True

    # Step 4: Fetch detailed pages in parallel
    print(f"Fetching detailed pages in parallel (using 10 workers)...")
    processed_records = [None] * total_rows  # preallocate to keep rows ordered

    with ThreadPoolExecutor(max_workers=10) as executor:
        # Submit all tasks
        futures_map = {
            executor.submit(fetch_row_detail, row, idx, total_rows, session, headers): idx 
            for idx, row in enumerate(rows)
        }

        completed_count = 0
        for future in as_completed(futures_map):
            idx = futures_map[future]
            completed_count += 1
            try:
                res = future.result()
                if res:
                    processed_records[idx] = res
            except Exception as e:
                print(f"      [CRITICAL ERROR] Future failed for row {idx+1}: {e}")
            
            # Print periodic progress
            if completed_count % 50 == 0 or completed_count == total_rows:
                print(f"Progress: Completed {completed_count}/{total_rows} detail fetches...")

    # Filter out any None results (e.g. invalid rows)
    processed_records = [r for r in processed_records if r is not None]

    # Step 5: Save results to CSV
    output_dir = "exports"
    os.makedirs(output_dir, exist_ok=True)
    csv_path = os.path.join(output_dir, output_csv_filename)
    
    headers_list = [
        "SL NO.",
        "DFR No",
        "Case No",
        "Party Detail",
        "Date Of Filing",
        "Next Date Of Listing/Court",
        "Status"
    ]

    print(f"Writing {len(processed_records)} records to CSV: {csv_path}...")
    try:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter=",", quoting=csv.QUOTE_MINIMAL)
            writer.writerow(headers_list)
            writer.writerows(processed_records)
                
        print(f"Successfully scraped range and saved to {output_csv_filename}!\n")
        return True
    except Exception as e:
        print(f"Error writing CSV file: {e}")
        return False


def main():
    ranges = [
        {"from": "2022-01-01", "to": "2022-12-31", "file": "cases_2022.csv"},
    ]
    
    for r in ranges:
        success = scrape_range(r["from"], r["to"], r["file"])
        if not success:
            print(f"Stopping execution due to failure in range: {r['from']} to {r['to']}")
            break

    print("All tasks completed.")

if __name__ == "__main__":
    main()
