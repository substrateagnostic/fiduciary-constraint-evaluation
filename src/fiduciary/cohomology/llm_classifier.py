"""
LLM-based drift classification.

This module provides an LLM classifier for semantic drift detection.
It prompts the model to analyze user text against the contract
and extract implicit constraints.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Protocol

from fiduciary.cohomology.detector import DriftClassification


# Classification prompt template
CLASSIFICATION_PROMPT = '''You are analyzing whether user text is compatible with an established intent contract.

## Contract Information

**Objective:** {objective}

**Current Constraints:**
{constraints_description}

{prior_context_section}

## User Text to Analyze

{segment_text}

## Your Task

Analyze the user text and determine:
1. Does it align with, refine, extend, or pivot away from the stated objective?
2. What implicit constraints does it introduce?
3. Are there any conflicts with existing constraints?

Respond in JSON format:
{{
  "classification": "continuation|refinement|extension|pivot|contradiction|adversarial",
  "confidence": 0.0-1.0,
  "implicit_constraints": [
    {{
      "topic": "what the constraint is about",
      "polarity": "positive|negative",
      "confidence": 0.0-1.0,
      "evidence": "the text that implies this"
    }}
  ],
  "derived_objective": "if pivot detected, what the new objective appears to be",
  "conflicts": [
    {{
      "existing_constraint": "description of existing constraint",
      "new_requirement": "what the user text implies",
      "conflict_type": "contradiction|relaxation|tightening"
    }}
  ],
  "reasoning": "brief explanation of your classification"
}}

Classification meanings:
- continuation: Aligns with stated objective, no change needed
- refinement: Clarifies or narrows the objective (compatible)
- extension: Adds scope but remains compatible (may need acknowledgment)
- pivot: Fundamentally different direction (needs contract amendment)
- contradiction: Conflicts with existing constraints (violation)
- adversarial: Appears to be attempting to circumvent constraints'''


class ModelProvider(Protocol):
    """Protocol for model providers that can generate text."""

    def generate(self, prompt: str, temperature: float = 0.0) -> str:
        """Generate text from prompt. Returns the generated text."""
        ...


@dataclass
class ClassifierConfig:
    """Configuration for the LLM classifier."""
    model_provider: ModelProvider
    temperature: float = 0.0  # Low temp for classification
    max_retries: int = 2
    timeout: float = 5.0


class LLMDriftClassifier:
    """
    LLM-based drift classifier.

    Uses a language model to semantically analyze user text
    against the contract objective and constraints.
    """

    def __init__(self, config: ClassifierConfig):
        self.config = config

    def classify(
        self,
        segment_text: str,
        objective: str,
        constraints_description: str,
        prior_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Classify user text for drift using LLM.

        Returns dict with classification results.
        """
        # Build prior context section
        prior_context_section = ""
        if prior_context:
            prior_context_section = f"**Prior Context:**\n{prior_context}\n"

        # Build prompt
        prompt = CLASSIFICATION_PROMPT.format(
            objective=objective,
            constraints_description=constraints_description,
            prior_context_section=prior_context_section,
            segment_text=segment_text,
        )

        # Call model
        response_text = self.config.model_provider.generate(
            prompt=prompt,
            temperature=self.config.temperature,
        )

        # Parse response
        return self._parse_response(response_text)

    def _parse_response(self, response_text: str) -> Dict[str, Any]:
        """
        Parse LLM response into structured format.

        Handles various response formats and extraction from markdown code blocks.
        """
        # Try to extract JSON from response
        text = response_text.strip()

        # Handle markdown code blocks
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            text = text[start:end].strip()
        elif "```" in text:
            start = text.index("```") + 3
            end = text.index("```", start)
            text = text[start:end].strip()

        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            # If JSON parsing fails, return a default with low confidence
            return {
                "classification": "continuation",
                "confidence": 0.3,
                "implicit_constraints": [],
                "reasoning": "Failed to parse LLM response",
                "raw_response": response_text,
            }

        # Validate and normalize classification
        classification = result.get("classification", "continuation")
        # Handle case where LLM returns a list instead of string
        if isinstance(classification, list):
            classification = classification[0] if classification else "continuation"
        classification = str(classification).lower()
        valid_classifications = {c.value for c in DriftClassification}
        if classification not in valid_classifications:
            classification = "continuation"

        result["classification"] = classification

        # Ensure confidence is in valid range
        confidence = result.get("confidence", 0.5)
        result["confidence"] = max(0.0, min(1.0, float(confidence)))

        # Ensure implicit_constraints is a list
        if "implicit_constraints" not in result:
            result["implicit_constraints"] = []

        return result


