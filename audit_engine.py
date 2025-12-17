import os
from openai import OpenAI
from pydantic import BaseModel, Field
from typing import Literal

# --- 1. Define the Structures (The "Form" the AI must fill out) ---
class ReasoningLog(BaseModel):
    Population_Check: bool = Field(description="Does it strictly meet the user's defined Population?")
    Intervention_Check: bool = Field(description="Does it strictly meet the user's defined Intervention?")
    Comparator_Check: bool = Field(description="Does it strictly meet the user's defined Comparator?")
    Outcome_Check: bool = Field(description="Does it strictly meet the user's defined Outcome?")
    StudyDesign_Check: bool = Field(description="Does it strictly meet the user's defined Study Design?")
    Summary_Judgment: str = Field(description="A 1-sentence summary of why the decision was made.")

class ScreeningDecision(BaseModel):
    ScreeningDecision: Literal["INCLUDE", "EXCLUDE", "UNCLEAR"] = Field(description="Final decision.")
    ExclusionReason: str = Field(description="Short reason code if EXCLUDED. Empty if INCLUDE.")
    ReasoningLog: ReasoningLog

# --- 2. The Analysis Function ---
def analyze_abstract(title, abstract, pico_criteria, api_key):
    """
    Accepts title, abstract, PICO criteria, and the API key.
    Returns a structured audit decision.
    """
    
    # Initialize the client with the key provided by the user
    client = OpenAI(api_key=api_key)
    
    system_prompt = f"""
    You are an expert Cochrane Reviewer. Screen this study based on these EXACT criteria:
    
    1. POPULATION: {pico_criteria['P']}
    2. INTERVENTION: {pico_criteria['I']}
    3. COMPARATOR: {pico_criteria['C']}
    4. OUTCOME: {pico_criteria['O']}
    5. STUDY DESIGN: {pico_criteria['S']}
    
    RULES:
    - Sensitivity > 99%: If vague, missing info, or unsure, select 'UNCLEAR'.
    - ONLY 'INCLUDE' if all 5 criteria are met or strongly implied.
    - ONLY 'EXCLUDE' if there is a clear violation.
    """

    user_content = f"TITLE: {title}\n\nABSTRACT: {abstract}"

    completion = client.beta.chat.completions.parse(
        model="gpt-4o-2024-08-06",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        response_format=ScreeningDecision,
    )

    return completion.choices[0].message.parsed