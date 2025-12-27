import streamlit as st
import pandas as pd
from audit_engine import analyze_study, extract_text_from_pdf, extract_pico_criteria, mine_citations
import database as db

# Initialize Database
db.init_db()

st.set_page_config(page_title="Cochrane AI Auditor", layout="wide")

# --- SESSION STATE INITIALIZATION ---
if 'user' not in st.session_state: st.session_state.user = None
if 'project_id' not in st.session_state: st.session_state.project_id = None
if 'project_name' not in st.session_state: st.session_state.project_name = None

if 'step' not in st.session_state: st.session_state.step = 0
if 'pico' not in st.session_state: st.session_state.pico = {}
if 'workflow_mode' not in st.session_state: st.session_state.workflow_mode = None # "level_1" or "level_2"
if 'temp_pico' not in st.session_state: st.session_state.temp_pico = None
if 'last_audit_id' not in st.session_state: st.session_state.last_audit_id = None

# =========================================================
# LOGIN SCREEN
# =========================================================
if not st.session_state.user:
    col1, col2 = st.columns([1, 2])
    with col1:
        st.title("🔐 Login")
        auth_mode = st.radio("Mode", ["Login", "Register"], horizontal=True)
        
        if auth_mode == "Login":
            with st.form("login_form"):
                username = st.text_input("Username")
                password = st.text_input("Password", type="password")
                if st.form_submit_button("Log In", type="primary"):
                    if db.login_user(username, password):
                        st.session_state.user = username
                        st.rerun()
                    else:
                        st.error("Invalid username or password.")
        else:
            with st.form("register_form"):
                st.subheader("Create New Account")
                new_user = st.text_input("Username")
                new_email = st.text_input("Email Address")
                p1 = st.text_input("Password", type="password")
                p2 = st.text_input("Confirm Password", type="password")
                
                if st.form_submit_button("Create Account", type="primary"):
                    if p1 != p2:
                        st.error("Passwords do not match!")
                    elif not new_email or "@" not in new_email:
                        st.error("Please enter a valid email address.")
                    elif not new_user:
                        st.error("Username required.")
                    else:
                        if db.create_user(new_user, new_email, p1):
                            st.success("Account created! Please switch to 'Login' tab.")
                        else:
                            st.error("Username already exists.")
    st.stop()

# =========================================================
# SIDEBAR NAVIGATION
# =========================================================
with st.sidebar:
    st.write(f"👤 **{st.session_state.user}**")
    if st.button("Logout"):
        st.session_state.user = None; st.rerun()
    st.divider()
    if st.session_state.project_id:
        st.write(f"📂 **{st.session_state.project_name}**")
        if st.session_state.step == 3:
            if st.button("⬅ Change Stage"): st.session_state.step = 2; st.rerun()
        if st.session_state.step >= 2:
            if st.button("✏️ Edit Protocol"): st.session_state.step = 1; st.rerun()
        if st.button("📂 Switch Project"):
            st.session_state.project_id = None; st.session_state.step = 0; st.rerun()
    st.divider()
    
    # Hide Protocol on Dashboard (Step 0)
    if st.session_state.pico and st.session_state.step > 0:
        with st.expander("📖 Active Protocol"): st.write(st.session_state.pico)

# =========================================================
# HELPER FUNCTIONS
# =========================================================
def render_scorecard(row):
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Pop", "✅" if row['P'] else "❌")
    c2.metric("Int", "✅" if row['I'] else "❌")
    c3.metric("Comp", "✅" if row['C'] else "❌")
    c4.metric("Out", "✅" if row['O'] else "❌")
    c5, c6, c7 = st.columns(3)
    c5.metric("Design", "✅" if row['S'] else "❌")
    c6.metric("Excl", "PASS" if not row['E'] else "FAIL")
    conf = row['Confidence']
    color = "normal" if conf > 80 else "off" if conf > 50 else "inverse"
    c7.metric("Conf", f"{conf}%", delta_color=color)

