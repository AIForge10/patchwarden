from demo_app.seed_variants.control.payments import charge, get_charge_count, reset_charges


def test_control_does_not_duplicate_charges() -> None:
    reset_charges()
    charge(50, "same-key")
    charge(50, "same-key")
    assert get_charge_count("same-key") == 1
