"""
eBay Baseball Card Break — Combined Invoice Script
===================================================
Fetches all unpaid orders, groups by buyer, applies tiered shipping,
and sends combined invoices via Gmail SMTP.

Shipping tiers:
  1-5 cards:   $2.25
  6-10 cards:  $3.75
  11-15 cards: $5.15
  15+ cards:   $6.60

Requirements:
    pip install requests

Run:
    python3 ebay_break_invoicer.py
"""

import requests
import json
import csv
import base64
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone, timedelta
from collections import defaultdict


# =============================================================================
# MODE SELECTION MENU
# =============================================================================

def select_mode():
    print("\n" + "=" * 55)
    print("  eBay Card Break Invoicer")
    print("=" * 55)
    print()
    print("  [1] MOCK MODE")
    print("      Loads mock_orders.json — zero API calls")
    print("      Use this to test grouping & shipping math")
    print()
    print("  [2] SANDBOX MODE")
    print("      Hits eBay Sandbox with your test accounts")
    print("      Sends real emails via Gmail to your +aliases")
    print()
    print("  [3] PRODUCTION MODE")
    print("      Hits your REAL eBay seller account")
    print("      Sends real invoices to real customers")
    print()
    while True:
        choice = input("  Select mode (1/2/3): ").strip()
        if choice == "1":
            return True, True      # MOCK_MODE=True,  TEST_MODE=True
        elif choice == "2":
            return False, True     # MOCK_MODE=False, TEST_MODE=True
        elif choice == "3":
            confirm = input("  Type PRODUCTION to confirm: ").strip()
            if confirm == "PRODUCTION":
                return False, False
            print("  Aborted — returning to menu.")
        else:
            print("  Please enter 1, 2, or 3.")

MOCK_MODE, TEST_MODE = select_mode()


# =============================================================================
# CREDENTIALS
# =============================================================================

import os as _os, json as _json

def _load_keys(filepath, label):
    if not _os.path.exists(filepath):
        print(f"  {filepath} not found.")
        raise SystemExit(1)
    with open(filepath) as _f:
        return _json.load(_f)

def _load_seller_token():
    if not _os.path.exists("sandbox_tokens.json"):
        print("  sandbox_tokens.json not found. Run ebay_sandbox_setup_tokens.py first.")
        raise SystemExit(1)
    with open("sandbox_tokens.json") as _f:
        t = _json.load(_f)
    token = t.get("SELLER", {}).get("refresh_token", "")
    if not token:
        print("  SELLER token missing from sandbox_tokens.json.")
        raise SystemExit(1)
    return token

# Load keys file based on mode
if TEST_MODE or MOCK_MODE:
    _keys             = _load_keys("sandbox_keys.json", "Sandbox")
else:
    _keys             = _load_keys("prod_keys.json", "Production")

GMAIL_USER          = _keys.get("gmail_user", "")
GMAIL_APP_PASSWORD  = _keys.get("gmail_app_password", "")
BUYER_EMAIL_OVERRIDES = _keys.get("buyer_email_overrides", {})

if not MOCK_MODE:
    if TEST_MODE:
        EBAY_CLIENT_ID     = _keys.get("client_id", "")
        EBAY_CLIENT_SECRET = _keys.get("client_secret", "")
        EBAY_REFRESH_TOKEN = _load_seller_token()
    else:
        EBAY_CLIENT_ID     = _keys.get("client_id", "")
        EBAY_CLIENT_SECRET = _keys.get("client_secret", "")
        EBAY_REFRESH_TOKEN = _keys.get("refresh_token", "")
else:
    EBAY_CLIENT_ID = EBAY_CLIENT_SECRET = EBAY_REFRESH_TOKEN = ""


# =============================================================================
# SETTINGS
# =============================================================================

OUTPUT_CSV = "break_payment_log.csv"

DAYS_BACK = 14  # look back 14 days, then filter by break manifest item IDs
print()

SHIPPING_TIERS = [
    (1,  5,  2.25),
    (6,  10, 3.75),
    (11, 15, 5.15),
    (16, 9999, 6.60),
]

def calc_shipping(card_count):
    for low, high, rate in SHIPPING_TIERS:
        if low <= card_count <= high:
            return rate
    return 6.60


# =============================================================================
# ENVIRONMENT
# =============================================================================

def get_env():
    if TEST_MODE:
        return {
            "label":         "SANDBOX (TEST MODE)",
            "api_base":      "https://api.sandbox.ebay.com",
            "token_url":     "https://api.sandbox.ebay.com/identity/v1/oauth2/token",
        }
    else:
        return {
            "label":         "PRODUCTION (LIVE ACCOUNT)",
            "api_base":      "https://api.ebay.com",
            "token_url":     "https://api.ebay.com/identity/v1/oauth2/token",
        }


# =============================================================================
# AUTH
# =============================================================================

