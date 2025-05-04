"""
This module processes receipt images, extracts text with pytesseract,
and parses dish names with corresponding prices.
"""

# pylint: disable=no-member

import re
import difflib
import cv2
import pytesseract
import numpy
from db import store_receipt_info


def process_image(raw_img):
    """Convert the input image to grayscale for better OCR performance."""
    processed_img = cv2.cvtColor(
        raw_img, cv2.COLOR_BGR2GRAY
    )  # pylint: disable=no-member

    return processed_img


def sanitize_string(dish):
    """Remove unnecessary characters from dish name"""
    index_start = 0
    while not dish[index_start].isalnum():
        index_start += 1

    index_end = -1
    while not dish[index_end].isalpha():
        index_end -= 1

    # Adjust end index if there is no invalid characters at the end of string
    if index_end == -1:
        return dish[index_start : len(dish)]

    return dish[index_start : index_end + 1]


def filter_dishes(entries):
    """Filter dishes from subtotal, tax, tips, grand total, and other charges"""
    keywords = [
        "subtotal",
        "sub-total",
        "tax",
        "tip",
        "tips",
        "service",
        "charge",
        "card",
        "fee",
        "total",
    ]
    dishes = []
    charges = []

    for item in entries:
        dish_name = item["dish"].strip().lower()
        if not any(keyword in dish_name for keyword in keywords):
            dishes.append(item)
        else:
            charges.append(item)

    return dishes, charges


def parse_processed_lines(lines):
    """Separate and parse dishes and prices from lines"""
    pattern = re.compile(r"([\d]+[,.][\d]{2})\s*$")
    entries = []

    for line in lines:
        match = pattern.search(line)
        if match:
            price_string = match.group(1).replace(",", ".")  # Replace , with .
            try:
                price_float = float(price_string)
            except ValueError:
                continue

            dish = line[: match.start()].strip()  # Extract dish for each price
            if dish:
                dish = sanitize_string(dish)

                entries.append({"dish": dish, "price": price_float})

    return entries


def normalize_text(text):
    """Removes commas, colons, dashes, and extra spaces from text"""
    # Remove dashes, commas, colons, and extra spaces.
    text = text.lower()
    text = re.sub(r"[-:,]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_dictionary_list(dictionary_list):
    """Converts a list of dictionaries into a single dictionary"""
    dictionary = {}
    for entry in dictionary_list:
        key = normalize_text(entry["dish"])
        dictionary[key] = entry["price"]
    return dictionary


# user_input data format:
# user_input = {
#   "receipt": (img),
#   "tip": (float),
#   "num-people": (int),
#   "people": [{"name": "", "items": ""}, ...]
# }
def calculate_charge_per_person(
    user_input, dish_entries, charge_entries
):  # pylint: disable=too-many-locals
    """Calculate the total amount per person according to the provided bill"""
    # Convert charge_entries and dish_prices list of dictionaries into a single dictionary

    charges_dict = normalize_dictionary_list(charge_entries)
    dish_prices = normalize_dictionary_list(dish_entries)

    # Get the subtotal and tax from the receipt
    subtotal_from_receipt = charges_dict.get("subtotal")
    tax_from_receipt = charges_dict.get("tax")

    print("Subtotal from receipt:", subtotal_from_receipt)
    print("Tax from receipt:", tax_from_receipt)

    # Extract tip from user input
    tip = float(user_input.get("tip", 0.0))

    # Get the list of people ordering
    people = user_input.get("people", [])

    # Build a mapping of dishes to the list of people who ordered them
    dish_consumers = {}
    for person in people:
        name = person["name"]
        # Convert the comma-separated items into a list of normalized dish names
        items_list = [
            item.strip().lower() for item in person.get("items", "").split(",")
        ]
        for dish in items_list:
            if dish not in dish_consumers:
                dish_consumers[dish] = []
            dish_consumers[dish].append(name)

    # Initialize base total for each person
    person_totals = {person["name"]: 0.0 for person in people}

    # For each dish that people ordered, add its cost share to each person who had the dish
    for dish, consumers in dish_consumers.items():
        matches = difflib.get_close_matches(dish, dish_prices.keys(), n=1, cutoff=0.6)
        if matches:
            matched_key = matches[0]
            price = dish_prices[matched_key]
            split_price = price / len(consumers)
            for name in consumers:
                person_totals[name] += split_price
        else:
            print(f"No close match found for: {dish}")

    # Calculate each person's share of the tip and tax proportionally
    for name in person_totals:
        base = person_totals[name]

        # Initialize tip_share and tax_share (linting)
        tip_share = 0.0
        tax_share = 0.0
        if subtotal_from_receipt is not None and subtotal_from_receipt > 0:
            tip_share = (base / subtotal_from_receipt) * tip
            tax_share = (base / subtotal_from_receipt) * tax_from_receipt
        person_totals[name] = round(base + tip_share + tax_share, 2)

    return person_totals


def process_data(user_input, receipt_file):
    """Reads the image sent by user, processes information, and stores data in DB"""
    file_bytes = numpy.asarray(bytearray(receipt_file.read()), dtype=numpy.uint8)
    img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)

    processed_text = pytesseract.image_to_string(process_image(img))
    processed_lines = parse_processed_lines(processed_text.splitlines())

    filtered_dishes, other_charges = filter_dishes(processed_lines)

    charge_per_person = calculate_charge_per_person(
        user_input, filtered_dishes, other_charges
    )

    charge_id = store_receipt_info(processed_text, charge_per_person)

    return charge_id
