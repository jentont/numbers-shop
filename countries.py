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


# Ещё страны, которые часто встречаются на маркете (ISO-3: ISO-2, код, имя).
COUNTRIES.update({
    "TKM": ("TM", "993", "Туркменистан"), "AUT": ("AT", "43", "Австрия"), "BEL": ("BE", "32", "Бельгия"),
    "CHE": ("CH", "41", "Швейцария"), "SWE": ("SE", "46", "Швеция"), "NOR": ("NO", "47", "Норвегия"),
    "DNK": ("DK", "45", "Дания"), "FIN": ("FI", "358", "Финляндия"), "IRL": ("IE", "353", "Ирландия"),
    "GRC": ("GR", "30", "Греция"), "HUN": ("HU", "36", "Венгрия"), "BGR": ("BG", "359", "Болгария"),
    "SRB": ("RS", "381", "Сербия"), "HRV": ("HR", "385", "Хорватия"), "SVK": ("SK", "421", "Словакия"),
    "SVN": ("SI", "386", "Словения"), "LTU": ("LT", "370", "Литва"), "LVA": ("LV", "371", "Латвия"),
    "EST": ("EE", "372", "Эстония"), "BIH": ("BA", "387", "Босния и Герцеговина"), "MKD": ("MK", "389", "Северная Македония"),
    "ALB": ("AL", "355", "Албания"), "CYP": ("CY", "357", "Кипр"), "MNE": ("ME", "382", "Черногория"),
    "MNG": ("MN", "976", "Монголия"), "HKG": ("HK", "852", "Гонконг"), "TWN": ("TW", "886", "Тайвань"),
    "SGP": ("SG", "65", "Сингапур"), "IRQ": ("IQ", "964", "Ирак"), "IRN": ("IR", "98", "Иран"),
    "AFG": ("AF", "93", "Афганистан"), "JOR": ("JO", "962", "Иордания"), "LBN": ("LB", "961", "Ливан"),
    "SYR": ("SY", "963", "Сирия"), "KWT": ("KW", "965", "Кувейт"), "QAT": ("QA", "974", "Катар"),
    "OMN": ("OM", "968", "Оман"), "BHR": ("BH", "973", "Бахрейн"), "YEM": ("YE", "967", "Йемен"),
    "MAR": ("MA", "212", "Марокко"), "DZA": ("DZ", "213", "Алжир"), "TUN": ("TN", "216", "Тунис"),
    "LBY": ("LY", "218", "Ливия"), "ETH": ("ET", "251", "Эфиопия"), "TZA": ("TZ", "255", "Танзания"),
    "UGA": ("UG", "256", "Уганда"), "CMR": ("CM", "237", "Камерун"), "CIV": ("CI", "225", "Кот-д’Ивуар"),
    "SEN": ("SN", "221", "Сенегал"), "AGO": ("AO", "244", "Ангола"), "MOZ": ("MZ", "258", "Мозамбик"),
    "ZMB": ("ZM", "260", "Замбия"), "ZWE": ("ZW", "263", "Зимбабве"), "SDN": ("SD", "249", "Судан"),
    "MDG": ("MG", "261", "Мадагаскар"), "NZL": ("NZ", "64", "Новая Зеландия"), "VEN": ("VE", "58", "Венесуэла"),
    "ECU": ("EC", "593", "Эквадор"), "BOL": ("BO", "591", "Боливия"), "PRY": ("PY", "595", "Парагвай"),
    "URY": ("UY", "598", "Уругвай"), "DOM": ("DO", "1", "Доминиканская Республика"), "GTM": ("GT", "502", "Гватемала"),
    "HND": ("HN", "504", "Гондурас"), "SLV": ("SV", "503", "Сальвадор"), "NIC": ("NI", "505", "Никарагуа"),
    "CRI": ("CR", "506", "Коста-Рика"), "PAN": ("PA", "507", "Панама"), "CUB": ("CU", "53", "Куба"),
    "JAM": ("JM", "1", "Ямайка"), "HTI": ("HT", "509", "Гаити"),
})

