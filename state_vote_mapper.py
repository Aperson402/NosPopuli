import math
from documentor_agent import log_action

# Seat counts per state chamber (lower = House equivalent, upper = Senate equivalent)
STATE_CHAMBERS = {
    "VA": {"lower": 100, "upper": 40},
    "TX": {"lower": 150, "upper": 31},
    "CA": {"lower":  80, "upper": 40},
    "NY": {"lower": 150, "upper": 63},
    "FL": {"lower": 120, "upper": 40},
    "PA": {"lower": 203, "upper": 50},
    "IL": {"lower": 118, "upper": 59},
    "OH": {"lower":  99, "upper": 33},
    "GA": {"lower": 180, "upper": 56},
    "NC": {"lower": 120, "upper": 50},
    "MI": {"lower": 110, "upper": 38},
    "NJ": {"lower":  80, "upper": 40},
    "WA": {"lower":  98, "upper": 49},
    "AZ": {"lower":  60, "upper": 30},
    "TN": {"lower":  99, "upper": 33},
    "MA": {"lower": 160, "upper": 40},
    "IN": {"lower": 100, "upper": 50},
}

STATE_VOTE_COLORS = {
    "yes":        "#2a6e2a",
    "no":         "#8b1a1a",
    "abstain":    "#8b7a1a",
    "absent":     "#c8bfaa",
    "excused":    "#c8bfaa",
    "not voting": "#c8bfaa",
    "other":      "#c8bfaa",
}

# Sort order: yes far-left, no far-right, abstentions in between
_VOTE_SORT = {"yes": 0, "abstain": 1, "other": 2, "not voting": 2,
              "excused": 3, "absent": 3, "no": 4}


def _compute_row_distribution(n_seats, n_rows):
    """Inner rows shorter, outer rows longer (mirrors a real chamber's arc geometry)."""
    weights = [1.0 + i / max(n_rows - 1, 1) for i in range(n_rows)]
    total_w = sum(weights)
    rows = []
    remaining = n_seats
    for w in weights[:-1]:
        count = max(1, round(n_seats * w / total_w))
        rows.append(count)
        remaining -= count
    rows.append(max(1, remaining))
    return rows


def _get_layout(n_seats):
    """Return (n_rows, svgW, svgH, r_start, r_step, cx, cy, dot_r) for given seat count."""
    if n_seats < 35:
        n_rows, r_start, r_step, dot_r = 3, 40, 24, 7.0
    elif n_seats < 70:
        n_rows, r_start, r_step, dot_r = 4, 42, 22, 6.0
    elif n_seats < 130:
        n_rows, r_start, r_step, dot_r = 5, 44, 20, 5.0
    elif n_seats < 200:
        n_rows, r_start, r_step, dot_r = 6, 50, 20, 4.5
    else:
        n_rows, r_start, r_step, dot_r = 8, 55, 20, 4.0

    max_r = r_start + (n_rows - 1) * r_step
    svgW = 2 * max_r + 40
    svgH = max_r + r_step + 15
    cx = svgW // 2
    cy = svgH - 5
    return n_rows, svgW, svgH, r_start, r_step, cx, cy, dot_r


def _semicircle_positions(row_counts, cx, cy, r_start, r_step, angle_padding=0.08):
    positions = []
    for row_idx, count in enumerate(row_counts):
        r = r_start + row_idx * r_step
        for i in range(count):
            t = 0.5 if count == 1 else i / (count - 1)
            angle = math.pi * (1 - angle_padding) - t * math.pi * (1 - 2 * angle_padding)
            x = cx + r * math.cos(angle)
            y = cy - r * math.sin(angle)
            positions.append((round(x, 2), round(y, 2)))
    return positions


