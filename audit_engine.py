import streamlit as st
import fitz  # PyMuPDF
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
    IncludeMetaAnalysis: bool = Field(description="Does the protocol explicitly allow including Systematic Reviews?")
    StudyDesign: str = Field(description="Required study design.")
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

# --- UPDATED MINER MODELS ---
class CitationItem(BaseModel):
    Title: str = Field(description="Title of the study.")
    AuthorYear: str = Field(description="First author and Year (e.g., 'Smith 2020').")
    # These fields are filled by Python logic later, but AI populates basic info
    Context: str = Field(description="Section found (e.g. 'References').")
    IsRelevant: bool = Field(default=False)
    Confidence: int = Field(default=0)
    Reason: str = Field(default="")

class MiningResponse(BaseModel):
    # LOBE 1: The Researcher's List
    Included_Study_Names: List[str] = Field(description="List of Author/Year keys found STRICTLY in the 'Included Studies' table/chart.")
    # LOBE 2: The Clerk's List
    Full_Bibliography: List[CitationItem] = Field(description="The comprehensive list of ALL citations found in the References section.")

# Helper for the App (keeps app.py compatible)
class CitationList(BaseModel):
    Citations: List[CitationItem]

# --- 3. OPTIMIZED PDF EXTRACTOR ---
def extract_text_from_pdf(uploaded_file, strict_crop=True):
    all_text = ""
    stop_keywords = ["REFERENCES", "References", "BIBLIOGRAPHY", "Bibliography", "LITERATURE CITED"]
    
    try:
        with fitz.open(stream=uploaded_file.read(), filetype="pdf") as doc:
            for page in doc:
                text = page.get_text()
                if strict_crop and any(k in text[:500] for k in stop_keywords):
                    all_text += "\n\n[...References Removed...]"
                    break 
                all_text += text + "\n"
    except Exception as e:
        return f"Error reading PDF: {e}"
    return all_text

# --- 4. EXTRACT PICO ---
def extract_pico_criteria(protocol_text):
    system_prompt = "You are a Methodologist. Extract strict PICO criteria."
    completion = client.beta.chat.completions.parse(
        model="gpt-4o-2024-08-06",
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": protocol_text[:15000]}],
        response_format=ProtocolStructure,
        temperature=0.0,
    )
    return completion.choices[0].message.parsed

# --- 5. ANALYZE STUDY ---
def analyze_study(text_content, pico_criteria, stage="level_1"):
    model_choice = "gpt-4o-mini" if stage == "level_1" else "gpt-4o-2024-08-06"
    max_chars = 15000 if stage == "level_1" else 60000

    system_prompt = f"""
    You are a Cochrane systematic review Screener.
    CRITERIA: P: {pico_criteria['P']}, I: {pico_criteria['I']}, C: {pico_criteria['C']}, O: {pico_criteria['O']}, S: {pico_criteria['S']}, E: {pico_criteria['E']}
    Allow Meta-Analysis? {pico_criteria.get('IncludeMetaAnalysis', False)}
    """

    completion = client.beta.chat.completions.parse(
        model=model_choice,
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"STUDY:\n{text_content[:max_chars]}"}],
        response_format=ScreeningDecision,
        temperature=0.0,
    )
    
    result = completion.choices[0].message.parsed
    if result.Confidence_Score < 85:
        result.ScreeningDecision = "UNCLEAR"
        result.Reasoning_Summary = f"⚠️ [AUTO-FLAGGED] AI Confidence ({result.Confidence_Score}%) is below 85% threshold. Human review required. AI thought: {result.Reasoning_Summary}"
    
    return result

# --- 6. META-MINER (Brain Split Strategy) ---
def mine_citations(text_content, pico_criteria):
    system_prompt = f"""
    You are a Dual-Process Bot. You have two distinct tasks.
    
    TASK 1: THE RESEARCHER (Find the Winners)
    - Scan the document for the "INCLUDED STUDIES" table or list.
    - Extract a simple list of the Author/Year keys for these studies (e.g. "Smith 2020").
    - Ignore everything else.
    
    TASK 2: THE CLERK (Digitize the Pile)
    - Go to the REFERENCES / BIBLIOGRAPHY section.
    - Extract EVERY citation you see (20-50+ items).
    - Do not filter. Do not judge. Just list Author, Year, and Title.
    - Context should be "Bibliography".
    """
    
    # 1. AI DOES THE EXTRACTION
    completion = client.beta.chat.completions.parse(
        model="gpt-4o-mini", # Fast enough for list extraction
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text_content[:120000]} 
        ],
        response_format=MiningResponse,
        temperature=0.0,
    )
    
    raw_data = completion.choices[0].message.parsed
    
    # 2. PYTHON DOES THE MERGING (100% Accuracy)
    # We loop through the Clerk's list (Full Bibliography)
    # If a study matches the Researcher's list (Included Names), we mark it True.
    
    final_list = []
    
    # Normalize included names for easier matching (lowercase)
    inc_names_norm = [n.lower() for n in raw_data.Included_Study_Names]
    
    for ref in raw_data.Full_Bibliography:
        # Check if this reference author/year is inside our "Included" list
        # Simple substring match is usually robust enough for Author/Year
        is_match = any(inc in ref.AuthorYear.lower() for inc in inc_names_norm)
        
        if is_match:
            ref.IsRelevant = True
            ref.Reason = "Explicitly listed in 'Included Studies' section."
            ref.Confidence = 100
            ref.Context = "Included Studies Table"
        else:
            ref.IsRelevant = False
            ref.Reason = "Found in Bibliography only."
            ref.Confidence = 0
            ref.Context = "Reference List"
            
        final_list.append(ref)
        
    return CitationList(Citations=final_list)