# =========================================================
# STEP 0: PROJECT SELECT
# =========================================================
if st.session_state.step == 0 or st.session_state.project_id is None:
    st.title("🗂️ Project Dashboard")
    t1, t2 = st.tabs(["New Project", "Load Existing"])
    with t1:
        np = st.text_input("Project Name")
        if st.button("Create", type="primary"):
            if np:
                pid = db.create_project(st.session_state.user, np, {})
                st.session_state.project_id = pid; st.session_state.project_name = np
                st.session_state.step = 1; st.rerun()
    with t2:
        projs = db.get_user_projects(st.session_state.user)
        if projs:
            for p in projs:
                c1, c2 = st.columns([3, 1])
                c1.write(f"**{p['name']}**")
                if c2.button("Load", key=f"load_{p['id']}"):
                    st.session_state.project_id = p['id']
                    st.session_state.project_name = p['name']
                    st.session_state.pico = p['pico']
                    st.session_state.step = 1 if not p['pico'] else 2
                    st.rerun()
        else: st.info("No projects.")

# =========================================================
# STEP 1: PROTOCOL
# =========================================================
elif st.session_state.step == 1:
    st.title("🛠️ Step 1: Define Protocol")
    im = st.radio("Input:", ["Paste Text", "Upload File"], horizontal=True)
    pt = ""
    if im == "Paste Text": pt = st.text_area("Paste Protocol", height=150)
    else:
        up = st.file_uploader("Upload", type=['pdf', 'txt'])
        if up: pt = extract_text_from_pdf(up) if up.type=="application/pdf" else str(up.read(),"utf-8")
    
    if st.button("✨ Extract Criteria", type="primary", disabled=not pt):
        with st.spinner("Extracting..."):
            st.session_state.temp_pico = extract_pico_criteria(pt); st.rerun()
    
    defaults = st.session_state.temp_pico if st.session_state.temp_pico else st.session_state.pico
    def g(o, k): return o.get(k, "") if isinstance(o, dict) else getattr(o, k, "") if o else ""
    
    with st.form("protocol_form"):
        c1, c2 = st.columns(2)
        p = c1.text_area("Population", value=g(defaults, "Population") or g(defaults, "P"))
        i = c1.text_area("Intervention", value=g(defaults, "Intervention") or g(defaults, "I"))
        c = c1.text_area("Comparator", value=g(defaults, "Comparator") or g(defaults, "C"))
        o = c2.text_area("Outcome", value=g(defaults, "Outcome") or g(defaults, "O"))
        s = c2.text_input("Study Design", value=g(defaults, "StudyDesign") or g(defaults, "S"))
        e = c2.text_area("Exclusion Criteria", value=g(defaults, "Exclusion") or g(defaults, "E"))
        if st.form_submit_button("✅ Save & Continue"):
            new_p = {"P": p, "I": i, "C": c, "O": o, "S": s, "E": e}
            st.session_state.pico = new_p
            db.update_project_pico(st.session_state.project_id, new_p)
            st.session_state.step = 2; st.rerun()

# =========================================================
# STEP 2: STAGE SELECT
# =========================================================
elif st.session_state.step == 2:
    st.title("🚀 Select Stage")
    c1, c2 = st.columns(2)
    with c1: 
        if st.button("📑 Level 1 (Abstract)"): st.session_state.workflow_mode = "level_1"; st.session_state.step = 3; st.rerun()
    with c2: 
        if st.button("📖 Level 2 (Full Text)"): st.session_state.workflow_mode = "level_2"; st.session_state.step = 3; st.rerun()

