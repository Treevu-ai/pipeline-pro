"""Tests para asignación de ángulos/gancho del piloto de outreach (sin LLM)."""
from __future__ import annotations

import outreach_pilot as op


def test_angle_for_slot_twelve():
    assert op.angle_for_slot(1, 12) == "A1"
    assert op.angle_for_slot(4, 12) == "A1"
    assert op.angle_for_slot(5, 12) == "A2"
    assert op.angle_for_slot(8, 12) == "A2"
    assert op.angle_for_slot(9, 12) == "A3"
    assert op.angle_for_slot(12, 12) == "A3"


def test_hook_variant_alternates():
    assert op.hook_variant_for_slot(1) == "A"
    assert op.hook_variant_for_slot(2) == "B"
    assert op.hook_variant_for_slot(3) == "A"


def test_planned_channel():
    row_wa = {"telefono": "987 654 321"}
    row_mail = {"telefono": ""}
    assert op.planned_channel(row_wa) == "whatsapp"
    assert op.planned_channel(row_mail) == "email"


def test_assignment_matches_components():
    a, h = op.assignment(7, 12)
    assert a == op.angle_for_slot(7, 12)
    assert h == op.hook_variant_for_slot(7)


def test_notes_suffix():
    s = op.notes_suffix("A2", "B", "whatsapp")
    assert "A2" in s and "B" in s and "whatsapp" in s
