"""Clean-up of ING's MT940 text. Every value here is invented, in the shape ING sends."""

from ing_fints.text import Cleaned, clean


def raw(name="", purpose="", posting_text="Gutschrift"):
    return {"applicant_name": name, "purpose": purpose, "posting_text": posting_text}


def test_iban_glued_to_the_name_is_cut():
    assert clean(raw("DE12500105170648489890Erika Mustermann", "Miete")) == Cleaned("Erika Mustermann", "Miete")


def test_ing_account_number_glued_to_the_name_is_cut():
    assert clean(raw("5432109876Kleingeld Plus - Sparen    ", "Sparen")).payee == "Kleingeld Plus - Sparen"


def test_booked_card_payment():
    row = raw(
        "VISA BAECKEREI MUSTERMANN ",
        "NR XXXX 1234 MUSTERSTADT DEKAUFUMSATZ12.11 4.80123456ARN12345678901234567890123Apple Pay",
        "Lastschrifteinzug",
    )
    assert clean(row) == Cleaned("BAECKEREI MUSTERMANN", "BAECKEREI MUSTERMANN · Musterstadt")


def test_booked_card_payment_abroad_names_the_country():
    row = raw("VISA CAFE CENTRAL", "NR XXXX 1234 WIEN ATKAUFUMSATZ02.11 3.50123456ARN12345678901234567890123", "Lastschrifteinzug")
    assert clean(row) == Cleaned("CAFE CENTRAL", "CAFE CENTRAL · Wien, AT")


def test_pending_card_payment_splits_merchant_and_town_columns():
    name = "Baeckerei Mustermann Ober" + "Musterstadt  " + "Nord"
    purpose = "Baeckerei Mustermann OberMusterstadt NordDatum 12.11. 2026 Zeit 08.15Kaufumsatz VISA CardEUR 4,80"
    assert clean(raw(name, purpose, "Lastschrifteinzug")) == Cleaned("Baeckerei Mustermann Ober", "Baeckerei Mustermann Ober · Musterstadt Nord")


def test_girocard_payment_keeps_merchant_and_town():
    purpose = "MUSTERMARKT SAGT DANKE./Kasse 3/Musterstadt /DE 2026.11.01T12.00.00 Folgenr.003 Verfalld.2028.12"
    assert clean(raw("Mustermarkt GmbH", purpose, "Lastschrifteinzug")) == Cleaned("Mustermarkt GmbH", "Mustermarkt GmbH · Musterstadt")


def test_round_up_saving():
    row = raw("5432109876Kleingeld Plus - Sparen", "Überweisung / Aus Kauf4,80. beiBAECKEREI MUSTERMANN SEQ123456789012345", "Überweisung")
    assert clean(row) == Cleaned("Kleingeld Plus - Sparen", "Aufrundung: BAECKEREI MUSTERMANN")


def test_card_fees():
    girocard = raw("ING", "GIROCARD 123456789012MONATLICHES ENTGELTGIROCARD (DEBITKARTE)", "Entgelt")
    visa = raw("VISA SOME SHOP", "VISA 1234 XXXX XXXX 5678AUSLANDSEINSATZENTGELTVISA CARD (DEBITKARTE)ARN12345678901234567890123", "Entgelt")
    assert clean(girocard) == Cleaned("ING", "Monatliches Entgelt Girocard")
    assert clean(visa) == Cleaned("SOME SHOP", "Auslandseinsatzentgelt Visa")


def test_returned_debit_reads_as_a_sentence():
    row = raw("Muster Versand GmbH", "Abo 123456789zum 01.11.2026Vorgelegt am 02.11.2026Nicht bezahlt 9,99.Fehlende Deckung", "Retouren")
    assert clean(row).description == "Abo 123456789zum 01.11.2026, vorgelegt am 02.11.2026, nicht bezahlt 9,99, fehlende Deckung"


def test_securities():
    buy = raw("         ", "WP.ABRECHNUNG 1234567890123Kauf ISINIE00B5BMR087ISHSIII-CORE MSCI WLD DLA", "Wertpapierkauf")
    sell = raw("", "WP.ABRECHNUNG 1234567890123Verkauf ISINIE00B5BMR087ISHSIII-CORE MSCI WLD DLA", "Wertpapiergutschrift")
    payout = raw("   ", "Zins/DividendeISIN IE00B5BMR087 ISHSVII-CORE S+P500", "Zins / Dividende WP")
    assert clean(buy) == Cleaned(None, "Kauf ISHSIII-CORE MSCI WLD DLA (IE00B5BMR087)")
    assert clean(sell) == Cleaned(None, "Verkauf ISHSIII-CORE MSCI WLD DLA (IE00B5BMR087)")
    assert clean(payout) == Cleaned(None, "Ausschüttung ISHSVII-CORE S+P500 (IE00B5BMR087)")


def test_whitespace_collapsed_and_plain_text_kept():
    assert clean(raw("  Erika   Mustermann ", "  Ausgleich  /  Urlaub ")) == Cleaned("Erika Mustermann", "Ausgleich / Urlaub")


def test_empty_purpose_falls_back_to_posting_text_then_a_default():
    assert clean(raw("Erika Mustermann", "", "Gutschrift aus Dauerauftrag")).description == "Gutschrift aus Dauerauftrag"
    assert clean({"applicant_name": None, "purpose": None, "posting_text": None}) == Cleaned(None, "ING")


def test_lengths_fit_securo():
    cleaned = clean(raw("N" * 400, "P" * 900))
    assert len(cleaned.payee) == 200
    assert len(cleaned.description) == 500


def test_card_refund():
    row = raw("VISA BAUMARKT MUSTER AG F", "NR XXXX 1234 MUSTERSTADT DEGUTSCHRIFTSBELEG03.11 12.99123456ARN12345678901234567890123", "Gutschrift")
    assert clean(row) == Cleaned("BAUMARKT MUSTER AG F", "Erstattung: BAUMARKT MUSTER AG F · Musterstadt")
