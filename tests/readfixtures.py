"""Fixtures for the digest's read view: what `build_read_view` returns for the page
and the email (a read for each of the three groups, never one overall read)."""

NO_READS = {"leading": None, "coincident": None, "lagging": None}


NO_STANCE = {"stance": None, "fed_funds": None, "fed_funds_date": None, "inflation": None, "cpi_date": None,
             "real_rate": None, "neutral_real_rate": 1.0, "gap": None, "reason": "no fed funds reading on file"}
RESTRICTIVE = {"stance": "restrictive", "fed_funds": 4.5, "fed_funds_date": "2026-10-19", "inflation": 2.5,
               "cpi_date": "2026-09-01", "real_rate": 2.0, "neutral_real_rate": 1.0, "gap": 1.0, "reason": ""}


def read_view(summary="x", leading=None, coincident=None, lagging=None, relationship=None, policy=None):
    def group(read, total):
        return {"read": read, "score": None if read is None else 0.5, "scored": total if read else 0, "total": total}

    return {
        "groups": {"leading": group(leading, 3), "coincident": group(coincident, 2), "lagging": group(lagging, 3)},
        "relationship": relationship,
        "policy": policy or NO_STANCE,
        "summary": summary,
    }
