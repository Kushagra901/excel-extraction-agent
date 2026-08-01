"""
Canonical schema definition.

This is the single source of truth for "what fields do we know about" and
"what messy header text usually means that field". Extend this dictionary
to teach the Schema Mapping Agent about new field types or new synonyms --
you should rarely need to touch any other file to support a new kind of
spreadsheet.

Each canonical field also declares a `value_type`, which tells the Data
Cleaning Agent which cleaning function to apply.
"""

from __future__ import annotations

CANONICAL_SCHEMA: dict[str, dict] = {
    "id": {
        "value_type": "text",
        "synonyms": [
            "id", "ID", "record id", "ref", "reference", "reference number",
            "customer id", "client id", "order id", "invoice id", "sku",
            "index", "row id", "no.", "no", "#",
        ],
    },
    "full_name": {
        "value_type": "text",
        "synonyms": [
            "name", "full name", "customer name", "client name", "contact name",
            "person", "employee name", "student name", "first and last name",
            "client", "customer", "contact",
        ],
    },
    "email": {
        "value_type": "email",
        "synonyms": [
            "email", "e-mail", "email address", "e-mail address", "contact email",
            "mail",
        ],
    },
    "phone": {
        "value_type": "phone",
        "synonyms": [
            "phone", "phone number", "contact number", "mobile", "mobile number",
            "telephone", "cell", "cell phone", "tel",
        ],
    },
    "amount": {
        "value_type": "currency",
        "synonyms": [
            "amount", "total", "price", "cost", "value", "amount due",
            "total amount", "invoice amount", "sale price", "revenue",
            "unit price", "subtotal", "grand total",
        ],
    },
    "date": {
        "value_type": "date",
        "synonyms": [
            "date", "created date", "order date", "invoice date", "timestamp",
            "date of birth", "dob", "due date", "start date", "end date",
            "transaction date", "date created", "date modified",
        ],
    },
    "address": {
        "value_type": "text",
        "synonyms": [
            "address", "street address", "mailing address", "location",
            "billing address", "shipping address",
        ],
    },
    "company": {
        "value_type": "text",
        "synonyms": [
            "company", "company name", "organization", "employer", "business name",
        ],
    },
    "status": {
        "value_type": "text",
        "synonyms": [
            "status", "state", "order status", "payment status", "stage",
        ],
    },
    "quantity": {
        "value_type": "number",
        "synonyms": [
            "quantity", "qty", "count", "units", "number of items",
        ],
    },
    "notes": {
        "value_type": "text",
        "synonyms": [
            "notes", "comments", "remarks", "description", "details",
        ],
    },
}

# Values that should be treated as "no data" rather than a real string.
NULL_PLACEHOLDERS = {
    "", "n/a", "na", "none", "null", "-", "--", "tbd", "unknown", "?",
    "pending", "n.a.", "nil",
}
