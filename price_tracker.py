from tcgplayer import get_raw_price
from ebay_scraper import get_graded_price

# Example list of cards to track
cards_to_track = [
    {"name": "Charizard Holo Base Set", "grading_cost": 20, "profit_threshold": 50},
    {"name": "Blastoise Base Set", "grading_cost": 20, "profit_threshold": 40},
]

def check_card_prices():
    alerts = []
    for card in cards_to_track:
        raw_price = get_raw_price(card["name"])
        graded_price = get_graded_price(card["name"])
        profit = graded_price - raw_price - card["grading_cost"]
        
        if profit >= card["profit_threshold"]:
            alert = (
    f"🔥 Buy Alert: **{card['name']}**\n"
    f"Raw Price: ${raw_price:.2f}\n"
    f"Graded (PSA 10): ${graded_price:.2f}\n"
    f"Estimated Profit: ${profit:.2f} 💰"
)
            alerts.append(alert)
    return alerts