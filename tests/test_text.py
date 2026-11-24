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
    assert clean(raw("Erika Mustermann", "", "Gutschrift aus Dauerauftrag")).description == "Gutschrift aus Dauerauftrag · Erika Mustermann"
    assert clean(raw("", "", "Abschluss")).description == "Abschluss"
    assert clean({"applicant_name": None, "purpose": None, "posting_text": None}) == Cleaned(None, "ING")


def test_lengths_fit_securo():
    cleaned = clean(raw("N" * 400, "P" * 900))
    assert len(cleaned.payee) == 200
    assert len(cleaned.description) == 500


def test_card_refund():
    row = raw("VISA BAUMARKT MUSTER AG F", "NR XXXX 1234 MUSTERSTADT DEGUTSCHRIFTSBELEG03.11 12.99123456ARN12345678901234567890123", "Gutschrift")
    assert clean(row) == Cleaned("BAUMARKT MUSTER AG F", "Erstattung: BAUMARKT MUSTER AG F · Musterstadt")


# Shapes found in a live sync on 2026-11-24 (values invented).


def test_visa_glued_to_the_merchant():
    row = raw("VISABAUMARKT MUSTER       ", "NR XXXX 1234 MUSTERSTADT DEKAUFUMSATZ01.11 9.99123456ARN12345678901234567890123", "Lastschrifteinzug")
    assert clean(row) == Cleaned("BAUMARKT MUSTER", "BAUMARKT MUSTER · Musterstadt")


def test_card_place_that_is_a_phone_number_or_code_is_left_out():
    paypal = raw("VISA PAYPAL *MUSTERDIENST", "NR XXXX 1234 0800123456 DEKAUFUMSATZ15.10 5.00123456ARN12345678901234567890123", "Lastschrifteinzug")
    abroad = raw("VISA PAYPAL *NEWS ONLINE", "NR XXXX 1234 0800123456 USKAUFUMSATZ15.10 8.00123456ARN22345678901234567890123", "Lastschrifteinzug")
    code = raw("VISA STADT MUSTERSTADT", "NR XXXX 1234 XY123456789 DEKAUFUMSATZ15.10 30.00123456ARN12345678901234567890123", "Lastschrifteinzug")
    assert clean(paypal) == Cleaned("MUSTERDIENST", "MUSTERDIENST · PayPal")
    assert clean(abroad) == Cleaned("NEWS ONLINE", "NEWS ONLINE · US · PayPal")
    assert clean(code) == Cleaned("STADT MUSTERSTADT", "STADT MUSTERSTADT")


def test_card_payment_in_a_foreign_currency():
    row = raw("VISA DESIGN TOOLS LTD", "NR XXXX 1234 SPRINGFIELD AUKURS 1.2345000KAUFUMSATZ01.09 20.00123456ARN12345678901234567890123", "Lastschrifteinzug")
    assert clean(row) == Cleaned("DESIGN TOOLS LTD", "DESIGN TOOLS LTD · Springfield, AU")


def test_cash_withdrawal():
    purpose = "NR XXXX 1234 MUSTERSTADT DEBARGELDAUSZAHLUNG01.10 50.00123456ARN12345678901234567890123"
    row = raw("Bargeldauszahlung VISA Card MUSTERBANK", purpose, "Lastschrifteinzug")
    assert clean(row) == Cleaned("MUSTERBANK", "Bargeldauszahlung · Musterstadt")


def test_pending_card_payment_with_the_merchant_padded_by_spaces():
    row = raw("Musikdienst              Musterstadt", "Musikdienst MusterstadtDatum 22.11. 2026 Zeit 19.50Kaufumsatz VISA CardEUR 17,99", "Lastschrifteinzug")
    assert clean(row) == Cleaned("Musikdienst", "Musikdienst · Musterstadt")


