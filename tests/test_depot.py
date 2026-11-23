"""MT535 depot statements. Every value is invented, in the shape ING sends."""

from decimal import Decimal

import pytest

from ing_fints.depot import Position, holding_rows, parse_mt535
from ing_fints.errors import BankSyncError
from ing_fints.mapping import digest

SALT = "11" * 32
DEPOT = "DE12500105170648489890"

HEADER = """
:16R:GENL
:28E:1/ONLY
:20C::SEME//NONREF
:23G:NEWM
:98C::STAT//20261123080000
:22F::STTY//CUST
:97A::SAFE//50010517/0648489890
:17B::ACTI//Y
:16S:GENL"""

POSITION = """
:16R:FIN
:35B:ISIN IE00B4L5Y983
/DE/A2PKXG
ISHSIII-CORE MSCI WLD DLA
:90B::MRKT//ACTU/EUR140,25
:94B::PRIC//LMAR/XGAT
:98C::PRIC//20261121173000
:93B::AGGR//UNIT/10,5
:16R:SUBBAL
:93C::TAVI//UNIT/AVAI/10,5
:16S:SUBBAL
:19A::HOLD//EUR1472,63
:70E::HOLD//1STK
120,123456+EUR
:16S:FIN"""

FOOTER = """
:16R:ADDINFO
:19A::HOLP//EUR1472,63
:16S:ADDINFO
-"""


def statement(*positions: str) -> str:
    return HEADER + "".join(positions) + FOOTER


def test_one_position_parsed():
    assert parse_mt535(statement(POSITION)) == [
        Position(
            isin="IE00B4L5Y983",
            name="ISHSIII-CORE MSCI WLD DLA",
            quantity=Decimal("10.5"),
            price=Decimal("140.25"),
            value=Decimal("1472.63"),
            currency="EUR",
            buy_in=Decimal("120.123456"),
        )
    ]


def test_empty_statement_is_an_empty_list():
    assert parse_mt535(statement()) == []


def test_empty_depot_keeps_the_other_depots_positions():
    full = holding_rows(parse_mt535(statement(POSITION)), DEPOT, "Direkt-Depot", SALT)
    empty = holding_rows(parse_mt535(statement()), "DE89500105170000000000", "Direkt-Depot", SALT)
    assert [h["isin"] for h in full + empty] == ["IE00B4L5Y983"]


def test_position_without_buy_in_has_no_purchase_price():
    position = POSITION.replace(":70E::HOLD//1STK\n120,123456+EUR\n", "")
    (row,) = holding_rows(parse_mt535(statement(position)), DEPOT, "Direkt-Depot", SALT)
    assert "purchase_price" not in row


@pytest.mark.parametrize("tag", [":93B::AGGR", ":19A::HOLD", ":35B:", ":90B::MRKT"])
def test_incomplete_position_is_refused(tag):
    broken = "\n".join(line for line in POSITION.splitlines() if not line.startswith(tag))
    with pytest.raises(BankSyncError) as error:
        parse_mt535(statement(broken))
    assert "IE00" not in str(error.value)


def test_negative_units_are_refused():
    with pytest.raises(BankSyncError):
        parse_mt535(statement(POSITION.replace("UNIT/10,5\n:16R", "UNIT/N10,5\n:16R")))


def test_unbalanced_sections_refused():
    with pytest.raises(BankSyncError):
        parse_mt535(HEADER + POSITION.replace(":16S:FIN", "") + FOOTER)


def test_holding_row():
    (row,) = holding_rows(parse_mt535(statement(POSITION)), DEPOT, "Direkt-Depot", SALT)
    assert row == {
        "external_id": digest(SALT, "hold-", DEPOT, "IE00B4L5Y983"),
        "name": "ISHSIII-CORE MSCI WLD DLA",
        "type": "investment",
        "currency": "EUR",
        "quantity": "10.5",
        "unit_price": "140.25",
        "current_value": "1472.63",
        "purchase_price": "1261.30",
        "isin": "IE00B4L5Y983",
        "account_external_id": digest(SALT, "ing-", DEPOT),
        "account_name": "Direkt-Depot …9890",
    }
