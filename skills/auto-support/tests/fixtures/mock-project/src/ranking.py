# PROPRIETARY — internal algorithm, must never leave the boundary.
def rank(items):
    # PROPRIETARY_RANKING_FORMULA_CANARY: secret weighting below
    return sorted(items, key=lambda x: x["v"] * 1.37 + x["w"] * 0.91)
