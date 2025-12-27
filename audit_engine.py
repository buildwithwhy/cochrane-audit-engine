import streamlit as st
import pdfplumber
from openai import OpenAI
from pydantic import BaseModel, Field
from typing import Literal, List

# --- 1. CONNECT ---
try:
    client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
except Exception:
    st.error("🚨 OpenAI API Key missing!")
    st.stop()

# --- 2. DATA STRUCTURES ---
class ProtocolStructure(BaseModel):
    Population: str = Field(description="The specific population defined.")
    Intervention: str = Field(description="The intervention being studied.")
    Comparator: str = Field(description="The comparator/control.")
    Outcome: str = Field(description="Primary outcomes.")
    # NEW: Specific check for Meta-Analysis allowance
    IncludeMetaAnalysis: bool = Field(description="Does the protocol explicitly allow including Systematic Reviews or Meta-Analyses?")
    StudyDesign: str = Field(description="Required study design (e.g. RCT, Cohort).")
    Exclusion: str = Field(description="Exclusion criteria.")

class ReasoningLog(BaseModel):
    Population_Check: bool = Field(description="Strictly meets Population criteria?")
    Population_Reason: str = Field(description="Reason for P check.")
    Intervention_Check: bool = Field(description="Strictly meets Intervention criteria?")
    Intervention_Reason: str = Field(description="Reason for I check.")
    Comparator_Check: bool = Field(description="Strictly meets Comparator criteria?")
    Comparator_Reason: str = Field(description="Reason for C check.")
    Outcome_Check: bool = Field(description="Strictly meets Outcome criteria?")
    Outcome_Reason: str = Field(description="Reason for O check.")
    StudyDesign_Check: bool = Field(description="Strictly meets Study Design criteria?")
    StudyDesign_Reason: str = Field(description="Reason for S check.")
    Exclusion_Check: bool = Field(description="Violates Exclusion Criteria? (True = Exclude)")
    Exclusion_Reason: str = Field(description="Which rule was violated?")

class ScreeningDecision(BaseModel):
    ScreeningDecision: Literal["INCLUDE", "EXCLUDE", "UNCLEAR"]
    Confidence_Score: int
    Reasoning_Summary: str
    ReasoningLog: ReasoningLog

# META-MINER STRUCTURE
class CitationItem(BaseModel):
    Title: str = Field(description="Title of the included RCT/study.")
    AuthorYear: str = Field(description="First author and Year (e.g., 'Smith 2020').")
    Relevance: str = Field(description="Why this was included (e.g. 'Source: Figure 1 - Included Studies').")

class CitationList(BaseModel):
    Citations: List[CitationItem]

# --- 3. OPTIMIZED PDF EXTRACTOR ---
def extract_text_from_pdf(uploaded_file, strict_crop=True):
    """
    strict_crop=True -> Stops at References (Save money)
    strict_crop=False -> Reads everything (Needed for Citation Mining!)
    """
    all_text = ""
    stop_keywords = ["REFERENCES", "References", "BIBLIOGRAPHY", "Bibliography", "LITERATURE CITED"]
    
    try:
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if not text: continue
                
                # Only crop if we are doing standard screening
                if strict_crop and any(k in text[:200] for k in stop_keywords):
                    all_text += "\n\n[...References Removed for Cost Optimization...]"
                    break 
                
                all_text += text + "\n"
    except Exception as e:
        return f"Error reading PDF: {e}"
    return all_text

# --- 4. EXTRACT PICO (Updated) ---
def extract_pico_criteria(protocol_text):
    system_prompt = "You are a Methodologist. Extract strict PICO criteria. specificially check if Meta-Analyses/Reviews are allowed."
    completion = client.beta.chat.completions.parse(
        model="gpt-4o-2024-08-06",
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": protocol_text[:15000]}],
        response_format=ProtocolStructure,
        temperature=0.0,
    )
    return completion.choices[0].message.parsed

# --- 5. ANALYZE STUDY ---
def analyze_study(text_content, pico_criteria, stage="level_1"):
    if stage == "level_1":
        model_choice = "gpt-4o-mini"
        max_chars = 15000 
        rules = "LEVEL 1 RULES: Bias towards INCLUSION. If unclear, keep it."
    else:
        model_choice = "gpt-4o-2024-08-06"
        max_chars = 60000
        rules = "LEVEL 2 RULES: Strict Verification. Missing evidence = EXCLUDE."

    system_prompt = f"""
    You are a Cochrane Screener.
    CRITERIA: 
    P: {pico_criteria['P']}
    I: {pico_criteria['I']}
    C: {pico_criteria['C']}
    O: {pico_criteria['O']}
    S: {pico_criteria['S']}
    E: {pico_criteria['E']}
    Allow Meta-Analysis? {pico_criteria.get('IncludeMetaAnalysis', False)}
    
    {rules}
    """

    completion = client.beta.chat.completions.parse(
        model=model_choice,
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"STUDY:\n{text_content[:max_chars]}"}],
        response_format=ScreeningDecision,
        temperature=0.0,
    )
    return completion.choices[0].message.parsed

# --- MINING STRUCTURE ---
class CitationItem(BaseModel):
    Title: str = Field(description="Title of the included RCT/study.")
    AuthorYear: str = Field(description="First author and Year (e.g., 'Smith 2020').")
    # NEW: Captures what the text actually said about this study
    Context: str = Field(description="Short summary of what the review says about this study (e.g. 'Listed in Table 1', 'High risk of bias', 'Contributed data for Outcome A').")

class CitationList(BaseModel):
    Citations: List[CitationItem]


# --- 6. META-MINER  ---
def mine_citations(text_content, pico_criteria):
    """
    Extracts INCLUDED studies + Context from a meta-analysis.
    """
    system_prompt = f"""
    You are a Research Assistant helping 'explode' a Meta-Analysis.
    
    CONTEXT:
    The user is screening for this topic: {pico_criteria['I']} vs {pico_criteria['C']} in {pico_criteria['P']}.
    This document is a Systematic Review / Meta-Analysis.
    
    TASK:
    1. Find the list of PRIMARY STUDIES that this review INCLUDED.
    2. Extract the Author/Year and Title.
    3. CRITICAL: Extract the 'Context'—what does the review say about this study? 
       - Is it listed in a 'Characteristics of Included Studies' table? (Summarize key traits)
       - Is it discussed in the text? (e.g. "Smith 2020 had high bias risk")
       - If it is just listed in a bibliography, state "Listed in References".
    
    Ignore studies explicitly listed as "Excluded".
    """
    
    completion = client.beta.chat.completions.parse(
        model="gpt-4o-2024-08-06",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text_content[:80000]} 
        ],
        response_format=CitationList,
        temperature=0.0,
    )
    return completion.choices[0].message.parsed