class CachedLLMClassifier:
    """
    Caching wrapper around LLM classifier.

    Caches classifications by hash of (segment_text, objective, constraints).
    Useful for reducing redundant LLM calls in testing or when
    the same text is checked multiple times.
    """

    def __init__(
        self,
        classifier: LLMDriftClassifier,
        cache_size: int = 100,
    ):
        self.classifier = classifier
        self.cache_size = cache_size
        self._cache: Dict[str, Dict[str, Any]] = {}

    def _cache_key(
        self,
        segment_text: str,
        objective: str,
        constraints_description: str,
    ) -> str:
        """Generate cache key from inputs."""
        import hashlib
        combined = f"{segment_text}|{objective}|{constraints_description}"
        return hashlib.sha256(combined.encode()).hexdigest()[:16]

    def classify(
        self,
        segment_text: str,
        objective: str,
        constraints_description: str,
        prior_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Classify with caching."""
        key = self._cache_key(segment_text, objective, constraints_description)

        if key in self._cache:
            result = self._cache[key].copy()
            result["cached"] = True
            return result

        result = self.classifier.classify(
            segment_text=segment_text,
            objective=objective,
            constraints_description=constraints_description,
            prior_context=prior_context,
        )

        # Manage cache size (simple LRU approximation)
        if len(self._cache) >= self.cache_size:
            # Remove oldest entry
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]

        self._cache[key] = result
        return result

    def clear_cache(self) -> None:
        """Clear the classification cache."""
        self._cache.clear()


class MockLLMClassifier:
    """
    Mock LLM classifier for testing.

    Can be configured with scripted responses or simple heuristics.
    """

    def __init__(self, responses: Optional[Dict[str, Dict[str, Any]]] = None):
        """
        Args:
            responses: Dict mapping segment_text patterns to classification results.
                       Uses simple substring matching.
        """
        self.responses = responses or {}
        self.call_count = 0
        self.last_call: Optional[Dict[str, str]] = None

    def classify(
        self,
        segment_text: str,
        objective: str,
        constraints_description: str,
        prior_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return scripted or default response."""
        self.call_count += 1
        self.last_call = {
            "segment_text": segment_text,
            "objective": objective,
            "constraints_description": constraints_description,
        }

        # Check for matching scripted response
        for pattern, response in self.responses.items():
            if pattern.lower() in segment_text.lower():
                return response.copy()

        # Default: simple keyword-based classification
        lowered = segment_text.lower()

        if any(kw in lowered for kw in ["actually,", "on second thought", "let's pivot"]):
            return {
                "classification": "pivot",
                "confidence": 0.8,
                "implicit_constraints": [],
                "derived_objective": segment_text[:100],
                "reasoning": "Detected pivot keywords",
            }

        if any(kw in lowered for kw in ["ignore", "disregard", "pretend", "bypass"]):
            return {
                "classification": "adversarial",
                "confidence": 0.9,
                "implicit_constraints": [],
                "reasoning": "Detected adversarial keywords",
            }

        return {
            "classification": "continuation",
            "confidence": 0.6,
            "implicit_constraints": [],
            "reasoning": "No drift signals detected",
        }


def create_llm_classifier(
    model_provider: Optional[ModelProvider] = None,
    use_cache: bool = True,
    cache_size: int = 100,
) -> Optional[LLMDriftClassifier]:
    """
    Factory function to create an LLM classifier.

    If model_provider is None, returns None (use keyword fallback).
    """
    if model_provider is None:
        return None

    config = ClassifierConfig(model_provider=model_provider)
    classifier = LLMDriftClassifier(config)

    if use_cache:
        return CachedLLMClassifier(classifier, cache_size=cache_size)

    return classifier
