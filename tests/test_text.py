"""Payee, description and notes as ING's app lists an entry. Every value here is invented, in the shape ING sends."""

from ing_fints.text import Cleaned, clean

CARD = "NR XXXX 1234 MUSTERSTADT DEKAUFUMSATZ01.11 9.99123456ARN12345678901234567890123"


def raw(name="", purpose="", posting_text="Gutschrift"):
    return {"applicant_name": name, "purpose": purpose, "posting_text": posting_text}


def test_a_card_payment_reads_as_the_merchant_and_keeps_the_purpose_as_notes():
    assert clean(raw("VISA BAUMARKT MUSTER", CARD, "Lastschrifteinzug")) == Cleaned("BAUMARKT MUSTER", "BAUMARKT MUSTER", CARD)


def test_visa_glued_to_the_merchant():
    assert clean(raw("VISABAUMARKT MUSTER       ", CARD, "Lastschrifteinzug")).description == "BAUMARKT MUSTER"


def test_the_description_keeps_the_terminal_s_name_and_the_payee_is_one_per_merchant():
    def card(name):
        cleaned = clean(raw(name, CARD, "Lastschrifteinzug"))
        return cleaned.payee, cleaned.description

    assert card("VISA AMZN MKTP DE*AB12CD34E") == ("AMZN MKTP DE", "AMZN MKTP DE*AB12CD34E")
    assert card("VISA AMAZON* X12Y34Z56") == ("AMAZON", "AMAZON* X12Y34Z56")
    assert card("VISAXYZ*STADT APOTHEKE     ") == ("STADT APOTHEKE", "XYZ*STADT APOTHEKE")
    assert card("VISA PAYPAL *NEWS ONLINE") == ("NEWS ONLINE", "PAYPAL *NEWS ONLINE")
    assert card("VISA CREEM*MUSTERDIENST") == ("CREEM*MUSTERDIENST", "CREEM*MUSTERDIENST")


def test_an_iban_or_account_number_glued_to_the_name_is_cut():
    assert clean(raw("DE12500105170648489890Erika Mustermann", "Miete")) == Cleaned("Erika Mustermann", "Erika Mustermann", "Miete")
    assert clean(raw("5432109876Kleingeld Plus - Sparen    ", "Überweisung / Aus Kauf9,99. beiMUSTERLADEN SEQ123")).payee == "Kleingeld Plus - Sparen"


def test_a_company_name_is_kept_whole():
    debit = raw("PayPal Europe S.a.r.l. et Cie S.C.A", "1000000000001/PP.1444.PP/. Muster Cloud, Inc., Ihr Einkauf bei Muster Cloud,Inc.")
    assert clean(debit).description == "PayPal Europe S.a.r.l. et Cie S.C.A"
    assert clean(debit).notes == "1000000000001/PP.1444.PP/. Muster Cloud, Inc., Ihr Einkauf bei Muster Cloud,Inc."


def test_a_pending_card_payment_shows_merchant_and_town():
    padded = raw("Musikdienst              Musterstadt", "Musikdienst MusterstadtDatum 22.11. 2026 Zeit 19.50Kaufumsatz VISA CardEUR 17,99")
    full = raw("Baeckerei Mustermann OberMusterstadt  Nord", "Baeckerei Mustermann OberMusterstadt NordDatum 12.11. 2026 Zeit 08.15Kaufumsatz VISA Card")
    assert (clean(padded).payee, clean(padded).description) == ("Musikdienst", "Musikdienst · Musterstadt")
    assert (clean(full).payee, clean(full).description) == ("Baeckerei Mustermann Ober", "Baeckerei Mustermann Ober · Musterstadt Nord")


def test_an_entry_without_a_name_is_described_by_its_own_words():
    buy = raw("         ", "WP.ABRECHNUNG 1234567890123Kauf ISINIE00B4L5Y983ISHSIII-CORE MSCI WLD DLA", "Wertpapierkauf")
    payout = raw("   ", "Zins/DividendeISIN IE00B5BMR087 ISHSVII-CORE S+P500", "Zins / Dividende WP")
    closing = raw("", "", "Abschluss")
    assert (clean(buy).payee, clean(buy).description) == (None, "Kauf ISHSIII-CORE MSCI WLD DLA (IE00B4L5Y983)")
    assert clean(payout).description == "Ausschüttung ISHSVII-CORE S+P500 (IE00B5BMR087)"
    assert clean(closing) == Cleaned(None, "Abschluss", None)
    assert clean({"applicant_name": None, "purpose": None, "posting_text": None}) == Cleaned(None, "ING", None)


def test_whitespace_is_collapsed_and_lengths_fit_securo():
    assert clean(raw("  Erika   Mustermann ", "  Ausgleich  /  Urlaub ")) == Cleaned("Erika Mustermann", "Erika Mustermann", "Ausgleich / Urlaub")
    long = clean(raw("N" * 400, "P" * 1200))
    assert (len(long.payee), len(long.description), len(long.notes)) == (200, 400, 1000)
