import requests
import re
import urllib3
import json

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

session = requests.Session()
session.verify = False

# Step 1: Get the main page to retrieve form_build_id
print("Fetching main page to get form_build_id...")
url = "https://aptel.gov.in/en/casestatusapi/tab4"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
resp = session.get(url, headers=headers)
html = resp.text

# Extract form_build_id using regex
form_build_id_match = re.search(r'name="form_build_id" value="([^"]+)"', html)
if not form_build_id_match:
    print("Could not find form_build_id on page!")
    # Let's search all input fields
    print("Inputs found:")
    print(re.findall(r'<input[^>]+>', html))
    exit(1)

form_build_id = form_build_id_match.group(1)
print(f"Found form_build_id: {form_build_id}")

# Step 2: Post to AJAX endpoint
ajax_url = "https://aptel.gov.in/en/casestatusapi/tab4?ajax_form=1"
payload = {
    "form_build_id": form_build_id,
    "form_id": "case_order_date_wise_form",
    "from_date": "2023-01-01",
    "to_date": "2024-01-01",
    "op": "Submit",
    "_triggering_element_name": "op",
    "_triggering_element_value": "Submit"
}

headers.update({
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "https://aptel.gov.in",
    "Referer": "https://aptel.gov.in/en/casestatusapi/tab4"
})

print("Posting AJAX request to", ajax_url)
post_resp = session.post(ajax_url, data=payload, headers=headers)
print("Response status:", post_resp.status_code)
print("Response headers:", dict(post_resp.headers))

try:
    data = post_resp.json()
    print("Response JSON length:", len(data))
    # Write to a file for examination
    with open("ajax_response.json", "w") as f:
        json.dump(data, f, indent=2)
    print("Response JSON saved to ajax_response.json")
    for i, item in enumerate(data):
        print(f"Item {i}: command={item.get('command')}, selector={item.get('selector')}")
except Exception as e:
    print("Failed to parse JSON response:", e)
    print("Response text preview:", post_resp.text[:500])
