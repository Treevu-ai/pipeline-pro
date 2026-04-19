"""Normalización de teléfonos peruanos para WhatsApp."""
from __future__ import annotations

import utils


def test_mobile_nine_digits():
    assert utils.whatsapp_digits_pe("987 654 321") == "51987654321"
    assert utils.whatsapp_digits_pe("951 485 890") == "51951485890"


def test_already_international():
    assert utils.whatsapp_digits_pe("+51 987 654 321") == "51987654321"
    assert utils.whatsapp_digits_pe("51987654321") == "51987654321"


def test_lima_landline():
    assert utils.whatsapp_digits_pe("(01) 2203288") == "5112203288"
    assert utils.whatsapp_digits_pe("(01) 4851157") == "5114851157"
