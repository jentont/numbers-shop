"""Страны: ISO-3 (как в LZT) → (ISO-2 для флага, телефонный код, русское имя).

Имена на остальных 29 языках витрина берёт из Intl.DisplayNames по ISO-2,
поэтому здесь только русские — для бота и админки.
"""
from __future__ import annotations

COUNTRIES: dict[str, tuple[str, str, str]] = {
    "RUS": ("RU", "7", "Россия"), "UKR": ("UA", "380", "Украина"), "KAZ": ("KZ", "7", "Казахстан"),
    "BLR": ("BY", "375", "Беларусь"), "UZB": ("UZ", "998", "Узбекистан"), "KGZ": ("KG", "996", "Киргизия"),
    "TJK": ("TJ", "992", "Таджикистан"), "GEO": ("GE", "995", "Грузия"), "ARM": ("AM", "374", "Армения"),
    "AZE": ("AZ", "994", "Азербайджан"), "MDA": ("MD", "373", "Молдова"), "USA": ("US", "1", "США"),
    "CAN": ("CA", "1", "Канада"), "GBR": ("GB", "44", "Великобритания"), "DEU": ("DE", "49", "Германия"),
    "FRA": ("FR", "33", "Франция"), "ITA": ("IT", "39", "Италия"), "ESP": ("ES", "34", "Испания"),
    "PRT": ("PT", "351", "Португалия"), "NLD": ("NL", "31", "Нидерланды"), "POL": ("PL", "48", "Польша"),
    "CZE": ("CZ", "420", "Чехия"), "ROU": ("RO", "40", "Румыния"), "TUR": ("TR", "90", "Турция"),
    "ISR": ("IL", "972", "Израиль"), "ARE": ("AE", "971", "ОАЭ"), "SAU": ("SA", "966", "Саудовская Аравия"),
    "EGY": ("EG", "20", "Египет"), "NGA": ("NG", "234", "Нигерия"), "KEN": ("KE", "254", "Кения"),
    "ZAF": ("ZA", "27", "ЮАР"), "GHA": ("GH", "233", "Гана"), "IND": ("IN", "91", "Индия"),
    "PAK": ("PK", "92", "Пакистан"), "BGD": ("BD", "880", "Бангладеш"), "LKA": ("LK", "94", "Шри-Ланка"),
    "NPL": ("NP", "977", "Непал"), "IDN": ("ID", "62", "Индонезия"), "PHL": ("PH", "63", "Филиппины"),
    "VNM": ("VN", "84", "Вьетнам"), "THA": ("TH", "66", "Таиланд"), "MYS": ("MY", "60", "Малайзия"),
    "MMR": ("MM", "95", "Мьянма"), "KHM": ("KH", "855", "Камбоджа"), "LAO": ("LA", "856", "Лаос"),
    "CHN": ("CN", "86", "Китай"), "JPN": ("JP", "81", "Япония"), "KOR": ("KR", "82", "Южная Корея"),
    "BRA": ("BR", "55", "Бразилия"), "MEX": ("MX", "52", "Мексика"), "ARG": ("AR", "54", "Аргентина"),
    "COL": ("CO", "57", "Колумбия"), "PER": ("PE", "51", "Перу"), "CHL": ("CL", "56", "Чили"),
    "AUS": ("AU", "61", "Австралия"),
}

_BY_ISO2 = {v[0]: k for k, v in COUNTRIES.items()}
_BY_NAME = {v[2].lower(): k for k, v in COUNTRIES.items()}
_EN = {"russia": "RUS", "ukraine": "UKR", "kazakhstan": "KAZ", "united states": "USA", "usa": "USA",
       "united kingdom": "GBR", "germany": "DEU", "india": "IND", "indonesia": "IDN", "turkey": "TUR"}


def to_iso3(raw: str) -> str:
    """LZT отдаёт страну по-разному: RUS, RU или словом. Приводим к ISO-3."""
    s = raw.strip()
    if not s:
        return ""
    up = s.upper()
    if len(up) == 3 and up.isalpha():
        return up
    if len(up) == 2 and up.isalpha():
        return _BY_ISO2.get(up, "")
    low = s.lower()
    return _BY_NAME.get(low) or _EN.get(low, "")


def iso2(c3: str) -> str:
    return COUNTRIES.get(c3, ("",))[0]


def flag(c3: str) -> str:
    code = iso2(c3)
    if len(code) != 2:
        return "🏳"
    return "".join(chr(0x1F1E6 + ord(ch) - 65) for ch in code)


def dial(c3: str) -> str:
    return COUNTRIES.get(c3, ("", "", ""))[1]


def name_ru(c3: str) -> str:
    return COUNTRIES.get(c3, ("", "", c3))[2]
