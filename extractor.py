import pdfplumber
import pandas as pd
import re
import os


# Different naming variations for line items
TARGET_LINE_ITEMS = {
    "Revenue": ["revenue", "sales", "total income"],
    "Cost of Goods Sold": ["cost of goods sold", "cogs"],
    "Operating Expenses": ["operating expenses", "operating costs"],
    "Net Income": ["net income", "profit after tax", "net profit"]
}


def extract_text_from_pdf(file_path):
    """
    Extract text from PDF using pdfplumber.
    """
    text = ""
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text.lower() + "\n"
    return text


def find_line_item_values(text, keywords):
    """
    Extract multiple numeric values following a matched financial line item.
    """
    for keyword in keywords:
        pattern = rf"{keyword}.*?((?:[\d,]+\.?\d*\s+)+)"
        match = re.search(pattern, text)
        if match:
            numbers = re.findall(r"[\d,]+\.?\d*", match.group(1))
            return numbers
    return None


def detect_currency_and_unit(text):
    """
    Detect reporting currency and units.
    """
    currency = "Unknown"
    unit = "Units"

    # Currency detection
    if "$" in text:
        currency = "USD ($)"
    elif "₹" in text:
        currency = "INR (₹)"
    elif "€" in text:
        currency = "EUR (€)"
    elif "£" in text:
        currency = "GBP (£)"

    # Unit detection
    if "million" in text:
        unit = "Millions"
    elif "thousand" in text:
        unit = "Thousands"
    elif "crore" in text:
        unit = "Crores"
    elif "billion" in text:
        unit = "Billions"

    return currency, unit


def detect_years(text):
    """
    Detect financial reporting years like 2023, 2022, etc.
    """
    years = re.findall(r"\b(20\d{2})\b", text)
    unique_years = sorted(list(set(years)), reverse=True)
    return unique_years[:4]  # limit to max 4 years


def process_financial_statement(file_path, output_folder):
    """
    Main processing function called from FastAPI.
    """

    # Extract raw text
    text = extract_text_from_pdf(file_path)

    # Detect metadata
    currency, unit = detect_currency_and_unit(text)
    years = detect_years(text)

    structured_data = []

    # Extract financial values
    for item, keywords in TARGET_LINE_ITEMS.items():
        values = find_line_item_values(text, keywords)

        if values:
            structured_data.append([item] + values)
        else:
            structured_data.append([item, "Not Found"])

    # Determine column structure
    if structured_data and len(structured_data[0]) > 1:
        num_value_columns = len(structured_data[0]) - 1

        if years:
            column_names = ["Line Item"] + years[:num_value_columns]
        else:
            column_names = ["Line Item"] + [
                f"Value {i}" for i in range(1, num_value_columns + 1)
            ]
    else:
        column_names = ["Line Item", "Value"]

    df = pd.DataFrame(structured_data, columns=column_names)

    # Add metadata at top
    metadata = pd.DataFrame([
        ["Currency", currency],
        ["Unit", unit],
        []
    ])

    final_df = pd.concat([metadata, df], ignore_index=True)

    # Save Excel
    output_file = os.path.join(output_folder, "income_statement.xlsx")
    final_df.to_excel(output_file, index=False, header=False)

    return output_file