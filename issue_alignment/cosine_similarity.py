from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import numpy as np
import pandas as pd
from openai import OpenAI
import os
import re
from extract_openai_response_text import extract_response_text

@dataclass
class UserPreference:
    issue: str
    importance: float
    statement: str

try:
    from credentials import RAYNA_OPENAI_API_KEY
except ImportError as exc:
    raise RuntimeError("credentials.py must define OPENAI_API_KEY for OpenAI access") from exc

os.environ["OPENAI_API_KEY"] = RAYNA_OPENAI_API_KEY
client = OpenAI()

def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    if np.linalg.norm(a) == 0 or np.linalg.norm(b) == 0:
        return 0.0
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def score_candidates_against_preferences(
    user_prefs: List[UserPreference],
    candidate_embeddings: Dict[str, Dict[str, Dict[str, List[float]]]],
) -> Dict[str, float]:
    """Compute weighted cosine similarity for each candidate with issue normalization."""
    scores: Dict[str, float] = {candidate_id: 0.0 for candidate_id in candidate_embeddings.keys()}

    # Pre-compute similarities per issue
    issue_similarities: Dict[str, Dict[str, float]] = {}
    for pref in user_prefs:
        sims_for_issue: Dict[str, float] = {}
        pref_vector = np.array(pref.statement_embedding, dtype=float)
        for candidate_id, issues in candidate_embeddings.items():
            entry = issues.get(pref.issue)
            if entry is None:
                continue
            embedding = entry.get("embedding")
            candidate_vector = np.array(embedding, dtype=float)
            sim = cosine_similarity(pref_vector, candidate_vector)
            sims_for_issue[candidate_id] = sim
        if sims_for_issue:
            issue_similarities[pref.issue] = sims_for_issue

    for pref in user_prefs:
        sims_for_issue = issue_similarities.get(pref.issue)
        if not sims_for_issue:
            continue
        min_similarity = min(sims_for_issue.values())
        if abs(min_similarity) < 1e-9:
            min_similarity = 1e-9
        for candidate_id, similarity in sims_for_issue.items():
            normalized_similarity = similarity / min_similarity
            scores[candidate_id] += pref.importance * normalized_similarity

    return scores


CANDIDATE_STANCES_CSV = "issue_alignment/candidate_stances1.csv"
CANDIDATE_DATA_CSV = "issue_alignment/candidate_data1.csv"
EMBED_DIM = None  # updated dynamically


def load_candidate_embeddings(csv_path: str = CANDIDATE_STANCES_CSV) -> Dict[str, Dict[str, List[float]]]:
    """Load candidate embeddings from CSV into nested dictionary."""
    df = pd.read_csv(csv_path)
    embeddings: Dict[str, Dict[str, Dict[str, List[float]]]] = {}
    statements_map: Dict[str, List[str]] = {}

    for _, row in df.iterrows():
        candidate_id = row["candidate_id"]
        issue_name = row["issue_name"].strip().upper()
        statement = row["statement"]
        embedding = eval_embedding(row["embedding"])  # expects list-like string

        embeddings.setdefault(candidate_id, {})[issue_name] = {
            "statement": statement,
            "embedding": embedding
        }
        statements_map.setdefault(candidate_id, []).append(f"{issue_name}: {statement}")

    return embeddings, statements_map


def eval_embedding(value: str) -> List[float]:
    """Convert string representation of embedding to list of floats."""
    if isinstance(value, list):
        return [float(x) for x in value]
    cleaned = value.strip()
    if cleaned.startswith("[") and cleaned.endswith("]"):
        return [float(x) for x in cleaned[1:-1].split(",")]
    raise ValueError(f"Invalid embedding format: {value}")


def build_user_preference_embeddings(user_prefs: List[UserPreference]) -> None:
    """Use the openai api to build embeddings for the user preferences."""
    for pref in user_prefs:
        pref.statement_embedding = client.embeddings.create(
            input=pref.statement,
            model="text-embedding-3-small"
        ).data[0].embedding
    return user_prefs


def get_alignment_rating(user_summary: str, candidate_statements: str) -> int:
    """Ask GPT to rate alignment 1-10 and return the integer rating."""
    prompt = (
        "You are evaluating political alignment."
        "\nUser preferences:\n"
        f"{user_summary}\n\n"
        "Candidate statements:\n"
        f"{candidate_statements}\n\n"
        "Rate, on a scale of 1 to 10, how strongly the candidate agrees with the user. This should depend on whether the candidate addresses the user's main issues."
        " Output ONLY the number."
    )

    response = client.responses.create(
        model="gpt-4o-mini",
        input=prompt
    )

    text = extract_response_text(response).strip()
    match = re.search(r"(10|[1-9])", text)
    if match:
        return int(match.group(1))
    return 0