def get_access_token(env):
    creds = base64.b64encode(
        f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}".encode()
    ).decode()
    resp = requests.post(
        env["token_url"],
        headers={
            "Authorization": f"Basic {creds}",
            "Content-Type":  "application/x-www-form-urlencoded",
        },
        data={
            "grant_type":    "refresh_token",
            "refresh_token": EBAY_REFRESH_TOKEN,
            "scope":         "https://api.ebay.com/oauth/api_scope https://api.ebay.com/oauth/api_scope/sell.fulfillment https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly https://api.ebay.com/oauth/api_scope/sell.inventory https://api.ebay.com/oauth/api_scope/sell.inventory.readonly",
        },
    )
    resp.raise_for_status()
    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError(f"Auth failed: {resp.text}")
    return token


# =============================================================================
# FETCH ORDERS — Trading API
# =============================================================================

def load_break_manifest():
    """Load item IDs from the last simulator run."""
    if not os.path.exists("break_manifest.json"):
        return None
    with open("break_manifest.json", encoding="utf-8") as f:
        data = json.load(f)
    return set(data.get("item_ids", []))


def fetch_unpaid_orders(env, access_token):
    # Load break manifest to filter orders
    break_item_ids = load_break_manifest()
    if break_item_ids:
        print(f"   Using break_manifest.json — filtering to {len(break_item_ids)} item IDs")
    else:
        print(f"   No break_manifest.json found — fetching all orders from last {DAYS_BACK} days")

    from_date = (datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    to_date   = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<GetOrdersRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{access_token}</eBayAuthToken>
  </RequesterCredentials>
  <CreateTimeFrom>{from_date}</CreateTimeFrom>
  <CreateTimeTo>{to_date}</CreateTimeTo>
  <OrderStatus>Active</OrderStatus>
  <DetailLevel>ReturnAll</DetailLevel>
</GetOrdersRequest>"""

    resp = requests.post(
        f"{env['api_base']}/ws/api.dll",
        headers={
            "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
            "X-EBAY-API-CALL-NAME":           "GetOrders",
            "X-EBAY-API-SITEID":              "0",
            "Content-Type":                   "text/xml",
        },
        data=xml_body.encode("utf-8"),
    )

    import xml.etree.ElementTree as ET
    root  = ET.fromstring(resp.text)
    ns    = {"ns": "urn:ebay:apis:eBLBaseComponents"}
    nodes = root.findall(".//ns:Order", ns)
    print(f"   Found {len(nodes)} total orders")

    orders = []
    for o in nodes:
        order_id   = o.findtext("ns:OrderID", "", ns)
        buyer_id   = o.findtext("ns:BuyerUserID", "", ns)
        pay_status = o.findtext("ns:CheckoutStatus/ns:Status", "", ns)
        total      = o.findtext("ns:Total", "0", ns)

        line_items = []
        for t in o.findall(".//ns:Transaction", ns):
            title = t.findtext("ns:Item/ns:Title", "Unknown", ns)
            price = float(t.findtext("ns:TransactionPrice", "0", ns))
            qty   = int(t.findtext("ns:QuantityPurchased", "1", ns))
            item_id = t.findtext("ns:Item/ns:ItemID", "", ns)
            line_items.append({
                "title":        title,
                "quantity":     qty,
                "lineItemCost": {"value": str(price), "currency": "USD"},
                "itemId":       item_id,
            })

        # Filter to only orders matching this break's item IDs
        order_item_ids = set(li["itemId"] for li in line_items)
        if break_item_ids and not order_item_ids.intersection(break_item_ids):
            continue  # skip orders not in this break

        orders.append({
            "orderId":            order_id,
            "orderPaymentStatus": "PENDING",
            "buyer": {
                "username":   buyer_id,
                "taxAddress": {"email": f"{buyer_id}@sandbox.com"},
            },
            "lineItems": line_items,
            "total":     total,
        })

    print(f"   Matched {len(orders)} orders from this break")
    return orders


# =============================================================================
# GROUP BY BUYER
# =============================================================================

def group_by_buyer(orders):
    buyers = defaultdict(lambda: {
        "username": "",
        "email":    "",
        "orders":   [],
        "items":    [],
        "subtotal": 0.0,
    })
    for order in orders:
        buyer    = order.get("buyer", {})
        username = buyer.get("username", "unknown")
        buyers[username]["username"] = username
        buyers[username]["email"]    = buyer.get("taxAddress", {}).get("email", "")
        buyers[username]["orders"].append(order["orderId"])
        for line in order.get("lineItems", []):
            title = line.get("title", "Unknown Item")
            qty   = line.get("quantity", 1)
            price = float(line.get("lineItemCost", {}).get("value", 0))
            buyers[username]["items"].append({
                "title":      title,
                "quantity":   qty,
                "unit_price": price,
                "line_total": price * qty,
            })
            buyers[username]["subtotal"] += price * qty
    print(f"   Grouped into {len(buyers)} unique buyers")
    return buyers


# =============================================================================
# EMAIL INVOICE — Gmail SMTP
# =============================================================================

def build_invoice_html(username, data, shipping, total_due):
    items_html = ""
    for item in data["items"]:
        items_html += f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #eee;">{item['title']}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:center;">{item['quantity']}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right;">${item['unit_price']:.2f}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right;">${item['line_total']:.2f}</td>
        </tr>"""

    orders_str = "<br>".join(data["orders"])
    date_str   = datetime.now().strftime("%B %d, %Y")

    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,sans-serif;">
  <div style="max-width:620px;margin:30px auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1);">

    <!-- Header -->
    <div style="background:#1a1a2e;padding:28px 32px;">
      <h1 style="margin:0;color:#fff;font-size:22px;">🃏 Card Break Invoice</h1>
      <p style="margin:6px 0 0;color:#aaa;font-size:13px;">{date_str}</p>
    </div>

    <!-- Buyer Info -->
    <div style="padding:24px 32px;border-bottom:1px solid #eee;">
      <p style="margin:0;font-size:15px;">Hi <strong>{username}</strong>,</p>
      <p style="margin:10px 0 0;color:#555;font-size:14px;">
        Thank you for participating in the break! Here is your combined invoice.
        Please make a single payment on eBay covering all items below.
      </p>
      <p style="margin:10px 0 0;color:#888;font-size:12px;">Order IDs: {orders_str}</p>
    </div>

    <!-- Items Table -->
    <div style="padding:24px 32px;">
      <table style="width:100%;border-collapse:collapse;font-size:14px;">
        <thead>
          <tr style="background:#f8f8f8;">
            <th style="padding:10px 12px;text-align:left;color:#333;">Item</th>
            <th style="padding:10px 12px;text-align:center;color:#333;">Qty</th>
            <th style="padding:10px 12px;text-align:right;color:#333;">Price</th>
            <th style="padding:10px 12px;text-align:right;color:#333;">Total</th>
          </tr>
        </thead>
        <tbody>{items_html}
        </tbody>
      </table>
    </div>

    <!-- Totals -->
    <div style="padding:0 32px 24px;">
      <table style="width:100%;font-size:14px;">
        <tr>
          <td style="padding:6px 0;color:#555;">Items subtotal ({len(data['items'])} cards)</td>
          <td style="padding:6px 0;text-align:right;">${data['subtotal']:.2f}</td>
        </tr>
        <tr>
          <td style="padding:6px 0;color:#555;">Combined shipping</td>
          <td style="padding:6px 0;text-align:right;">${shipping:.2f}</td>
        </tr>
        <tr style="font-size:16px;font-weight:bold;border-top:2px solid #1a1a2e;">
          <td style="padding:12px 0;">Total Due</td>
          <td style="padding:12px 0;text-align:right;color:#1a1a2e;">${total_due:.2f}</td>
        </tr>
      </table>
    </div>

    <!-- Shipping Note -->
    <div style="margin:0 32px 24px;padding:14px 16px;background:#f0f7ff;border-radius:6px;border-left:4px solid #3b82f6;">
      <p style="margin:0;font-size:13px;color:#1e40af;">
        <strong>Combined Shipping Applied</strong> — You won {len(data['items'])} card(s) so your shipping rate is <strong>${shipping:.2f}</strong>.
        Please pay the total amount of <strong>${total_due:.2f}</strong> on eBay.
      </p>
    </div>

    <!-- Footer -->
    <div style="padding:20px 32px;background:#f8f8f8;border-top:1px solid #eee;">
      <p style="margin:0;font-size:12px;color:#999;text-align:center;">
        Questions? Reply to this email. Thank you for your business!
      </p>
    </div>

  </div>
</body>
</html>"""


def send_gmail_invoice(username, data, shipping, total_due, test_mode):
    """Send invoice email via Gmail SMTP."""
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        return False, "Gmail credentials not configured in keys file"

    # Check for explicit email override for this buyer (case-insensitive)
    lower_overrides = {k.lower(): v for k, v in BUYER_EMAIL_OVERRIDES.items()}
    to_email = lower_overrides.get(username.lower())
    if not to_email and test_mode:
        # Fall back to +alias
        parts    = GMAIL_USER.split("@")
        to_email = f"{parts[0]}+{username[:12]}@{parts[1]}"
    elif not to_email:
        to_email = data["email"]

    subject    = f"🃏 Your Card Break Invoice — {len(data['items'])} card(s) | ${total_due:.2f} due"
    html_body  = build_invoice_html(username, data, shipping, total_due)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"Card Break Seller <{GMAIL_USER}>"
    msg["To"]      = to_email
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, to_email, msg.as_string())
        return True, to_email
    except Exception as e:
        return False, str(e)


# =============================================================================
# PAYMENT TRACKING CSV
# =============================================================================

def write_tracking_csv(buyers_data, filepath):
    rows = []
    for username, data in buyers_data.items():
        card_count = sum(i["quantity"] for i in data["items"])
        shipping   = calc_shipping(card_count)
        total_due  = round(data["subtotal"] + shipping, 2)
        item_titles = " | ".join(f"{i['title']} x{i['quantity']}" for i in data["items"])
        rows.append({
            "Buyer Username": username,
            "Email":          data["email"],
            "Orders":         ", ".join(data["orders"]),
            "Cards Won":      card_count,
            "Shipping Tier":  f"${shipping:.2f}",
            "Items Subtotal": f"${data['subtotal']:.2f}",
            "Total Due":      f"${total_due:.2f}",
            "Items":          item_titles,
            "Invoice Sent":   datetime.now().strftime("%Y-%m-%d %H:%M"),
            "Paid?":          "NO",
            "Notes":          "",
        })
    rows.sort(key=lambda r: float(r["Total Due"].replace("$", "")), reverse=True)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n   Payment log saved -> {filepath}")


# =============================================================================
# SUMMARY
# =============================================================================

def print_summary(buyers_data):
    print("\n" + "=" * 65)
    print("  BREAK INVOICE SUMMARY")
    print("=" * 65)
    print(f"  {'Buyer':<30} {'Cards':>5}  {'Subtotal':>10}  {'Ship':>6}  {'Total':>9}")
    print("  " + "-" * 62)
    grand_total = 0.0
    for username, data in buyers_data.items():
        cards    = sum(i["quantity"] for i in data["items"])
        shipping = calc_shipping(cards)
        total    = data["subtotal"] + shipping
        grand_total += total
        print(f"  {username:<30} {cards:>5}  ${data['subtotal']:>9.2f}  ${shipping:>5.2f}  ${total:>8.2f}")
    print("  " + "-" * 62)
    print(f"  {'TOTAL':<30}        {'':>10}  {'':>6}  ${grand_total:>8.2f}")
    print("=" * 65)
    print("\n  Shipping Tiers:")
    print("    1-5 cards:   $2.25")
    print("    6-10 cards:  $3.75")
    print("    11-15 cards: $5.15")
    print("    15+ cards:   $6.60")


# =============================================================================
# MAIN
# =============================================================================

def main():
    env = get_env()
    print(f"\n  Mode: {env['label']}")
    if TEST_MODE:
        print(f"  Emails will be sent to your own +alias addresses (not real buyers)")
    print()

    # Fetch orders
    if MOCK_MODE:
        mock_file = "mock_orders.json"
        if not os.path.exists(mock_file):
            print(f"  mock_orders.json not found. Run generate_mock_orders.py first.")
            return
        with open(mock_file, encoding="utf-8") as f:
            orders = json.load(f)
        print(f"  Loaded {len(orders)} orders from {mock_file}")
    else:
        access_token = get_access_token(env)
        print(f"  Authenticated")
        orders = fetch_unpaid_orders(env, access_token)

    if not orders:
        print("  No unpaid orders found. All caught up!")
        return

    buyers = group_by_buyer(orders)
    print_summary(buyers)
    print(f"\n  Total buyers to invoice: {len(buyers)}")

    if TEST_MODE:
        print(f"\n  NOTE: Emails will go to:")
        lower_overrides = {k.lower(): v for k, v in BUYER_EMAIL_OVERRIDES.items()}
        parts = GMAIL_USER.split("@")
        for username in buyers:
            override = lower_overrides.get(username.lower())
            email    = override if override else f"{parts[0]}+{username[:12]}@{parts[1]}"
            tag      = "" if override else " (alias fallback)"
            print(f"    {username[:35]} → {email}{tag}")

    confirm = input("\n  Send invoices to all buyers? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("  Aborted. No invoices sent.")
        return

    # Send emails
    print("\n  Sending invoice emails...")
    for username, data in buyers.items():
        cards     = sum(i["quantity"] for i in data["items"])
        shipping  = calc_shipping(cards)
        total_due = round(data["subtotal"] + shipping, 2)

        print(f"\n  -> {username}  ({cards} cards, ${total_due:.2f} due)")

        if MOCK_MODE:
            print(f"     [MOCK] Invoice not sent")
        else:
            ok, result = send_gmail_invoice(username, data, shipping, total_due, TEST_MODE)
            if ok:
                print(f"     Email sent -> {result}")
            else:
                print(f"     Failed: {result}")

    write_tracking_csv(buyers, OUTPUT_CSV)
    print(f"\n  Done! Check your Gmail for the invoice emails.")


if __name__ == "__main__":
    main()
