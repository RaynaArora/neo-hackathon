import os
from openai import OpenAI
import json

try:
    from credentials import RAYNA_OPENAI_API_KEY
except ImportError as exc:
    raise RuntimeError("credentials.py must define OPENAI_API_KEY for OpenAI access") from exc

os.environ["OPENAI_API_KEY"] = RAYNA_OPENAI_API_KEY
client = OpenAI()


def extract_response_text(response) -> str:
    """Return the first text segment from an OpenAI response object."""
    # New style: response.output -> list of messages -> list of content blocks
    for message in getattr(response, "output", []) or []:
        for block in getattr(message, "content", []) or []:
            text = getattr(block, "text", None)
            if text:
                return text

    # Legacy style: response.content may be list-like or object with .text
    content = getattr(response, "content", None)
    if isinstance(content, (list, tuple)):
        for block in content:
            text = getattr(block, "text", None)
            if text:
                return text
    text = getattr(content, "text", None)
    if text:
        return text

    return ""


from get_civicengine_stances import get_elections_with_candidate_stances
#elections = get_elections_with_candidate_stances(max_elections=100, levels=["STATE", "FEDERAL", "LOCAL", "CITY"])
elections = None
#load elections from file if it exists
if os.path.exists("elections.json"):
    with open("elections.json", "r") as f:
        elections = json.load(f)
else:
    elections = get_elections_with_candidate_stances(max_elections=150)
    # store elections so they can be easily loaded later
    with open("elections.json", "w") as f:
        json.dump(elections, f)
    print ("Got elections: ", len(elections))

for election_id, election_data in elections.items():
    print ("Election: ", election_id)
    for race in election_data["races"]:
        print ("Race: ", race["id"])
        for candidacy in race["candidacies"]:
            print ("Candidacy: ", candidacy["id"])
    print ("--------------------------------")
#import a csv file with running dataset of candidate stances
import pandas as pd
i = 0
candidate_stances = pd.read_csv("candidate_stances.csv")
candidate_data = pd.read_csv("candidate_data.csv")
for election_id, election_data in elections.items():
    election_data = election_data["races"]
    for race in election_data:
        race_id = race["id"]
        race_data = race["candidacies"]
        for candidacy in race_data:
            candidacy_id = candidacy["id"]
            stances = candidacy["stances"]
            print ("Got candidate: ", candidacy["candidate"]["name"])
            if candidacy_id not in candidate_stances["candidate_id"]: # add new candidate to the datasets
                print ("Adding new candidate: ", candidacy["candidate"]["name"])
                candidate_data.loc[len(candidate_data)] = [
                    candidacy_id,
                    candidacy["candidate"]["name"],
                    [i for i in range(len(candidate_stances), len(candidate_stances) + len(stances))]
                ]
                for stance in stances:
                    issue_id = stance["issue"]["id"]
                    issue_name = stance["issue"]["name"]
                    stance_id = stance["id"]
                    stance_data = stance["statement"]
                    # use the openai api to condense the stance data into its key idea
                    response = client.responses.create(
                        model="gpt-4o-mini",
                        input="Condense the following political stance into its key idea of a few words. Don't output any other text than the key idea: " + stance_data
                    )
                    key_idea = extract_response_text(response)
                    if i < 5:
                        print(key_idea)
                        i += 1
                    embedding = client.embeddings.create(
                        input=key_idea,
                        model="text-embedding-3-small"
                    ).data[0].embedding

                    candidate_stances.loc[len(candidate_stances)] = [
                        candidacy_id,
                        issue_id,
                        issue_name,
                        embedding
                    ]

candidate_stances.to_csv("candidate_stances.csv", index=False)
candidate_data.to_csv("candidate_data.csv", index=False)