def get_all_issues():
    """Get all issues from the candidate embeddings."""
    candidate_embeddings, statements_map = load_candidate_embeddings()
    return list(set(issue for issues in candidate_embeddings.values() for issue in issues.keys()))

def print_all_abortion_statements():
    """Print all abortion statements from the candidate embeddings."""
    candidate_embeddings, statements_map = load_candidate_embeddings()
    for candidate_id, issues in candidate_embeddings.items():
        for issue, entry in issues.items():
            if issue == "ABORTION / CONTRACEPTION":
                print(f"Candidate: {candidate_id}")
                print(f"Statement: {entry['statement']}")
                print("--------------------------------")

def main():
    candidate_embeddings, statements_map = load_candidate_embeddings()
    candidate_data = pd.read_csv(CANDIDATE_DATA_CSV)
    user_prefs = [
        #UserPreference(issue="ECONOMY", importance=8, statement="Boost small business support."),
        #UserPreference(issue="HEALTHCARE", importance=6, statement="Expand affordable care."),
        UserPreference(issue="IMMIGRATION", importance=10, statement="We need to secure our borders and enforce immigration laws."),
        UserPreference(issue="ABORTION / CONTRACEPTION", importance=6, statement="We must protect the lives of unborn children.")
    ]

    # In practice, create embeddings for user statements
    build_user_preference_embeddings(user_prefs)

    scores = score_candidates_against_preferences(user_prefs, candidate_embeddings)
    scored_df = pd.DataFrame(
        [
            {
                "candidate_id": candidate_id,
                "similarity_score": score,
                "statements": "\n".join(statements_map.get(candidate_id, [])),
            }
            for candidate_id, score in scores.items()
        ]
    )
    scored_df = scored_df.merge(candidate_data[["candidate_id", "candidate_name"]], on="candidate_id", how="left")
    scored_df = scored_df[["candidate_id", "candidate_name", "similarity_score", "statements"]]

    scored_df.to_csv("issue_relevance_scores.csv", index=False)
    top = scored_df.sort_values(by="similarity_score", ascending=False).head(20).copy()
    top["similarity_score"] = top["similarity_score"].map(lambda x: f"{x:.3f}")
    display_cols = ["candidate_name", "similarity_score", "statements"]
    print("\nTop", len(top), "Candidates by Similarity:\n")
    user_summary = "\n".join(
        f"Issue: {pref.issue}, Importance: {pref.importance}, Statement: {pref.statement}"
        for pref in user_prefs
    )

    def display_candidate_statements(candidate_id):
        """Display the candidate statements about only the user's issues."""
        candidate_statements = "\n".join(
            stmt
            for stmt in statements_map.get(candidate_id, [])
            if stmt.split(":", 1)[0] in user_issue_set
        )
        return candidate_statements

    gpt_scores = []
    user_issue_set = {pref.issue for pref in user_prefs}
    for _, row in top.iterrows():
        # get the candidate statements about only the user's issues
        candidate_statements = display_candidate_statements(row["candidate_id"])
        rating = get_alignment_rating(user_summary, candidate_statements)
        gpt_scores.append(rating)
        print(f"Candidate: {row['candidate_name']}")
        print(f"Traditional Similarity Score: {row['similarity_score']}")
        print(f"GPT Alignment Rating: {rating}")
        print(f"Statements:\n{candidate_statements}")
        print("--------------------------------")

    top["gpt_alignment_score"] = gpt_scores
    top["issue_relevance_score"] = top["gpt_alignment_score"]

    top.to_csv("issue_relevance_scores.csv", index=False)
    #print ("All issues: ", get_all_issues())
    '''
    All issues:  ['TAXES / BUDGET', 'EDUCATION', 'CIVIL RIGHTS', 'ABORTION / CONTRACEPTION',
    'IMMIGRATION', 'DRUG POLICY', 'CRIMINAL JUSTICE / PUBLIC SAFETY', 'DEFENSE / VETERANS',
    'ECONOMY', 'GUNS', 'SOCIAL SERVICES', 'HEALTHCARE', 'ENVIRONMENT / ENERGY', 'ARTS / CULTURE',
    'WAGES / JOB BENEFITS', 'HOUSING', 'INFRASTRUCTURE / TRANSPORTATION', 'LEGISLATION', 'GOVERNMENT REFORM']
    '''
    #print_all_abortion_statements()


if __name__ == "__main__":
    main()
