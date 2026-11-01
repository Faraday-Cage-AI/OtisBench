"""Seeded, disclosed customer qualification and emergency-carrier exceptions."""


def harden_long_tail(contents, rng):
    contract = contents["GRC"]["coupling"]
    customers = contract["customers"]
    # Emergency waivers are deliberately asymmetric: ordinary rules do not
    # automatically carry over into a compound disruption.
    affected = rng.sample(range(len(customers)), 2)
    customers[affected[0]]["scenario_overrides"] = {
        "compound_port_quality": {
            "paired_first_two": False,
            "prohibited_modes": ["standard"],
            "service_credit_cents": [0, 250000, 650000, 1500000],
        }
    }
    customers[affected[1]]["scenario_overrides"] = {
        "compound_carrier_quality": {
            "paired_first_two": False,
            "service_credit_cents": [0, 350000, 850000, 1800000],
        }
    }
    contract["dispatch_overrides"] = {
        "compound_port_quality": {
            "minimum_packs": {"express": rng.randint(4, 7)},
            "activation_fees_cents": {"express": rng.randrange(200000, 500001, 25000)},
        },
        "compound_carrier_quality": {
            "minimum_packs": {"express": rng.randint(4, 7)},
            "activation_fees_cents": {"express": rng.randrange(300000, 600001, 25000)},
        },
    }
    contract["rules"] += (
        " Long-tail addendum: scenario_overrides replace ONLY the named fields of a"
        " customer contract in the matching scenario; all other base terms remain."
        " prohibited_modes are customer-specific qualification exclusions, not global"
        " lane closures. Emergency kit-split waivers apply only where paired_first_two"
        " is explicitly false. Credit tables REPLACE, not add to, base credit tables."
        " dispatch_overrides apply by scenario: if a mode is used, its TOTAL shipped"
        " packs across ALL customers must meet minimum_packs; zero use is exempt."
        " Activation fee overrides REPLACE the base fee, charged once per used mode."
        " These are binding carrier minimum-load and emergency-charter terms."
    )