#: Регионы для фильтров витрины и текстовой версии — одна таблица на всех.
REGIONS = {
    "cis": "RUS UKR KAZ BLR UZB KGZ TJK TKM GEO ARM AZE MDA".split(),
    "eu": ("GBR DEU FRA ITA ESP PRT NLD POL CZE ROU AUT BEL CHE SWE NOR DNK FIN IRL GRC HUN BGR SRB HRV SVK "
           "SVN LTU LVA EST BIH MKD ALB CYP MNE").split(),
    "asia": ("TUR ISR ARE SAU IND PAK BGD LKA NPL IDN PHL VNM THA MYS MMR KHM LAO CHN JPN KOR MNG HKG TWN SGP "
             "IRQ IRN AFG JOR LBN SYR KWT QAT OMN BHR YEM").split(),
    "am": "USA CAN BRA MEX ARG COL PER CHL VEN ECU BOL PRY URY DOM GTM HND SLV NIC CRI PAN CUB JAM HTI".split(),
    "af": ("EGY NGA KEN ZAF GHA AUS NZL MAR DZA TUN LBY ETH TZA UGA CMR CIV SEN AGO MOZ ZMB ZWE SDN "
           "MDG").split(),
}

_BY_ISO2 = {v[0]: k for k, v in COUNTRIES.items()}
_BY_NAME = {v[2].lower(): k for k, v in COUNTRIES.items()}
_EN_NAMES = {
    "RUS": "Russia", "UKR": "Ukraine", "KAZ": "Kazakhstan", "BLR": "Belarus", "UZB": "Uzbekistan",
    "KGZ": "Kyrgyzstan", "TJK": "Tajikistan", "GEO": "Georgia", "ARM": "Armenia", "AZE": "Azerbaijan",
    "MDA": "Moldova", "USA": "United States", "CAN": "Canada", "GBR": "United Kingdom", "DEU": "Germany",
    "FRA": "France", "ITA": "Italy", "ESP": "Spain", "PRT": "Portugal", "NLD": "Netherlands", "POL": "Poland",
    "CZE": "Czechia", "ROU": "Romania", "TUR": "Turkey", "ISR": "Israel", "ARE": "United Arab Emirates",
    "SAU": "Saudi Arabia", "EGY": "Egypt", "NGA": "Nigeria", "KEN": "Kenya", "ZAF": "South Africa", "GHA": "Ghana",
    "IND": "India", "PAK": "Pakistan", "BGD": "Bangladesh", "LKA": "Sri Lanka", "NPL": "Nepal", "IDN": "Indonesia",
    "PHL": "Philippines", "VNM": "Vietnam", "THA": "Thailand", "MYS": "Malaysia", "MMR": "Myanmar",
    "KHM": "Cambodia", "LAO": "Laos", "CHN": "China", "JPN": "Japan", "KOR": "South Korea", "BRA": "Brazil",
    "MEX": "Mexico", "ARG": "Argentina", "COL": "Colombia", "PER": "Peru", "CHL": "Chile", "AUS": "Australia",
    "MAR": "Morocco", "DZA": "Algeria", "TUN": "Tunisia", "IRQ": "Iraq", "IRN": "Iran", "AFG": "Afghanistan",
    "ETH": "Ethiopia", "TZA": "Tanzania", "UGA": "Uganda", "CMR": "Cameroon", "VEN": "Venezuela",
    "ECU": "Ecuador", "BOL": "Bolivia", "GRC": "Greece", "HUN": "Hungary", "SWE": "Sweden", "AUT": "Austria",
    "BEL": "Belgium", "CHE": "Switzerland", "NZL": "New Zealand", "SGP": "Singapore", "HKG": "Hong Kong",
}
_EN = {v.lower(): k for k, v in _EN_NAMES.items()} | {
    "usa": "USA", "us": "USA", "united states of america": "USA", "uk": "GBR", "great britain": "GBR",
    "england": "GBR", "russian federation": "RUS", "czech republic": "CZE", "turkiye": "TUR", "türkiye": "TUR",
    "uae": "ARE", "korea": "KOR", "republic of korea": "KOR", "viet nam": "VNM", "moldova, republic of": "MDA",
}


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
    low = s.lower().removeprefix("the ").strip()
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