# =========================================================
# STEP 3: WORKSPACE
# =========================================================
elif st.session_state.step == 3:
    mode = st.session_state.workflow_mode
    mode_title = "Level 1" if mode == "level_1" else "Level 2"
    current_table = "results_level_1" if mode == "level_1" else "results_level_2"
    
    st.title(f"🔍 Workspace: {mode_title}")
    
    def add_result_to_db(title, text, audit, source):
        data = {
            "Title": title, "Abstract": text, "Decision": audit.ScreeningDecision, 
            "Reason": audit.Reasoning_Summary, "Confidence": audit.Confidence_Score,
            "P": audit.ReasoningLog.Population_Check, "I": audit.ReasoningLog.Intervention_Check,
            "C": audit.ReasoningLog.Comparator_Check, "O": audit.ReasoningLog.Outcome_Check,
            "S": audit.ReasoningLog.StudyDesign_Check, "E": audit.ReasoningLog.Exclusion_Check,
            "P_Reas": audit.ReasoningLog.Population_Reason, "I_Reas": audit.ReasoningLog.Intervention_Reason,
            "C_Reas": audit.ReasoningLog.Comparator_Reason, "O_Reas": audit.ReasoningLog.Outcome_Reason,
            "S_Reas": audit.ReasoningLog.StudyDesign_Reason, "E_Reas": audit.ReasoningLog.Exclusion_Reason,
            "Source": source, "Override_History": ""
        }
        return db.save_result(st.session_state.project_id, data, current_table)

    t1, t2, t3 = st.tabs(["Single Audit", "Batch Upload", f"{mode_title} Dashboard"])

    # --- TAB 1: SINGLE AUDIT (With Meta-Miner Fork) ---
    with t1:
        # 1. THE FORK IN THE ROAD
        task_type = "Standard Screening"
        
        # Only show this option in Level 2!
        if mode == "level_2":
            st.info("🧠 Level 2 Mode")
            task_type = st.radio(
                "What are you screening?", 
                ["Standard Screening (RCT/Study)", "Meta-Analysis Extraction (Mine Citations)"],
                horizontal=True
            )

        c1, c2 = st.columns([1, 1])
        
        with c1:
            # SOURCE INPUT
            src = st.radio("Source", ["Paste", "Upload"], horizontal=True, key="src_single")
            
            if src == "Paste":
                ti = st.text_input("Title"); ab = st.text_area("Text", height=200)
                txt = f"Title: {ti}\nText: {ab}" if ab else ""
                file_name = "Pasted Text"
            else:
                f = st.file_uploader("Upload Document", type=['txt','pdf'], key="up_single")
                if f:
                    file_name = f.name
                    # LOGIC: If mining, read WHOLE file. If screening, CROP refs.
                    is_mining = (task_type == "Meta-Analysis Extraction (Mine Citations)")
                    if f.type == "application/pdf":
                        # strict_crop=False if mining, True if screening
                        txt = extract_text_from_pdf(f, strict_crop=not is_mining)
                    else:
                        txt = str(f.read(),"utf-8")
                else:
                    txt = ""
                    file_name = ""

            # BUTTON LOGIC
            btn_label = "⛏️ Extract Included Studies" if "Extraction" in task_type else "Run Screening Audit"
            
            if st.button(btn_label, type="primary", disabled=not txt):
                
                # --- PATH A: MINING META-ANALYSIS ---
                if "Extraction" in task_type:
                    with st.spinner("Reading Review & Extracting Included Studies..."):
                        citations = mine_citations(txt, st.session_state.pico)
                        
                        st.session_state.last_mining_result = citations
                        if 'last_single_result' in st.session_state: del st.session_state.last_single_result
                        st.success(f"Found {len(citations.Citations)} included studies!")

                # --- PATH B: STANDARD SCREENING ---
                else:
                    with st.spinner("Analyzing Study against Protocol..."):
                        res = analyze_study(txt, st.session_state.pico, stage=mode)
                        nid = add_result_to_db(ti if 'ti' in locals() and ti else file_name, txt, res, "Single")
                        st.session_state.last_audit_id = nid
                        st.session_state.last_single_result = res
                        if 'last_mining_result' in st.session_state: del st.session_state.last_mining_result
                        st.success("Saved!")

        # OUTPUT COLUMN
        with c2:
            # --- SHOW MINING RESULTS (Interactive!) ---
            if "Extraction" in task_type and 'last_mining_result' in st.session_state:
                res = st.session_state.last_mining_result
                
                st.subheader("⛏️ Extracted Studies")
                st.caption("Review the list below. Uncheck any you don't want to keep.")
                
                if 'mining_df' not in st.session_state or st.session_state.get('last_mining_source') != file_name:
                    data = [
                        {
                            "Keep": True, 
                            "Author": c.AuthorYear, 
                            "Title": c.Title, 
                            "Context from Review": c.Context 
                        } 
                        for c in res.Citations
                    ]
                    st.session_state.mining_df = pd.DataFrame(data)
                    st.session_state.last_mining_source = file_name

                edited_df = st.data_editor(
                    st.session_state.mining_df,
                    column_config={
                        "Keep": st.column_config.CheckboxColumn("Export?", default=True),
                        "Context from Review": st.column_config.TextColumn("Context (Verify Here)", width="medium"),
                    },
                    hide_index=True,
                    use_container_width=True,
                    key="editor_mining"
                )
                
                st.markdown("---")
                selected_studies = edited_df[edited_df["Keep"] == True]
                
                if not selected_studies.empty:
                    st.write(f"**{len(selected_studies)} studies selected.**")
                    csv = selected_studies.drop(columns=["Keep"]).to_csv(index=False).encode('utf-8')
                    st.download_button(
                        "📥 Download Selected for Screening", 
                        csv, 
                        "selected_rcts.csv", 
                        "text/csv",
                        type="primary"
                    )
                else:
                    st.warning("No studies selected.")

            # --- SHOW STANDARD SCREENING RESULTS ---
            elif 'last_single_result' in st.session_state and "Extraction" not in task_type:
                res = st.session_state.last_single_result
                st.subheader(f"Decision: {res.ScreeningDecision}")
                
                render_scorecard({
                    'P': res.ReasoningLog.Population_Check, 'I': res.ReasoningLog.Intervention_Check,
                    'C': res.ReasoningLog.Comparator_Check, 'O': res.ReasoningLog.Outcome_Check,
                    'S': res.ReasoningLog.StudyDesign_Check, 'E': res.ReasoningLog.Exclusion_Check,
                    'Confidence': res.Confidence_Score
                })

                b1, b2 = st.columns(2)
                if b1.button("Override to INCLUDE", key="s_inc"):
                    db.update_result_decision(st.session_state.last_audit_id, "INCLUDE", "Single Override", current_table)
                    res.ScreeningDecision = "INCLUDE"; st.rerun()
                if b2.button("Override to EXCLUDE", key="s_exc"):
                    db.update_result_decision(st.session_state.last_audit_id, "EXCLUDE", "Single Override", current_table)
                    res.ScreeningDecision = "EXCLUDE"; st.rerun()
                
                st.markdown("#### Detailed Reasons")
                with st.container(border=True):
                    rl = res.ReasoningLog
                    if rl.Population_Reason: st.write(f"**P:** {rl.Population_Reason}")
                    if rl.Intervention_Reason: st.write(f"**I:** {rl.Intervention_Reason}")
                    if rl.Comparator_Reason: st.write(f"**C:** {rl.Comparator_Reason}")
                    if rl.Outcome_Reason: st.write(f"**O:** {rl.Outcome_Reason}")
                    if rl.Exclusion_Reason: st.write(f"**E:** {rl.Exclusion_Reason}")

    # --- TAB 2: BATCH ---
    with t2:
        if mode == "level_1":
            bf = st.file_uploader("Upload CSV", type=["csv"])
            if bf and st.button("Run Batch"):
                df = pd.read_csv(bf)
                bar = st.progress(0)
                for i, row in df.iterrows():
                    tx = f"Title: {row.get('Title','')}\nAbstract: {row.get('Abstract','')}"
                    rs = analyze_study(tx, st.session_state.pico, stage="level_1")
                    add_result_to_db(row.get('Title'), row.get('Abstract'), rs, "Batch CSV")
                    bar.progress((i+1)/len(df))
                st.success("Done!")
        else:
            bfs = st.file_uploader("Upload PDFs", type=["pdf"], accept_multiple_files=True)
            if bfs and st.button("Run Batch"):
                bar = st.progress(0)
                for i, f in enumerate(bfs):
                    # For batch, we assume standard screening (cropping enabled)
                    tx = extract_text_from_pdf(f, strict_crop=True)
                    rs = analyze_study(tx, st.session_state.pico, stage="level_2")
                    add_result_to_db(f.name, tx, rs, "Batch PDF")
                    bar.progress((i+1)/len(bfs))
                st.success("Done!")

    # --- TAB 3: DASHBOARD (Stage Specific) ---
    with t3:
        results = db.get_project_results(st.session_state.project_id, current_table)
        df = pd.DataFrame(results)
        
        if df.empty:
            st.info(f"No {mode_title} results yet.")
        else:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Total Studies", len(df))
            m2.metric("Include", len(df[df['Decision'] == 'INCLUDE']))
            m3.metric("Exclude", len(df[df['Decision'] == 'EXCLUDE']))
            m4.metric("Unclear", len(df[df['Decision'] == 'UNCLEAR']))
            st.divider()
            
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(f"📥 Download {mode_title} Results (CSV)", csv, f"results_{mode}.csv", "text/csv")
            
            c_list, c_view = st.columns([1, 2])
            with c_list:
                st.subheader("Filters")
                dec_filter = st.selectbox("Decision:", ["All", "INCLUDE", "EXCLUDE", "UNCLEAR"])
                ov_filter = st.radio("Override Status:", ["All", "Overridden Only"], horizontal=True)
                conf_filter = st.slider("Show Confidence Below %", 0, 100, 100)
                
                vdf = df.copy()
                if dec_filter != "All": vdf = vdf[vdf['Decision'] == dec_filter]
                if ov_filter == "Overridden Only": vdf = vdf[vdf['Override_History'] != ""]
                vdf = vdf[vdf['Confidence'] <= conf_filter]
                
                st.caption(f"Showing {len(vdf)} records")
                sel_id = None
                if not vdf.empty:
                    sel_id = st.radio("Select:", vdf['ID'], format_func=lambda x: f"#{x} {vdf[vdf.ID==x]['Title'].iloc[0][:20]}...")
            
            with c_view:
                if sel_id:
                    row = df[df.ID == sel_id].iloc[0]
                    st.markdown(f"### {row['Title']}")
                    st.caption(f"Source: {row['Source']}")
                    
                    render_scorecard(row)
                    st.info(f"**{row['Decision']}**: {row['Reason']}")
                    if row['Override_History']: st.warning(f"📝 {row['Override_History']}")
                    
                    b1, b2 = st.columns(2)
                    if b1.button("Override to INCLUDE", key="d_inc"):
                        db.update_result_decision(int(row['ID']), "INCLUDE", "Dash Override", current_table)
                        st.rerun()
                    if b2.button("Override to EXCLUDE", key="d_exc"):
                        db.update_result_decision(int(row['ID']), "EXCLUDE", "Dash Override", current_table)
                        st.rerun()

                    st.markdown("#### Detailed Reasons")
                    with st.container(border=True):
                        if row['P_Reas']: st.write(f"**P:** {row['P_Reas']}")
                        if row['I_Reas']: st.write(f"**I:** {row['I_Reas']}")
                        if row['C_Reas']: st.write(f"**C:** {row['C_Reas']}")
                        if row['O_Reas']: st.write(f"**O:** {row['O_Reas']}")
                        if row['E_Reas']: st.write(f"**E:** {row['E_Reas']}")