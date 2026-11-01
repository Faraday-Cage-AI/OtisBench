"""Source-inspired synthetic receipt revaluation; not a vendor emulator."""


def reconcile_costs(contract):
    rows = []

    def visit(node, delta, inherited=True):
        if node["quantity"] != node["on_hand"] + node["consumed"] + sum(
            c["quantity"] for c in node["children"]
        ):
            raise ValueError("quantity conservation failed")
        enabled = inherited and (
            node["logical"] or (node["method"] == "actual" and node["propagate"])
        )
        inventory = node["on_hand"] * delta if enabled else 0
        expense = node["consumed"] * delta if enabled else node["quantity"] * delta
        rows.append(
            {
                "node_id": node["id"],
                "propagated": enabled,
                "inventory_adjustment_cents": inventory,
                "expense_adjustment_cents": expense,
                "available_quantity": node["on_hand"]
                if node["quarantine"] in ("none", "ended")
                else 0,
            }
        )
        if enabled:
            for child in node["children"]:
                visit(child, delta, enabled)

    exclusions = []
    liability = 0
    for receipt in contract["receipts"]:
        if receipt["owner"] != "buyer":
            exclusions.append({"receipt_id": receipt["id"], "reason": "supplier_owned"})
            continue
        if receipt["status"] != "approved":
            exclusions.append({"receipt_id": receipt["id"], "reason": "unapproved_adjustment"})
            continue
        delta = receipt["new_unit_cents"] - receipt["old_unit_cents"]
        liability += receipt["root"]["quantity"] * delta
        visit(receipt["root"], delta)
    inventory = sum(r["inventory_adjustment_cents"] for r in rows)
    expense = sum(r["expense_adjustment_cents"] for r in rows)
    if inventory + expense != liability:
        raise ValueError("journal conservation failed")
    return {
        "nodes": sorted(rows, key=lambda r: r["node_id"]),
        "exclusions": exclusions,
        "inventory_adjustment_cents": inventory,
        "expense_adjustment_cents": expense,
        "liability_adjustment_cents": liability,
    }


def generate_costs(rng):
    def node(name, on_hand, consumed, children=(), **overrides):
        return {
            "id": name,
            "quantity": on_hand + consumed + sum(c["quantity"] for c in children),
            "on_hand": on_hand,
            "consumed": consumed,
            "children": list(children),
            "logical": False,
            "method": "actual",
            "propagate": True,
            "quarantine": "none",
            **overrides,
        }

    leaf = node(
        "DC-OUTLET",
        rng.randint(3, 7),
        rng.randint(3, 8),
        method=rng.choice(["actual", "standard"]),
        quarantine="ended",
    )
    transit = node("LOGICAL-TRANSIT", 0, 0, [leaf], logical=True, propagate=False)
    warehouse = node(
        "DC-QUALITY", rng.randint(5, 12), rng.randint(1, 5), quarantine="reported_finished"
    )
    root = node("PLANT-RECEIPT", rng.randint(5, 12), rng.randint(4, 9), [transit, warehouse])
    old = rng.randint(2000, 6000)
    receipts = [
        {
            "id": "RECEIPT-OWNED",
            "owner": "buyer",
            "status": "approved",
            "old_unit_cents": old,
            "new_unit_cents": old + rng.choice([-175, 225, 375]),
            "root": root,
        },
        {
            "id": "RECEIPT-CONSIGNED",
            "owner": "supplier",
            "status": "approved",
            "old_unit_cents": 1000,
            "new_unit_cents": 5000,
            "root": node("VENDOR-STOCK", 40, 0),
        },
        {
            "id": "RECEIPT-DRAFT",
            "owner": "buyer",
            "status": "draft",
            "old_unit_cents": 1000,
            "new_unit_cents": 9000,
            "root": node("DRAFT", 30, 0),
        },
    ]
    return {
        "receipts": receipts,
        "rules": "This separate incident-cost subledger is not included in AP documents or recovery costs. Exclude supplier-owned receipts first (supplier_owned), then non-approved adjustments (unapproved_adjustment). For each other receipt use signed new minus old unit cents. Each tree node conserves quantity = on_hand + consumed + child quantities. Starting at root, propagate when logical=true OR (method=actual AND propagate=true). At an enabled node, allocate delta*on_hand to inventory and delta*consumed to expense, then visit children. At a disabled node, allocate delta*quantity to expense and STOP: omit all its descendants. Logical nodes pass through even with propagate=false. For each visited node available_quantity=on_hand only if quarantine=none or ended; reported_finished is NOT back at the regular warehouse. Quarantine does not eliminate owned inventory value. Emit cost_bridge {nodes sorted by node_id [{node_id,propagated,inventory_adjustment_cents,expense_adjustment_cents,available_quantity}], exclusions in receipt order [{receipt_id,reason}], inventory_adjustment_cents, expense_adjustment_cents, liability_adjustment_cents}. Total inventory+expense must equal quantity*delta for eligible roots. Add ONLY cost_bridge.expense_adjustment_cents/100 to incident reserve, not inventory or liability. This bridge remains separate from AP payable and settled cash.",
    }
