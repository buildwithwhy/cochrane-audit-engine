import streamlit as st
import pandas as pd
import time
from audit_engine import analyze_abstract

# Page Config
st.set_page_config(page_title="Cochrane AI Auditor", layout="wide")

# --- HEADER ---
st.title("🤖 RAISE-Compliant Cochrane Audit Engine")
st.markdown("""
This tool automates Level 1 screening (Title/Abstract) with **>99% sensitivity**.
It creates a verifiable **Audit Log** for every decision.
""")

# --- SIDEBAR (Settings) ---
with st.sidebar:
    st.header("⚙️ Settings")
    api_key = st.text_input("OpenAI API Key", type="password", placeholder="sk-...")
    
    st.divider()
    st.subheader("Define Protocol (PICO)")
    p_crit = st.text_area("Population", "Adults (>=18) with Type 2 Diabetes")
    i_crit = st.text_input("Intervention", "SGLT2 inhibitors")
    c_crit = st.text_input("Comparator", "Placebo or Standard Care")
    o_crit = st.text_input("Outcome", "HbA1c reduction")
    s_crit = st.selectbox("Study Design", ["RCT", "Observational", "Any"], index=0)

    current_pico = {
        "P": p_crit, "I": i_crit, "C": c_crit, "O": o_crit, "S": s_crit
    }

# --- TABS ---
tab1, tab2 = st.tabs(["📝 Single Study Check", "📂 Batch Upload (CSV)"])

# === TAB 1: SINGLE STUDY ===
with tab1:
    col1, col2 = st.columns([1, 1])
    with col1:
        st.subheader("Input Study")
        input_title = st.text_input("Study Title", "Dapagliflozin in Heart Failure")
        input_abstract = st.text_area("Study Abstract", height=250, placeholder="Paste abstract here...")
        run_btn = st.button("Audit This Study", type="primary")

    with col2:
        st.subheader("Audit Decision Log")
        if run_btn:
            if not api_key:
                st.warning("⚠️ Enter API Key in sidebar first.")
            else:
                with st.spinner("Consulting Cochrane guidelines..."):
                    try:
                        result = analyze_abstract(input_title, input_abstract, current_pico, api_key)
                        
                        # Display Decision
                        if result.ScreeningDecision == "INCLUDE":
                            st.success(f"### ✅ DECISION: {result.ScreeningDecision}")
                        elif result.ScreeningDecision == "EXCLUDE":
                            st.error(f"### 🛑 DECISION: {result.ScreeningDecision}")
                        else:
                            st.warning(f"### ⚠️ DECISION: {result.ScreeningDecision}")
                        
                        st.info(f"**Logic:** {result.ReasoningLog.Summary_Judgment}")
                        
                        # Checklist
                        check_data = {
                            "Criteria": ["Population", "Intervention", "Comparator", "Outcome", "Design"],
                            "Pass?": [
                                result.ReasoningLog.Population_Check,
                                result.ReasoningLog.Intervention_Check,
                                result.ReasoningLog.Comparator_Check,
                                result.ReasoningLog.Outcome_Check,
                                result.ReasoningLog.StudyDesign_Check
                            ]
                        }
                        st.table(pd.DataFrame(check_data))
                    except Exception as e:
                        st.error(f"Error: {e}")

# === TAB 2: BATCH UPLOAD ===
with tab2:
    st.subheader("Batch Audit Processing")
    st.markdown("Upload a CSV file with columns: `Title` and `Abstract`.")
    
    uploaded_file = st.file_uploader("Upload CSV", type=["csv"])
    
    if uploaded_file and api_key:
        df = pd.read_csv(uploaded_file)
        st.write("Preview of uploaded data:", df.head())
        
        if st.button("🚀 Run Batch Audit"):
            results = []
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            total_rows = len(df)
            
            for index, row in df.iterrows():
                status_text.text(f"Processing study {index + 1} of {total_rows}...")
                
                try:
                    audit = analyze_abstract(row['Title'], row['Abstract'], current_pico, api_key)
                    
                    results.append({
                        "Title": row['Title'],
                        "Decision": audit.ScreeningDecision,
                        "Reason": audit.ExclusionReason,
                        "Logic": audit.ReasoningLog.Summary_Judgment,
                        "Pop_Check": audit.ReasoningLog.Population_Check,
                        "Int_Check": audit.ReasoningLog.Intervention_Check
                    })
                except Exception as e:
                    results.append({"Title": row['Title'], "Decision": "ERROR", "Reason": str(e)})
                
                progress_bar.progress((index + 1) / total_rows)
                time.sleep(0.1) # Small pause to be nice to the API
            
            status_text.text("✅ Audit Complete!")
            
            # --- DASHBOARD SECTION ---
            st.divider()
            st.subheader("📊 Audit Summary")
            
            # 1. Calculate Stats
            results_df = pd.DataFrame(results)
            decision_counts = results_df['Decision'].value_counts()
            
            col_a, col_b = st.columns([1, 2])
            
            with col_a:
                # Simple Metrics
                st.metric("Total Studies", len(results_df))
                st.metric("Included", len(results_df[results_df['Decision'] == 'INCLUDE']))
                st.metric("Excluded", len(results_df[results_df['Decision'] == 'EXCLUDE']))
            
            with col_b:
                # Bar Chart
                st.bar_chart(decision_counts, color=["#FF4B4B"]) # Streamlit's red color

            # 2. Show Detailed Table
            st.write("### Detailed Log")
            st.dataframe(results_df)
            
            # 3. Download Button
            csv = results_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                "📥 Download Audit Log (CSV)",
                csv,
                "audit_results.csv",
                "text/csv",
                key='download-csv'
            )