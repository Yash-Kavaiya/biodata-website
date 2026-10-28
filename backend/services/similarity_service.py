"""
Similarity Service - weighted attribute matching for finding compatible profiles.
"""
import heapq
from typing import List, Optional, Tuple

from backend.models import BiodataInDB, Gender, MatchResult, SearchPreferences

# Relative importance of each criterion. Scores are normalized over the
# criteria actually supplied, so a search on one field can still reach 100%.
WEIGHTS = {
    "age": 0.15,
    "gender": 0.20,
    "religion": 0.15,
    "caste": 0.10,
    "education": 0.15,
    "occupation": 0.10,
    "location": 0.10,
    "marital_status": 0.05,
}


def _fuzzy_match(query: Optional[str], target: Optional[str]) -> bool:
    """Case-insensitive containment match in either direction."""
    if not query or not target:
        return False
    q, t = query.lower().strip(), target.lower().strip()
    return bool(q and t) and (q in t or t in q)


class SimilarityService:
    """Scores biodatas against search preferences."""

    def has_criteria(self, preferences: SearchPreferences) -> bool:
        return any(v not in (None, "") for v in preferences.model_dump().values())

    async def find_matches(
        self,
        preferences: SearchPreferences,
        biodatas: List[BiodataInDB],
        limit: int = 10,
    ) -> List[MatchResult]:
        """Return the top `limit` biodatas by match score (O(n log k))."""
        heap: List[Tuple[float, int, BiodataInDB, List[str]]] = []
        for idx, biodata in enumerate(biodatas):
            score, reasons = self.calculate_match_score(preferences, biodata)
            if score <= 0:
                continue
            entry = (score, -idx, biodata, reasons)  # -idx keeps earlier items on ties
            if len(heap) < limit:
                heapq.heappush(heap, entry)
            elif entry[:2] > heap[0][:2]:
                heapq.heapreplace(heap, entry)

        ranked = sorted(heap, key=lambda e: e[:2], reverse=True)
        return [
            MatchResult(biodata=b, similarity_score=round(score, 4), match_reasons=reasons)
            for score, _, b, reasons in ranked
        ]

    async def find_similar_profiles(
        self,
        source_biodata: BiodataInDB,
        biodatas: List[BiodataInDB],
        limit: int = 10,
    ) -> List[MatchResult]:
        """Find compatible profiles for a given biodata (opposite gender, similar age/community)."""
        opposite = {Gender.MALE: Gender.FEMALE, Gender.FEMALE: Gender.MALE}
        preferences = SearchPreferences(
            gender=opposite.get(source_biodata.gender),
            religion=source_biodata.religion,
            caste=source_biodata.caste,
            min_age=source_biodata.age - 5 if source_biodata.age else None,
            max_age=source_biodata.age + 5 if source_biodata.age else None,
        )
        # Gender is a hard filter here, not just a weighted criterion: a same-gender
        # profile must never surface just because the age happens to fit.
        candidates = [
            b for b in biodatas
            if b.id != source_biodata.id
            and not (preferences.gender and b.gender and b.gender != preferences.gender)
        ]
        return await self.find_matches(preferences, candidates, limit)

    def calculate_match_score(
        self,
        preferences: SearchPreferences,
        biodata: BiodataInDB,
    ) -> Tuple[float, List[str]]:
        """Return (score in 0..1, human-readable match reasons)."""
        score = 0.0
        max_score = 0.0
        reasons: List[str] = []

        def check(key: str, matched: bool, reason: str):
            nonlocal score, max_score
            max_score += WEIGHTS[key]
            if matched:
                score += WEIGHTS[key]
                reasons.append(reason)

        if preferences.min_age is not None or preferences.max_age is not None:
            age = biodata.age
            in_range = (
                age is not None
                and (preferences.min_age is None or age >= preferences.min_age)
                and (preferences.max_age is None or age <= preferences.max_age)
            )
            check("age", in_range, f"Age: {age} years")

        if preferences.gender:
            check("gender", biodata.gender == preferences.gender,
                  f"Gender: {biodata.gender.value if biodata.gender else ''}")

        if preferences.religion:
            check("religion", _fuzzy_match(preferences.religion, biodata.religion), f"Religion: {biodata.religion}")

        if preferences.caste:
            check("caste", _fuzzy_match(preferences.caste, biodata.caste), f"Caste: {biodata.caste}")

        if preferences.education:
            check("education", _fuzzy_match(preferences.education, biodata.education),
                  f"Education: {biodata.education}")

        if preferences.occupation:
            check("occupation", _fuzzy_match(preferences.occupation, biodata.occupation),
                  f"Occupation: {biodata.occupation}")

        if preferences.location:
            places = [biodata.current_city, biodata.state, biodata.native_place, biodata.country]
            hit = next((p for p in places if _fuzzy_match(preferences.location, p)), None)
            check("location", hit is not None, f"Location: {hit}")

        if preferences.marital_status:
            check("marital_status", biodata.marital_status == preferences.marital_status,
                  f"Marital Status: {preferences.marital_status.value}")

        return (score / max_score if max_score > 0 else 0.0), reasons


# Singleton instance
similarity_service = SimilarityService()
