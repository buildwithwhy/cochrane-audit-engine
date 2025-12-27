import streamlit as st
import pdfplumber
from openai import OpenAI
from pydantic import BaseModel, Field
from typing import Literal

# --- 1. CONNECT TO SECRETS ---
try:
    client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
except Exception:
    st.error("🚨 OpenAI API Key missing! Check your .streamlit/secrets.toml file.")
    st.stop()

# --- 2. DATA STRUCTURES (Enhanced for Granular Reasoning) ---
class ProtocolStructure(BaseModel):
    Population: str = Field(description="The specific population defined in the text.")
    Intervention: str = Field(description="The intervention being studied.")
    Comparator: str = Field(description="The comparator or control group.")
    Outcome: str = Field(description="The primary outcomes of interest.")
    StudyDesign: str = Field(description="The required study design (e.g., RCT).")
    Exclusion: str = Field(description="Any specific exclusion criteria mentioned.")

class ReasoningLog(BaseModel):
    # We now capture a short REASON for each check!
    Population_Check: bool = Field(description="Strictly meets Population criteria?")
    Population_Reason: str = Field(description="Very short reason (e.g. 'Wrong age group').")
    
    Intervention_Check: bool = Field(description="Strictly meets Intervention criteria?")
    Intervention_Reason: str = Field(description="Very short reason.")
    
    Comparator_Check: bool = Field(description="Strictly meets Comparator criteria?")
    Comparator_Reason: str = Field(description="Very short reason.")
    
    Outcome_Check: bool = Field(description="Strictly meets Outcome criteria?")
    Outcome_Reason: str = Field(description="Very short reason.")
    
    StudyDesign_Check: bool = Field(description="Strictly meets Study Design criteria?")
    StudyDesign_Reason: str = Field(description="Very short reason.")
    
    Exclusion_Check: bool = Field(description="Violates Exclusion Criteria? (True = Exclude)")
    Exclusion_Reason: str = Field(description="Which rule was violated?")

class ScreeningDecision(BaseModel):
    ScreeningDecision: Literal["INCLUDE", "EXCLUDE", "UNCLEAR"] = Field(description="Final decision.")
    Confidence_Score: int = Field(description="0-100 score. How confident are you in this decision based strictly on the text?")
    ExclusionReason: str = Field(description="Short reason code if EXCLUDED. Empty if INCLUDE.")
    Reasoning_Summary: str = Field(description="1-sentence summary of the decision logic.")
    ReasoningLog: ReasoningLog

# --- 3. HELPER: EXTRACT TEXT FROM PDF ---
def extract_text_from_pdf(uploaded_file):
    all_text = ""
    try:
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    all_text += text + "\n"
    except Exception as e:
        return f"Error reading PDF: {e}"
    return all_text

# --- 4. EXTRACT PICO ---
def extract_pico_criteria(protocol_text):
    system_prompt = """
    You are a Methodologist. Extract the strict PICO and Exclusion criteria.
    If not explicitly mentioned, fill with "Not Specified".
    """
    completion = client.beta.chat.completions.parse(
        model="gpt-4o-2024-08-06",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": protocol_text[:15000]},
        ],
        response_format=ProtocolStructure,
        temperature=0.0,
    )
    return completion.choices[0].message.parsed

# --- 5. THE ANALYSIS FUNCTION ---
def analyze_study(text_content, pico_criteria, stage="level_1"):
    if stage == "level_1":
        rules_block = """
        LEVEL 1 (SENSITIVITY) RULES:
        - Bias towards INCLUSION.
        - If abstract is vague/unclear, select 'UNCLEAR' (Keep it).
        - EXCLUDE only if clearly violating criteria.
        """
    else:
        rules_block = """
        LEVEL 2 (SPECIFICITY) RULES:
        - Strict Verification required.
        - If criteria evidence is missing in full text, mark 'UNCLEAR' or 'EXCLUDE'.
        - Violating ANY exclusion criteria = EXCLUDE.
        """

    system_prompt = f"""
    You are a Cochrane Screener.
    
    CRITERIA:
    P: {pico_criteria['P']}
    I: {pico_criteria['I']}
    C: {pico_criteria['C']}
    O: {pico_criteria['O']}
    S: {pico_criteria['S']}
    E: {pico_criteria['E']}
    
    {rules_block}
    """

    max_chars = 50000 if stage == "level_2" else 10000
    
    completion = client.beta.chat.completions.parse(
        model="gpt-4o-2024-08-06",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"STUDY TEXT:\n{text_content[:max_chars]}"},
        ],
        response_format=ScreeningDecision,
        temperature=0.0,
    )
    return completion.choices[0].message.parsed