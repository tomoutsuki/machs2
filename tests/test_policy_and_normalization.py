from services.machs_main_api.app.services.normalization import normalize_birthdate, normalize_cpf, normalize_name
from services.machs_main_api.app.services.policy import evaluate_policy, normalize_policy_expression


def test_normalization_rules():
    assert normalize_name("  Ana   BEATRIZ ") == "ana beatriz"
    assert normalize_cpf("345.678.901-23") == "34567890123"
    assert normalize_birthdate(" 2018-09-25 ") == "2018-09-25"


def test_policy_validation_and_eval():
    p = normalize_policy_expression("(role.doctor OR role.nurse) AND clearance.clinical_notes")
    assert "role.doctor" in p
    assert evaluate_policy(p, ["role.nurse", "clearance.clinical_notes", "epoch.2026"])
    assert not evaluate_policy(p, ["role.receptionist", "clearance.demographics"])
