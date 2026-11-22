"""Lightweight keyword heuristic for the academic domain.

This is only a *hint* passed into P01 (and a fallback label if analysis
fails); the LLM makes the final decision. It is intentionally simple and
not a whitelist of supported subjects.
"""
from __future__ import annotations

import re
from collections import Counter

DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "mathematics": ["theorem", "proof", "lemma", "equation", "integral", "derivative", "matrix", "vector", "polynomial", "algebra", "calculus", "probability", "function"],
    "physical_sciences": ["force", "energy", "velocity", "acceleration", "momentum", "particle", "wave", "electron", "reaction", "molecule", "thermodynamics", "quantum", "newton"],
    "life_sciences": ["cell", "protein", "dna", "gene", "organism", "enzyme", "species", "tissue", "photosynthesis", "evolution", "membrane"],
    "computer_science": ["algorithm", "program", "function", "variable", "network", "protocol", "data structure", "complexity", "compiler", "database", "software", "packet", "python", "java"],
    "engineering": ["circuit", "voltage", "design", "load", "stress", "signal", "control system", "torque", "resistor", "material"],
    "humanities": ["century", "empire", "revolution", "war", "dynasty", "philosophy", "historian", "treaty", "monarchy", "colonial"],
    "social_sciences": ["society", "social", "policy", "behaviour", "behavior", "culture", "population", "survey", "psychology", "economy", "inflation", "demand", "supply"],
    "business_management": ["management", "marketing", "strategy", "organisation", "organization", "customer", "finance", "leadership", "stakeholder", "profit", "business"],
    "languages_literature": ["novel", "poem", "poetry", "author", "narrative", "character", "grammar", "literary", "metaphor"],
    "law": ["court", "statute", "plaintiff", "defendant", "contract", "liability", "jurisdiction", "legislation"],
    "medicine_health": ["patient", "diagnosis", "treatment", "clinical", "disease", "symptom", "therapy", "dosage"],
}


def detect_domain(text: str) -> tuple[str, dict[str, int]]:
    lowered = text.lower()
    scores: Counter = Counter()
    for domain, words in DOMAIN_KEYWORDS.items():
        for w in words:
            scores[domain] += len(re.findall(r"\b" + re.escape(w) + r"s?\b", lowered))
    if not scores or scores.most_common(1)[0][1] == 0:
        return "other", dict(scores)
    return scores.most_common(1)[0][0], dict(scores)
