"""
State vote mapper tests — committee vs floor vote disambiguation.

OpenStates tags committee votes and floor votes with the SAME chamber
classification ("lower"/"upper") and often leaves motion_classification empty.
We disambiguate by motion_text patterns plus a participation-count sanity
check against the chamber seat map.

These tests guard the rules added when we caught the bugs where:
- VA HB 191 was showing 22-0 committee tally as the House floor vote (real: 98-0-2)
- CA SB 1407 was showing 8-0 Assembly committee tally when no floor vote exists yet
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from state_vote_mapper import map_state_votes


def _vote(*, chamber, motion, counts, date="2026-01-01"):
    """Build a synthetic OpenStates vote record."""
    return {
        "organization": {"classification": chamber},
        "motion_text": motion,
        "motion_classification": [],
        "counts": [{"option": k, "value": v} for k, v in counts.items()],
        "start_date": date,
        "votes": [],  # No individual voter records — uses bucket fill
    }


def _summary(result):
    return result["summary"] if result else None


class FloorVsCommitteeVA(unittest.TestCase):
    """Virginia HB 191 — real-world bugs we already fixed."""

    def setUp(self):
        # Simulated VA HB 191 votes — committee report + floor passage
        self.votes = [
            _vote(  # Committee report — should NOT be picked as the floor vote
                chamber="lower",
                motion="Reported from Courts of Justice with substitute",
                counts={"yes": 22, "no": 0},
                date="2026-02-04",
            ),
            _vote(  # Floor passage — this IS the chamber vote
                chamber="lower",
                motion="H VOTE:",
                counts={"yes": 98, "no": 0, "not voting": 2},
                date="2026-02-10",
            ),
            _vote(  # Subcommittee — must not leak through
                chamber="lower",
                motion="Subcommittee recommends reporting with substitute",
                counts={"yes": 10, "no": 0},
                date="2026-01-30",
            ),
        ]

    def test_picks_floor_vote_not_committee(self):
        result = map_state_votes(self.votes, "VA", "lower")
        self.assertEqual(_summary(result),
            {"yea": 98, "nay": 0, "present": 0, "not_voting": 2})

    def test_motion_text_carries_floor_marker(self):
        result = map_state_votes(self.votes, "VA", "lower")
        self.assertIn("VOTE", result["motion"].upper())


class NoFloorVoteCA(unittest.TestCase):
    """California SB 1407 — Assembly hasn't voted on the floor yet.

    Only committee votes exist for the Assembly. Mapper must return None so
    the frontend hides the chamber tile rather than mislabeling a committee
    tally as a floor vote.
    """

    def setUp(self):
        self.votes = [
            _vote(  # Assembly committee — only Assembly vote in the set
                chamber="lower",
                motion="Do pass and be re-referred to the Committee on Revenue and Taxation",
                counts={"yes": 8, "no": 0},
                date="2026-06-17",
            ),
            _vote(  # Senate floor passage (Special Consent calendar)
                chamber="upper",
                motion="Special Consent SB1407",
                counts={"yes": 39, "no": 0, "not voting": 1},
                date="2026-05-28",
            ),
        ]

    def test_assembly_returns_none_when_no_floor_vote(self):
        self.assertIsNone(map_state_votes(self.votes, "CA", "lower"))

    def test_senate_picks_floor_vote(self):
        result = map_state_votes(self.votes, "CA", "upper")
        self.assertEqual(_summary(result),
            {"yea": 39, "nay": 0, "present": 0, "not_voting": 1})


class CommitteeMotionTextDetection(unittest.TestCase):
    """The _is_committee_vote() rules — encoded as scenarios so future
    refactors can't silently relax detection."""

    CHAMBER_SEATS = 100  # arbitrary; just need a baseline for participation threshold

    def _has_only(self, motion, counts):
        """Helper: a single vote with the given motion_text + counts. Expects
        the mapper to either return None or to not pick this vote as the floor
        result (i.e. its motion shouldn't show up)."""
        return [_vote(chamber="lower", motion=motion, counts=counts)]

    def test_reported_from_committee_excluded(self):
        votes = self._has_only("Reported from Judiciary Committee with amendment", {"yes": 12, "no": 0})
        self.assertIsNone(map_state_votes(votes, "VA", "lower"))

    def test_subcommittee_excluded(self):
        votes = self._has_only("Subcommittee recommends do pass", {"yes": 5, "no": 0})
        self.assertIsNone(map_state_votes(votes, "VA", "lower"))

    def test_do_pass_and_re_refer_excluded(self):
        votes = self._has_only("Do pass and re-refer to Com. on Appropriations", {"yes": 7, "no": 0})
        self.assertIsNone(map_state_votes(votes, "CA", "lower"))

    def test_do_pass_be_re_referred_excluded(self):
        votes = self._has_only("Do pass and be re-referred to the Committee on Health", {"yes": 8, "no": 0})
        self.assertIsNone(map_state_votes(votes, "CA", "lower"))

    def test_placed_on_suspense_excluded(self):
        votes = self._has_only("Placed on suspense file", {"yes": 7, "no": 0})
        self.assertIsNone(map_state_votes(votes, "CA", "lower"))

    def test_from_committee_excluded(self):
        votes = self._has_only("From committee: Do pass", {"yes": 6, "no": 0})
        self.assertIsNone(map_state_votes(votes, "CA", "lower"))


