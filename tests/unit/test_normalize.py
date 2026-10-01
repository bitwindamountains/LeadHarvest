import pytest

from leadharvest.clean.normalize import (
    city_key,
    is_shared_domain,
    name_key,
    normalize_email,
    normalize_phones,
    normalize_url,
    registered_domain,
    split_website,
    street_key,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0917 123 4567", ["+639171234567"]),
        ("+63 917-123-4567", ["+639171234567"]),
        ("(02) 8123-4567", ["+63281234567"]),
        ("12345", []),
        ("(02) 8123-4567/68", ["+63281234567", "+63281234568"]),
        ("(02) 8123-4567 / 8765-4321", ["+63281234567", "+63287654321"]),
        ("0917-123-4567; (02) 8888-1234", ["+639171234567", "+63288881234"]),
        ("0917 123 4567, 0917 123 4567", ["+639171234567"]),
        ("", []),
    ],
)
def test_normalize_phones(raw: str, expected: list[str]) -> None:
    assert normalize_phones(raw, "PH") == expected


def test_normalize_phones_accepts_list() -> None:
    assert normalize_phones(["0917 123 4567", "(02) 8123-4567"]) == [
        "+639171234567",
        "+63281234567",
    ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("www.Clinic.com.ph", "https://www.clinic.com.ph"),
        ("http://clinic.ph/", "http://clinic.ph"),
        (
            "https://clinic.ph/contact/?utm_source=fb&fbclid=1&id=2",
            "https://clinic.ph/contact?id=2",
        ),
        ("https://clinic.ph/?gclid=x", "https://clinic.ph"),
        ("ftp://clinic.ph", None),
        ("mailto:info@clinic.ph", None),
        ("not a url", None),
        ("localhost", None),
        (None, None),
    ],
)
def test_normalize_url(raw: str | None, expected: str | None) -> None:
    assert normalize_url(raw) == expected


def test_social_website_moves_to_social_field() -> None:
    assert split_website("https://www.facebook.com/SmileClinicPH/") == (
        None,
        {"facebook": "https://www.facebook.com/SmileClinicPH"},
    )
    assert split_website("instagram.com/smile") == (
        None,
        {"instagram": "https://instagram.com/smile"},
    )
    assert split_website("https://smile.ph") == ("https://smile.ph", {})


def test_registered_domain_handles_ph_suffixes_and_www() -> None:
    assert registered_domain("https://www.clinic.com.ph/x") == "clinic.com.ph"
    assert registered_domain("https://clinic.com.ph") == "clinic.com.ph"
    assert registered_domain("https://shop.clinic.ph") == "clinic.ph"


def test_shared_hosting_domains_are_flagged() -> None:
    for url in (
        "https://smile.wixsite.com/x",
        "https://smile.blogspot.com",
        "https://x.business.site",
    ):
        assert is_shared_domain(registered_domain(url))
    assert not is_shared_domain("clinic.com.ph")


def test_name_key() -> None:
    assert name_key("Smile Dental Clinic, Inc.") == "smile dental clinic"
    assert name_key("SMILE DENTAL CLINIC CORP") == "smile dental clinic"
    assert name_key("Niño's Café & Co.") == "nino s cafe and"
    assert name_key("Co") == "co"


def test_street_key_expands_and_drops_units() -> None:
    assert street_key("Unit 5, 2/F Ayala Ave.") == "ayala avenue"
    assert street_key("Rizal St.") == "rizal street"
    assert street_key("3rd Floor, Paseo de Roxas") == "paseo de roxas"
    assert street_key(None) is None


def test_city_key() -> None:
    assert city_key("City of Makati") == city_key("Makati City") == city_key("makati") == "makati"
    assert city_key("") is None


def test_normalize_email() -> None:
    assert normalize_email("mailto:Info@Clinic.PH?subject=Hi") == "info@clinic.ph"
    assert normalize_email("not-an-email") is None