def map_state_votes(bill_votes, state_code, chamber_class):
    """
    Map OpenStates vote events to semicircle seat format.

    bill_votes: list of vote event objects from bill_data["votes"]
    chamber_class: "lower" or "upper"

    Returns {seats, summary, svgW, svgH, dot_r, motion, result} or None.
    """
    if not bill_votes:
        return None

    # Pick the right vote for this chamber.
    #
    # OpenStates tags both committee and floor votes with the same chamber
    # classification ("lower"/"upper") and often leaves motion_classification
    # empty. So we can't trust those alone — committee tallies (e.g. 22-0) get
    # mistaken for chamber passage (e.g. 98-0). We rank candidates by:
    #
    #   1. motion_classification of "passage" or "reading-3" (when present)
    #   2. motion_text matching floor-vote markers ("VOTE:", "Passage",
    #      "Third Reading", "Final Passage")
    #   3. Total participants — chamber-wide floor votes are near full chamber
    #      seat count; committee tallies are far smaller
    #
    # Anything with explicit committee-vote text ("Reported from",
    # "Subcommittee", "Substitute agreed") is explicitly excluded.
    state_data = STATE_CHAMBERS.get(state_code.upper(), {})
    chamber_seats = state_data.get(chamber_class, 0)

    def _is_committee_vote(motion_text: str) -> bool:
        mt = (motion_text or "").lower()
        direct_markers = (
            "reported from", "subcommittee", "substitute agreed",
            "amendment agreed", "committee recommend",
            "from committee", "placed on suspense",
        )
        if any(m in mt for m in direct_markers):
            return True
        # "Do pass" by itself is sometimes a floor motion in plain language, but
        # in committee contexts it always co-occurs with re-referral, committee
        # naming, or amendment language. Catch all three.
        if "do pass" in mt and any(
            kw in mt for kw in ("re-refer", "re-referred", "committee", "com.", "amend")
        ):
            return True
        return False

    def _floor_vote_score(v: dict) -> tuple:
        org_class = (v.get("organization") or {}).get("classification", "")
        if org_class != chamber_class:
            return (-1,)
        motion_text = v.get("motion_text") or ""
        if _is_committee_vote(motion_text):
            return (-1,)
        classifications = v.get("motion_classification") or []
        mc_score = 2 if any(c in classifications for c in ("passage", "reading-3")) else 0
        mt = motion_text.lower()
        mt_score = 2 if any(p in mt for p in ("vote:", "passage", "third reading", "final passage")) else 0
        total = sum(c.get("value", 0) for c in v.get("counts", []))
        # Normalise total against chamber seat count when known: votes close
        # to full chamber size score highest; tiny committee tallies score low.
        if chamber_seats and total > 0:
            participation_score = min(total / chamber_seats, 1.0)
        else:
            participation_score = min(total / 40.0, 1.0)
        date = v.get("start_date") or v.get("date") or ""
        return (mc_score + mt_score, participation_score, date)

    candidates = [v for v in bill_votes if _floor_vote_score(v)[0] != -1]
    if candidates:
        target = max(candidates, key=_floor_vote_score)
    else:
        # No clean floor vote. Only fall back when there's a non-committee
        # vote with substantial participation (>= 50% of the chamber, if known).
        # Otherwise return None — better to show "no recorded vote" than to
        # mislabel a committee tally as the chamber's verdict.
        non_committee = [
            v for v in bill_votes
            if (v.get("organization") or {}).get("classification", "") == chamber_class
            and not _is_committee_vote(v.get("motion_text") or "")
        ]
        if not non_committee:
            return None
        target = max(non_committee, key=lambda v: sum(c.get("value", 0) for c in v.get("counts", [])))
        total = sum(c.get("value", 0) for c in target.get("counts", []))
        if chamber_seats and total < chamber_seats * 0.5:
            return None

    # Vote counts
    counts = {c["option"]: c["value"] for c in target.get("counts", [])}
    yea    = counts.get("yes", 0)
    nay    = counts.get("no", 0)
    pres   = counts.get("abstain", 0)
    absent = sum(counts.get(k, 0) for k in ("absent", "excused", "not voting", "other"))
    summary = {"yea": yea, "nay": nay, "present": pres, "not_voting": absent}

    # Seat count — use state lookup, fall back to total voters from this vote
    state_data = STATE_CHAMBERS.get(state_code.upper(), {})
    n_seats = state_data.get(chamber_class, 0)
    if not n_seats:
        n_seats = yea + nay + pres + absent or 40

    n_rows, svgW, svgH, r_start, r_step, cx, cy, dot_r = _get_layout(n_seats)
    row_counts = _compute_row_distribution(n_seats, n_rows)
    positions = _semicircle_positions(row_counts, cx, cy, r_start, r_step)

    individual = target.get("votes", [])

    if individual:
        sorted_votes = sorted(individual, key=lambda v: _VOTE_SORT.get(v.get("option", ""), 2))
        seats = []
        for i, (x, y) in enumerate(positions):
            if i < len(sorted_votes):
                v = sorted_votes[i]
                option = v.get("option", "")
                name = v.get("voter_name", "") or (v.get("voter") or {}).get("name", "")
                color = STATE_VOTE_COLORS.get(option, "#c8bfaa")
            else:
                option, name, color = "absent", "", "#c8bfaa"
            seats.append({
                "x": x, "y": y,
                "name": name,
                "party": "",
                "state": state_code,
                "vote": option,
                "color": color,
                "source": "state",
            })
    else:
        # No individual voter data — fill proportionally from counts
        buckets = (
            [("yes",     STATE_VOTE_COLORS["yes"])]     * yea    +
            [("abstain", STATE_VOTE_COLORS["abstain"])] * pres   +
            [("absent",  STATE_VOTE_COLORS["absent"])]  * absent +
            [("no",      STATE_VOTE_COLORS["no"])]      * nay
        )
        seats = []
        for i, (x, y) in enumerate(positions):
            if i < len(buckets):
                option, color = buckets[i]
            else:
                option, color = "absent", "#c8bfaa"
            seats.append({
                "x": x, "y": y,
                "name": "", "party": "", "state": state_code,
                "vote": option, "color": color, "source": "state",
            })

    log_action(
        agent_name="state_vote_mapper",
        action="map_state_votes",
        input_data={"state": state_code, "chamber": chamber_class, "n_seats": n_seats},
        output_data=summary,
    )

    return {
        "seats":   seats,
        "summary": summary,
        "svgW":    svgW,
        "svgH":    svgH,
        "dot_r":   dot_r,
        "motion":  target.get("motion_text", ""),
        "result":  target.get("result", ""),
    }