class ParticipationThreshold(unittest.TestCase):
    """When no clean floor-vote motion exists, fall back only if a
    non-committee vote has >= 50% of the chamber participating. Below that
    we return None so committee-sized tallies can't get fallback-promoted."""

    def test_below_50_pct_returns_none(self):
        # VA House = 100 seats. 30 participants is well below 50%.
        votes = [_vote(
            chamber="lower",
            motion="Motion to recommit",  # Not a committee marker, not a clear floor marker
            counts={"yes": 30, "no": 0},
        )]
        self.assertIsNone(map_state_votes(votes, "VA", "lower"))

    def test_above_50_pct_with_clear_floor_marker_passes(self):
        # VA House = 100. 80 participants on a clear floor marker — should pass.
        votes = [_vote(
            chamber="lower",
            motion="H VOTE: Third reading",
            counts={"yes": 70, "no": 10},
        )]
        result = map_state_votes(votes, "VA", "lower")
        self.assertEqual(_summary(result),
            {"yea": 70, "nay": 10, "present": 0, "not_voting": 0})


class WrongChamber(unittest.TestCase):
    """Votes from the other chamber must not bleed into the result."""

    def test_only_upper_votes_returns_none_for_lower(self):
        votes = [_vote(
            chamber="upper",
            motion="H VOTE: Passage",
            counts={"yes": 30, "no": 0},
        )]
        self.assertIsNone(map_state_votes(votes, "VA", "lower"))

    def test_empty_input_returns_none(self):
        self.assertIsNone(map_state_votes([], "VA", "lower"))

    def test_none_input_returns_none(self):
        self.assertIsNone(map_state_votes(None, "VA", "lower"))


class CountsMapping(unittest.TestCase):
    """OpenStates count keys vary — verify aggregation."""

    def test_absent_excused_not_voting_aggregate(self):
        votes = [_vote(
            chamber="lower",
            motion="H VOTE:",
            counts={"yes": 50, "no": 30, "absent": 5, "excused": 3, "not voting": 2},
        )]
        summary = _summary(map_state_votes(votes, "VA", "lower"))
        self.assertEqual(summary["not_voting"], 10)  # 5 + 3 + 2
        self.assertEqual(summary["yea"], 50)
        self.assertEqual(summary["nay"], 30)

    def test_abstain_separate_from_not_voting(self):
        votes = [_vote(
            chamber="lower",
            motion="H VOTE:",
            counts={"yes": 60, "no": 35, "abstain": 5},
        )]
        summary = _summary(map_state_votes(votes, "VA", "lower"))
        self.assertEqual(summary["present"], 5)
        self.assertEqual(summary["not_voting"], 0)


if __name__ == "__main__":
    unittest.main()
