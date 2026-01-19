"""
Similarity Service - PKL-based similarity search for match finding.
Follows Single Responsibility Principle.
"""
import pickle
import os
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import math

from backend.config import settings
from backend.models import BiodataInDB, SearchPreferences, MatchResult


class SimilarityService:
    """
    Service for finding matching biodatas based on preferences.
    Uses pickle file to store and retrieve embeddings/features.
    """

    def __init__(self, pkl_path: Optional[Path] = None):
        self.pkl_path = pkl_path or settings.PKL_FILE_PATH
        self._ensure_pkl_exists()

    def _ensure_pkl_exists(self):
        """Create pickle file if it doesn't exist."""
        self.pkl_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.pkl_path.exists():
            self._save_data({"features": {}, "metadata": {"version": "1.0", "updated_at": datetime.utcnow().isoformat()}})

    def _load_data(self) -> Dict[str, Any]:
        """Load data from pickle file."""
        try:
            with open(self.pkl_path, "rb") as f:
                return pickle.load(f)
        except (pickle.PickleError, FileNotFoundError):
            return {"features": {}, "metadata": {"version": "1.0"}}

    def _save_data(self, data: Dict[str, Any]):
        """Save data to pickle file."""
        data["metadata"]["updated_at"] = datetime.utcnow().isoformat()
        with open(self.pkl_path, "wb") as f:
            pickle.dump(data, f)

    def _extract_features(self, biodata: BiodataInDB) -> Dict[str, Any]:
        """
        Extract searchable features from biodata.

        Args:
            biodata: BiodataInDB instance

        Returns:
            Dictionary of normalized features
        """
        features = {
            "id": biodata.id,
            "age": biodata.age,
            "gender": biodata.gender.value if biodata.gender else None,
            "religion": self._normalize_string(biodata.religion),
            "caste": self._normalize_string(biodata.caste),
            "education": self._normalize_string(biodata.education),
            "occupation": self._normalize_string(biodata.occupation),
            "location": self._normalize_string(
                f"{biodata.current_city or ''} {biodata.state or ''} {biodata.country or ''}"
            ),
            "marital_status": biodata.marital_status.value if biodata.marital_status else None,
            "income": self._parse_income(biodata.income),
            "height": self._parse_height(biodata.height),
        }
        return features

    def _normalize_string(self, s: Optional[str]) -> Optional[str]:
        """Normalize string for comparison."""
        if not s:
            return None
        return s.lower().strip()

    def _parse_income(self, income_str: Optional[str]) -> Optional[float]:
        """Parse income string to numeric value (in lakhs)."""
        if not income_str:
            return None
        try:
            # Extract numbers from string
            numbers = re.findall(r"[\d.]+", income_str)
            if numbers:
                value = float(numbers[0])
                # Convert to lakhs if in different format
                if "crore" in income_str.lower():
                    value *= 100
                elif "k" in income_str.lower():
                    value /= 100
                return value
        except (ValueError, IndexError):
            pass
        return None

    def _parse_height(self, height_str: Optional[str]) -> Optional[float]:
        """Parse height string to cm."""
        if not height_str:
            return None
        try:
            # Handle feet/inches format
            if "'" in height_str or "ft" in height_str.lower():
                parts = re.findall(r"(\d+)", height_str)
                if len(parts) >= 1:
                    feet = int(parts[0])
                    inches = int(parts[1]) if len(parts) > 1 else 0
                    return (feet * 30.48) + (inches * 2.54)
            # Handle cm format
            numbers = re.findall(r"[\d.]+", height_str)
            if numbers:
                return float(numbers[0])
        except (ValueError, IndexError):
            pass
        return None

    async def index_biodata(self, biodata: BiodataInDB):
        """
        Add or update biodata in the similarity index.

        Args:
            biodata: BiodataInDB to index
        """
        data = self._load_data()
        features = self._extract_features(biodata)
        data["features"][biodata.id] = features
        self._save_data(data)

    async def remove_from_index(self, biodata_id: str):
        """Remove biodata from similarity index."""
        data = self._load_data()
        if biodata_id in data["features"]:
            del data["features"][biodata_id]
            self._save_data(data)

    async def find_matches(
        self,
        preferences: SearchPreferences,
        biodatas: List[BiodataInDB],
        limit: int = 10
    ) -> List[MatchResult]:
        """
        Find matching biodatas based on preferences.

        Args:
            preferences: Search preferences
            biodatas: List of biodatas to search through
            limit: Maximum number of results

        Returns:
            List of MatchResult sorted by similarity score
        """
        results = []

        for biodata in biodatas:
            score, reasons = self._calculate_match_score(preferences, biodata)
            if score > 0:
                results.append(MatchResult(
                    biodata=biodata,
                    similarity_score=score,
                    match_reasons=reasons
                ))

        # Sort by score descending
        results.sort(key=lambda x: x.similarity_score, reverse=True)

        return results[:limit]

    async def find_similar_profiles(
        self,
        source_biodata: BiodataInDB,
        biodatas: List[BiodataInDB],
        limit: int = 10
    ) -> List[MatchResult]:
        """
        Find profiles similar to a given biodata.

        Args:
            source_biodata: Source biodata to match against
            biodatas: List of biodatas to search through
            limit: Maximum number of results

        Returns:
            List of similar profiles
        """
        # Convert source biodata to preferences
        gender_pref = None
        if source_biodata.gender:
            # Opposite gender preference
            gender_pref = "female" if source_biodata.gender.value == "male" else "male"

        preferences = SearchPreferences(
            gender=gender_pref,
            religion=source_biodata.religion,
            caste=source_biodata.caste,
            min_age=source_biodata.age - 5 if source_biodata.age else None,
            max_age=source_biodata.age + 5 if source_biodata.age else None,
        )

        # Filter out the source biodata itself
        filtered_biodatas = [b for b in biodatas if b.id != source_biodata.id]

        return await self.find_matches(preferences, filtered_biodatas, limit)

    def _calculate_match_score(
        self,
        preferences: SearchPreferences,
        biodata: BiodataInDB
    ) -> Tuple[float, List[str]]:
        """
        Calculate match score between preferences and biodata.

        Args:
            preferences: Search preferences
            biodata: Biodata to score

        Returns:
            Tuple of (score 0-1, list of match reasons)
        """
        score = 0.0
        max_score = 0.0
        reasons = []

        # Age matching (weight: 0.15)
        if preferences.min_age is not None or preferences.max_age is not None:
            max_score += 0.15
            if biodata.age:
                age_match = True
                if preferences.min_age and biodata.age < preferences.min_age:
                    age_match = False
                if preferences.max_age and biodata.age > preferences.max_age:
                    age_match = False
                if age_match:
                    score += 0.15
                    reasons.append(f"Age: {biodata.age} years")

        # Gender matching (weight: 0.2)
        if preferences.gender:
            max_score += 0.2
            if biodata.gender and biodata.gender.value == preferences.gender:
                score += 0.2
                reasons.append(f"Gender: {biodata.gender.value}")

        # Religion matching (weight: 0.15)
        if preferences.religion:
            max_score += 0.15
            if biodata.religion and self._fuzzy_match(preferences.religion, biodata.religion):
                score += 0.15
                reasons.append(f"Religion: {biodata.religion}")

        # Caste matching (weight: 0.1)
        if preferences.caste:
            max_score += 0.1
            if biodata.caste and self._fuzzy_match(preferences.caste, biodata.caste):
                score += 0.1
                reasons.append(f"Caste: {biodata.caste}")

        # Education matching (weight: 0.15)
        if preferences.education:
            max_score += 0.15
            if biodata.education and self._fuzzy_match(preferences.education, biodata.education):
                score += 0.15
                reasons.append(f"Education: {biodata.education}")

        # Occupation matching (weight: 0.1)
        if preferences.occupation:
            max_score += 0.1
            if biodata.occupation and self._fuzzy_match(preferences.occupation, biodata.occupation):
                score += 0.1
                reasons.append(f"Occupation: {biodata.occupation}")

        # Location matching (weight: 0.1)
        if preferences.location:
            max_score += 0.1
            location_str = f"{biodata.current_city or ''} {biodata.state or ''}"
            if self._fuzzy_match(preferences.location, location_str):
                score += 0.1
                reasons.append(f"Location: {biodata.current_city or biodata.state}")

        # Marital status matching (weight: 0.05)
        if preferences.marital_status:
            max_score += 0.05
            if biodata.marital_status and biodata.marital_status == preferences.marital_status:
                score += 0.05
                reasons.append(f"Marital Status: {biodata.marital_status.value}")

        # Normalize score
        final_score = score / max_score if max_score > 0 else 0.0

        return final_score, reasons

    def _fuzzy_match(self, query: str, target: str) -> bool:
        """Simple fuzzy string matching."""
        if not query or not target:
            return False
        query_lower = query.lower().strip()
        target_lower = target.lower().strip()
        return query_lower in target_lower or target_lower in query_lower


# Singleton instance
similarity_service = SimilarityService()