def test_paypal_names_the_merchant():
    plain = raw("PayPal Europe S.a.r.l. et Cie S.C.A", "1000000000001/PP.1444.PP/. Muster Cloud, Inc., Ihr Einkauf bei Muster Cloud,Inc.", "Lastschrifteinzug")
    glued = raw("PayPal Europe S.a.r.l. et Cie S.C.A", "1000000000002/. Muster Cloud Inc, IhrEinkauf bei Muster Cloud Inc", "Lastschrifteinzug")
    unnamed = raw("PayPal Europe S.a.r.l. etCie S.C.A", "1000000000003/PP.1444.PP/. , Ihr Einkauf bei", "Lastschrifteinzug")
    refund = raw("PayPal Europe S.a.r.l. et Cie S.C.A", "PP.9491.PP/YYR1000000000004", "Gutschrift")
    assert clean(plain) == Cleaned("Muster Cloud, Inc.", "Muster Cloud, Inc. · PayPal")
    assert clean(glued) == Cleaned("Muster Cloud Inc", "Muster Cloud Inc · PayPal")
    assert clean(unnamed) == Cleaned("PayPal", "PayPal")
    assert clean(refund) == Cleaned("PayPal", "PayPal")


def test_amazon_shows_the_order_number():
    market = raw("AMAZON PAYMENTS EUROPE S.C.A.", "111.2223333.4445555 AMZN Mktp DE ABCDEF1234567890", "Lastschrifteinzug")
    shop = raw("AMAZON EU S.A R.L., NIEDERLASSUNG DEUTSCHLAND", "999.8887777.6665555 Amazon.de ZYXWVU0987654321", "Lastschrifteinzug")
    assert clean(market) == Cleaned("Amazon", "Amazon Marketplace · Bestellung 111-2223333-4445555")
    assert clean(shop) == Cleaned("Amazon", "Amazon.de · Bestellung 999-8887777-6665555")


def test_girocard_direct_debit():
    row = raw("MUSTERMARKT MUSTERSTADT 0001", "ELV1234567890.10 17.40 ME0", "Lastschrifteinzug")
    assert clean(row) == Cleaned("MUSTERMARKT MUSTERSTADT 0001", "MUSTERMARKT MUSTERSTADT 0001 · girocard")


def test_transfer_without_purpose_names_the_counterparty():
    out = raw("DE12500105170648489890Erika Mustermann", "", "Überweisung")
    back = raw("Erika Mustermann", "", "Gutschrift")
    assert clean(out) == Cleaned("Erika Mustermann", "Überweisung · Erika Mustermann")
    assert clean(back) == Cleaned("Erika Mustermann", "Gutschrift · Erika Mustermann")


def test_merchant_references_and_prefixes_are_cut():
    def card(name, place="MUSTERSTADT DE"):
        return clean(raw(name, f"NR XXXX 1234 {place}KAUFUMSATZ19.11 4.01123456ARN12345678901234567890123", "Lastschrifteinzug"))

    assert card("VISA AMZN MKTP DE*AB12CD34E", "Shop.Com/Ex LU") == Cleaned("Amazon Marketplace", "Amazon Marketplace · LU")
    assert card("VISA AMAZON* X12Y34Z56", "Luxembourg LU") == Cleaned("Amazon", "Amazon · Luxembourg, LU")
    assert card("VISAXYZ*STADT APOTHEKE     ") == Cleaned("STADT APOTHEKE", "STADT APOTHEKE · Musterstadt")
    assert card("VISA PAYPAL *NEWSLETTER DIENST", "0800123456 DE") == Cleaned("NEWSLETTER DIENST", "NEWSLETTER DIENST · PayPal")
    round_up = raw("5432109876Kleingeld Plus - Sparen", "Überweisung / Aus Kauf4,01. beiAMZN MKTP DE*AB12CD34ESEQ123456789012345", "Überweisung")
    assert clean(round_up).description == "Aufrundung: Amazon Marketplace"


def test_amazon_return_and_paypal_glued_words():
    returned_text = "123.4567890.1234567 AMZN Mktp DE XXVorgelegt am 05.10.2026Nicht bezahlt 9,99.Fehlende Deckung"
    returned = raw("AMAZON PAYMENTS EUROPE S.C.A.", returned_text, "Retouren")
    glued_text = "1000000000005/PP.1444.PP/. Muster Payments Ltd., Ihr Einkaufbei Muster Payments Ltd."
    glued = raw("PayPal Europe S.a.r.l. et Cie S.C.A", glued_text, "Lastschrifteinzug")
    assert clean(returned) == Cleaned(
        "Amazon", "Amazon Marketplace · Bestellung 123-4567890-1234567, vorgelegt am 05.10.2026, nicht bezahlt 9,99, fehlende Deckung"
    )
    assert clean(glued) == Cleaned("Muster Payments Ltd.", "Muster Payments Ltd. · PayPal")
