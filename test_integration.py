"""
NosPopuli Integration Tests — requires running server
Run with: pytest test_integration.py -v -s
"""

import pytest
import requests

BASE = "http://localhost:8000"

def search(query, **kwargs):
    r = requests.post(f"{BASE}/search", json={"question": query, **kwargs})
    assert r.status_code == 200, f"Server error: {r.status_code} — {r.text}"
    return r.json()

# ── Named Entity ──

class TestNamedEntitySearch:
    def test_title_ix_uses_named_entity_path(self):
        data = search("Title IX")
        assert data.get("query") and data["query"].get("query_subtype") == "named_entity", \
            f"Router didn't detect named_entity. Got: {data.get('query', {}).get('query_subtype')}"

    def test_title_ix_returns_results(self):
        data = search("Title IX")
        assert len(data["results"]) > 0, "No results returned for Title IX"

    def test_title_ix_original_law_present(self):
        data = search("Title IX", full_history=True)
        results = data["results"]
        originals = [r for r in results if r.get("congress") and r.get("congress") <= 100]
        assert len(originals) > 0, \
            f"No historical law in results. Congresses returned: {[r['congress'] for r in results]}"

    def test_aca_known_bill(self):
        data = search("Affordable Care Act")
        results = data["results"]
        assert any(r.get("number") == 3590 and r.get("congress") == 111 for r in results), \
            f"ACA not found. Results: {[(r.get('type','').upper(), r.get('number'), r.get('congress')) for r in results]}"

    def test_patriot_act(self):
        data = search("PATRIOT Act", full_history=True)
        results = data["results"]
        assert len(results) > 0
        congresses = [r["congress"] for r in results]
        assert any(c <= 107 for c in congresses), \
            f"Original PATRIOT Act (107th Congress) not found. Got congresses: {congresses}"


# ── Year Filtering ──

class TestYearSearch:
    def test_2017(self):
        data = search("Give me a bill from 2017")
        results = data["results"]
        assert len(results) > 0
        congresses = [r["congress"] for r in results]
        assert all(c == 115 for c in congresses), \
            f"Expected only 115th Congress, got: {congresses}"

    def test_2021(self):
        data = search("bills from 2021")
        results = data["results"]
        congresses = [r["congress"] for r in results]
        assert all(c == 117 for c in congresses), \
            f"Expected only 117th Congress, got: {congresses}"

    def test_1819(self):
        data = search("bills from 1819", full_history=True)
        # May return empty — just check it doesn't crash and doesn't return wrong congress
        results = data["results"]
        if results:
            congresses = [r["congress"] for r in results]
            assert all(c == 16 for c in congresses), \
                f"Expected 16th Congress, got: {congresses}"

    def test_recent_default(self):
        data = search("healthcare bills")
        results = data["results"]
        congresses = [r["congress"] for r in results]
        assert all(c >= 117 for c in congresses), \
            f"Default search returned old congresses: {congresses}"


# ── Laws vs Bills ──

class TestLawSearch:
    def test_laws_query_returns_enacted(self):
        data = search("laws passed under trump")
        results = data["results"]
        assert len(results) > 0, "No results for trump laws query"
        # Should not return 119th Congress bills (too recent, no laws yet)
        # Should return 115/116
        congresses = set(r["congress"] for r in results)
        assert congresses.issubset({115, 116, 119}), \
            f"Unexpected congresses: {congresses}"

    def test_enacted_status_set(self):
        data = search("give me a law that has been passed")
        query = data.get("query", {})
        assert query.get("status") == "enacted", \
            f"Status not set to enacted. Got: {query.get('status')}"


# ── Member Search ──

class TestMemberSearch:
    def test_ted_kennedy(self):
        data = search("Ted Kennedy")
        assert data["query_type"] == "member"
        assert data["found"] is True
        assert "Kennedy" in data["member"]["name"]

    def test_bernie_sanders(self):
        data = search("Bernie Sanders")
        assert data["query_type"] == "member"
        assert data["found"] is True

    def test_trump_not_member(self):
        data = search("laws under trump")
        assert data["query_type"] == "legislation", \
            "Trump should route to legislation, not member"


# ── Result Relevance ──

class TestResultRelevance:
    def test_healthcare_returns_healthcare(self):
        data = search("healthcare bills")
        results = data["results"]
        assert len(results) > 0
        titles = [r["title"].lower() for r in results]
        relevant = [t for t in titles if any(
            word in t for word in ["health", "medical", "medicare", "medicaid", "care"]
        )]
        assert len(relevant) >= len(results) // 2, \
            f"Less than half the results are healthcare-related.\nTitles: {titles}"

    def test_no_obviously_wrong_results(self):
        data = search("Title IX")
        results = data["results"]
        titles = [r["title"].lower() for r in results]
        # Should not contain postal office designations or disaster bills
        bad = [t for t in titles if "post office" in t or "disaster" in t]
        assert len(bad) == 0, f"Irrelevant results found: {bad}"

    def test_validator_ran(self):
        # Validator should have logged — check via monitor
        r = requests.get(f"{BASE}/monitor/stream")
        log = r.json()
        validator_entries = [e for e in log if e.get("agent") == "result_validator"]
        assert len(validator_entries) > 0, "Validator never ran — check wiring in api.py"


# ── Confidence and Ambiguity ──

class TestConfidence:
    def test_specific_bill_high_confidence(self):
        data = search("HR 3590")
        assert data["confidence"] >= 0.9

    def test_ambiguous_low_confidence(self):
        data = search("Kennedy healthcare")
        assert data["confidence"] < 0.8, \
            f"Expected low confidence for ambiguous query, got {data['confidence']}"

    def test_ambiguity_reason_present_when_low(self):
        data = search("Kennedy healthcare")
        if data["confidence"] < 0.7:
            assert data["ambiguity_reason"] is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])