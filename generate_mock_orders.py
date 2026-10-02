"""
Mock Order Generator
====================
Generates realistic fake eBay order data and saves it to mock_orders.json.
Used to test the invoicer without needing real eBay API calls.

Run:
    python3 generate_mock_orders.py
"""

import json
import random
import uuid
from datetime import datetime, timezone, timedelta

# =============================================================================
# CONFIG
# =============================================================================

BUYERS = [
    "Jack98765432345678987",
    "Thom98765432345678987",
    "Jim98765432345678987",
    "Dirk98765432345678987",
    "Helen98765432345678987",
]

VARIANTS = {
    "REGULAR":     (5.00,  25.00),
    "RARE":        (25.01, 75.00),
    "SUPER DUPER": (75.01, 125.00),
}

PLAYERS_BY_TEAM = {
    "Pittsburgh Pirates":    ["Konnor Griffin", "Bubba Chandler", "Edward Florentino", "Seth Hernandez", "Jhostynxon Garcia"],
    "Detroit Tigers":        ["Kevin McGonigle", "Max Clark", "Bryce Rainer", "Josue Briceño"],
    "New York Mets":         ["Nolan McLean", "Carson Benge", "Jonah Tong", "AJ Ewing", "Ryan Clifford"],
    "Milwaukee Brewers":     ["Jesus Made", "Jett Williams", "Brandon Sproat", "Jeferson Quero", "Logan Henderson"],
    "Seattle Mariners":      ["Colt Emerson", "Kade Anderson", "Ryan Sloan", "Jonny Farmelo", "Lazaro Montes"],
    "Philadelphia Phillies": ["Aidan Miller", "Andrew Painter", "Justin Crawford"],
    "St. Louis Cardinals":   ["JJ Wetherholt", "Rainiel Rodriguez", "Liam Doyle", "Jimmy Crooks"],
    "Baltimore Orioles":     ["Samuel Basallo", "Dylan Beavers", "Trey Gibson"],
    "Los Angeles Dodgers":   ["Zyhir Hope", "Mike Sirota", "Eduardo Quintero", "River Ryan", "Alex Freeland"],
    "Minnesota Twins":       ["Walker Jenkins", "Emmanuel Rodriguez", "Kaelen Culpepper", "Charlee Soto"],
    "Miami Marlins":         ["Thomas White", "Robby Snelling", "Joe Mack", "Owen Caissie"],
    "Cleveland Guardians":   ["Chase DeLauter", "Travis Bazzana", "Ralphy Velazquez", "Angel Genao"],
    "Washington Nationals":  ["Eli Willits", "Jarlin Susana", "Harry Ford"],
    "Boston Red Sox":        ["Connelly Early", "Payton Tolle", "Franklin Arias"],
    "Chicago White Sox":     ["Caleb Bonemer", "Braden Montgomery", "Noah Schultz"],
    "Tampa Bay Rays":        ["Brody Hopkins", "Carson Williams", "Theo Gillen"],
    "New York Yankees":      ["George Lombard Jr.", "Carlos Lagrange", "Dax Kilby"],
    "Toronto Blue Jays":     ["Trey Yesavage", "Joseph Parker", "Arjun Nimmala"],
    "Atlanta Braves":        ["JR Ritchie", "Cam Caminiti"],
    "San Diego Padres":      ["Ethan Salas"],
}

TARGET_ORDERS = 500
OUTPUT_FILE   = "mock_orders.json"

# =============================================================================
# ASSIGN TEAMS TO BUYERS
# =============================================================================

def assign_teams():
    teams = list(PLAYERS_BY_TEAM.keys())
    random.shuffle(teams)
    team_to_buyer = {}
    for i, team in enumerate(teams):
        team_to_buyer[team] = BUYERS[i % len(BUYERS)]
    return team_to_buyer

# =============================================================================
# BUILD ORDERS
# =============================================================================

def make_order(buyer, player, team, variant, price, created_at):
    order_id  = f"MOCK-{uuid.uuid4().hex[:12].upper()}"
    item_id   = str(random.randint(100000000000, 999999999999))
    return {
        "orderId":             order_id,
        "orderPaymentStatus":  "PENDING",
        "orderFulfillmentStatus": "NOT_STARTED",
        "creationDate":        created_at.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "buyer": {
            "username": buyer,
            "taxAddress": {
                "email": f"{buyer.lower()[:8]}@testmail.com"
            }
        },
        "lineItems": [
            {
                "lineItemId":  str(random.randint(1000000000, 9999999999)),
                "title":       f"BREAK {player} - {variant} ({team}) Baseball Card",
                "quantity":    1,
                "lineItemCost": {
                    "value":    str(round(price, 2)),
                    "currency": "USD"
                },
                "itemId": item_id,
            }
        ],
        "pricingSummary": {
            "priceSubtotal": {
                "value":    str(round(price, 2)),
                "currency": "USD"
            }
        }
    }


def main():
    print("\n🃏 Mock Order Generator")
    print("=" * 50)

    team_to_buyer = assign_teams()

    # Build full player pool cycling through variants
    all_players = [(p, t) for t, players in PLAYERS_BY_TEAM.items() for p in players]
    variant_names = list(VARIANTS.keys())

    orders = []
    now = datetime.now(timezone.utc)

    for i in range(TARGET_ORDERS):
        player, team   = all_players[i % len(all_players)]
        variant        = variant_names[i % len(variant_names)]
        low, high      = VARIANTS[variant]
        price          = round(random.uniform(low, high), 2)
        buyer          = team_to_buyer[team]
        created_at     = now - timedelta(hours=random.randint(1, 48))
        orders.append(make_order(buyer, player, team, variant, price, created_at))

    # Save
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(orders, f, indent=2)

    # Summary
    from collections import defaultdict
    by_buyer = defaultdict(list)
    for o in orders:
        by_buyer[o["buyer"]["username"]].append(o)

    print(f"\n  Generated {len(orders)} mock orders across {len(by_buyer)} buyers\n")
    print(f"  {'Buyer':<30} {'Orders':>6}  {'Cards':>5}  {'Subtotal':>10}")
    print("  " + "─" * 58)

    for buyer in BUYERS:
        buyer_orders = by_buyer[buyer]
        cards    = sum(li["quantity"] for o in buyer_orders for li in o["lineItems"])
        subtotal = sum(float(li["lineItemCost"]["value"]) for o in buyer_orders for li in o["lineItems"])
        print(f"  {buyer:<30} {len(buyer_orders):>6}  {cards:>5}  ${subtotal:>9.2f}")

    print(f"\n  📊 Saved → {OUTPUT_FILE}")
    print(f"  Next step: python3 ebay_break_invoicer.py")
    print(f"  (Make sure MOCK_MODE = True in the invoicer)\n")


if __name__ == "__main__":
    main()
