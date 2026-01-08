import streamlit as st
import pandas as pd
from streamlit_pdf_viewer import pdf_viewer
from audit_engine import analyze_study, extract_text_from_pdf, extract_pico_criteria, mine_citations
import database as db
import concurrent.futures

# Initialize Database
db.init_db()

st.set_page_config(page_title="AI Evidence Synthesis", layout="wide", page_icon="🩺")

# --- CUSTOM CSS (PRESERVED) ---
st.markdown("""
<style>
    .decision-box { padding: 15px; border-radius: 8px; text-align: center; font-size: 1.5em; font-weight: 800; margin-bottom: 10px; color: white; }
    .dec-include { background-color: #28a745; border: 2px solid #1e7e34; }
    .dec-exclude { background-color: #dc3545; border: 2px solid #bd2130; }
    .dec-unclear { background-color: #ffc107; color: #333; border: 2px solid #d39e00; }
    .override-box { background-color: #fff3cd; color: #856404; padding: 8px; border: 1px solid #ffeeba; border-radius: 5px; text-align: center; font-weight: bold; margin-bottom: 10px; font-size: 0.9em; }
    .metric-badge { display: inline-block; padding: 4px 12px; border-radius: 15px; font-size: 0.85em; font-weight: 600; margin-right: 5px; margin-bottom: 5px; }
    .badge-success { background-color: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
    .badge-danger { background-color: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
</style>
""", unsafe_allow_html=True)

# --- SESSION STATE ---
if 'user' not in st.session_state: st.session_state.user = None
if 'project_id' not in st.session_state: st.session_state.project_id = None
if 'project_name' not in st.session_state: st.session_state.project_name = None
if 'step' not in st.session_state: st.session_state.step = 0
if 'pico' not in st.session_state: st.session_state.pico = {}
if 'workflow_mode' not in st.session_state: st.session_state.workflow_mode = None
if 'temp_pico' not in st.session_state: st.session_state.temp_pico = None
if 'last_audit_id' not in st.session_state: st.session_state.last_audit_id = None
if 'miner_selections' not in st.session_state: st.session_state.miner_selections = {}

# =========================================================
# HELPER: PDF DISPLAY
# =========================================================
def display_pdf(uploaded_file, height=900):
    try:
        uploaded_file.seek(0)
        bytes_data = uploaded_file.getvalue()
        pdf_viewer(input=bytes_data, width=None, height=height, render_text=True)
        uploaded_file.seek(0)
    except Exception as e:
        st.error(f"Error displaying PDF: {e}")

# =========================================================
# HELPER: SCORECARD (PRESERVED)
# =========================================================
def render_full_result_view(row):
    decision = row.get('Decision', 'UNCLEAR')
    override = row.get('Override_History', None)
    
    css_class = "dec-include" if decision == "INCLUDE" else "dec-exclude" if decision == "EXCLUDE" else "dec-unclear"
    icon = "✅" if decision == "INCLUDE" else "⛔" if decision == "EXCLUDE" else "🤔"
    
    st.markdown(f'<div class="decision-box {css_class}">{icon} {decision}</div>', unsafe_allow_html=True)
    
    if override:
        st.markdown(f'<div class="override-box">⚠️ Manually Overridden to {decision}</div>', unsafe_allow_html=True)

    def badge(label, is_pass):
        # Handle cases where data might be missing/None
        is_pass = bool(is_pass) 
        color = "badge-success" if is_pass else "badge-danger"
        icon = "✔" if is_pass else "✖"
        return f'<span class="metric-badge {color}">{icon} {label}</span>'
    
    html = f"""
    <div style="margin-bottom: 10px;">
        {badge("Population", row.get('P'))}
        {badge("Intervention", row.get('I'))}
        {badge("Comparator", row.get('C'))}
        {badge("Outcome", row.get('O'))}
        {badge("Study Design", row.get('S'))}
        {badge("Excl. Criteria", not row.get('E'))}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)
    
    conf = row.get('Confidence', 0)
    st.caption(f"**AI Confidence:** {conf}%")
    st.progress(conf / 100)

# =========================================================
# LOGIN / LANDING SCREEN (PRESERVED)
# =========================================================
if not st.session_state.user:
    l_col, c_col, r_col = st.columns([1, 2, 1])
    
    with c_col:
        st.markdown("""
            <div style='text-align: center; margin-top: 50px; margin-bottom: 30px;'>
                <h1 style='font-size: 3rem; margin-bottom: 10px;'>🩺 AI Evidence Synthesis</h1>
                <h3 style='font-weight: 300; color: #555;'>Explainable and Auditable AI-assisted Evidence Synthesis</h3>
                <hr style='margin: 20px 0;'>
                <p style='font-size: 1.1rem; color: #666;'>
                    Accelerate your systematic reviews with intelligent screening, 
                    meta-analysis mining, and fully auditable decision support.
                </p>
            </div>
        """, unsafe_allow_html=True)

        with st.container(border=True):
            auth_mode = st.radio("Access Mode", ["Login", "Register"], horizontal=True, label_visibility="collapsed")
            
            if auth_mode == "Login":
                st.markdown("### 🔐 Sign In")
                with st.form("login_form"):
                    username = st.text_input("Username")
                    password = st.text_input("Password", type="password")
                    
                    st.markdown("") 
                    if st.form_submit_button("Log In to Dashboard", type="primary", use_container_width=True):
                        if db.login_user(username, password):
                            st.session_state.user = username
                            st.rerun()
                        else:
                            st.error("Invalid username or password.")
            else:
                st.markdown("### 📝 Create Account")
                with st.form("register_form"):
                    c1, c2 = st.columns(2)
                    new_user = c1.text_input("Username")
                    new_email = c2.text_input("Email Address")
                    p1 = st.text_input("Password", type="password")
                    p2 = st.text_input("Confirm Password", type="password")
                    
                    st.markdown("") 
                    if st.form_submit_button("Create Free Account", type="primary", use_container_width=True):
                        if p1 != p2:
                            st.error("Passwords do not match!")
                        elif not new_user:
                            st.error("Username required.")
                        else:
                            if db.create_user(new_user, new_email, p1):
                                st.success("Account created! Please switch to 'Login' tab.")
                            else:
                                st.error("Username already exists.")

    st.stop()

# =========================================================
# SIDEBAR
# =========================================================
with st.sidebar:
    st.markdown(f"### 👤 {st.session_state.user}")
    if st.button("Logout", use_container_width=True): st.session_state.user = None; st.rerun()
    st.divider()
    if st.session_state.project_id:
        st.info(f"📂 **{st.session_state.project_name}**")
        if st.session_state.step > 0:
            if st.button("⬅ Project Dashboard", use_container_width=True): st.session_state.step = 2; st.rerun()
        if st.button("📂 Switch Project", use_container_width=True): st.session_state.project_id = None; st.session_state.step = 0; st.rerun()
    
    if st.session_state.pico and st.session_state.step > 0:
        with st.expander("📖 Active Protocol"): st.write(st.session_state.pico)

# =========================================================
# STEP 0: PROJECT DASHBOARD
# =========================================================
if st.session_state.step == 0 or st.session_state.project_id is None:
    st.title("🗂️ Project Library")
    t1, t2 = st.tabs(["📂 Your Projects", "➕ New Project"])
    
    with t1:
        projs = db.get_user_projects(st.session_state.user)
        if projs:
            for p in projs:
                with st.container(border=True):
                    c1, c2, c3 = st.columns([3, 1, 1])
                    with c1: st.subheader(p['name'])
                    with c2: st.caption("Active") 
                    with c3:
                        if st.button("Open", key=f"load_{p['id']}", type="primary", use_container_width=True):
                            st.session_state.project_id = p['id']
                            st.session_state.project_name = p['name']
                            st.session_state.pico = p['pico']
                            st.session_state.step = 1 if not p['pico'] else 2
                            st.rerun()
        else: st.info("No projects yet.")

    with t2:
        with st.form("new_proj"):
            np = st.text_input("Project Name")
            if st.form_submit_button("Create Project", type="primary"):
                if np:
                    pid = db.create_project(st.session_state.user, np, {})
                    st.session_state.project_id = pid; st.session_state.project_name = np; st.session_state.step = 1; st.rerun()

# =========================================================
# STEP 1: PROTOCOL
# =========================================================
elif st.session_state.step == 1:
    st.title("🛠️ Step 1: Protocol Configuration")
    c1, c2 = st.columns([1, 1])
    with c1:
        with st.expander("📂 Import from File", expanded=True):
            im = st.radio("Method:", ["Paste Text", "Upload File"], horizontal=True)
            pt = ""
            if im == "Paste Text": pt = st.text_area("Paste Protocol Text", height=200)
            else:
                up = st.file_uploader("Upload Protocol", type=['pdf', 'txt'])
                if up: pt = extract_text_from_pdf(up) if up.type=="application/pdf" else str(up.read(),"utf-8")
            
            if st.button("✨ Auto-Extract Criteria", type="primary", disabled=not pt, use_container_width=True):
                with st.spinner("Analyzing..."): st.session_state.temp_pico = extract_pico_criteria(pt); st.rerun()

    with c2:
        defaults = st.session_state.temp_pico if st.session_state.temp_pico else st.session_state.pico
        def g(o, k): return o.get(k, "") if isinstance(o, dict) else getattr(o, k, "") if o else ""
        with st.form("protocol_form"):
            st.subheader("Edit Criteria")
            p = st.text_area("Population", value=g(defaults, "Population") or g(defaults, "P"))
            i = st.text_area("Intervention", value=g(defaults, "Intervention") or g(defaults, "I"))
            c = st.text_area("Comparator", value=g(defaults, "Comparator") or g(defaults, "C"))
            o = st.text_area("Outcome", value=g(defaults, "Outcome") or g(defaults, "O"))
            s = st.text_input("Study Design", value=g(defaults, "StudyDesign") or g(defaults, "S"))
            e = st.text_area("Exclusion", value=g(defaults, "Exclusion") or g(defaults, "E"))
            if st.form_submit_button("✅ Save & Continue", type="primary", use_container_width=True):
                new_p = {"P": p, "I": i, "C": c, "O": o, "S": s, "E": e}
                st.session_state.pico = new_p
                db.update_project_pico(st.session_state.project_id, new_p)
                st.session_state.step = 2; st.rerun()

# =========================================================
# STEP 2: STAGE SELECT
# =========================================================
elif st.session_state.step == 2:
    st.markdown(f"# Welcome to {st.session_state.project_name} 🩺")
    l1_count = len(db.get_project_results(st.session_state.project_id, "results_level_1"))
    l2_count = len(db.get_project_results(st.session_state.project_id, "results_level_2"))
    
    c1, c2 = st.columns(2)
    with c1:
        with st.container(border=True):
            st.markdown("### 📑 Level 1: Abstract Screening")
            st.metric("Studies Processed", l1_count)
            if st.button("Enter Level 1", type="primary", use_container_width=True):
                st.session_state.workflow_mode = "level_1"; st.session_state.step = 3; st.rerun()
    with c2:
        with st.container(border=True):
            st.markdown("### 📖 Level 2: Full Text Review")
            st.metric("Studies Processed", l2_count)
            if st.button("Enter Level 2", type="primary", use_container_width=True):
                st.session_state.workflow_mode = "level_2"; st.session_state.step = 3; st.rerun()

# =========================================================
# STEP 3: WORKSPACE
# =========================================================
elif st.session_state.step == 3:
    mode = st.session_state.workflow_mode
    mode_title = "Level 1" if mode == "level_1" else "Level 2"
    current_table = "results_level_1" if mode == "level_1" else "results_level_2"
    
    c_head_1, c_head_2 = st.columns([3, 1])
    with c_head_1: st.title(f"{mode_title} Workspace")
    with c_head_2: st.caption(f"Project: {st.session_state.project_name}")
    
    def add_result_to_db(title, text, audit, source):
        # DUPLICATE CHECKER
        existing = db.get_project_results(st.session_state.project_id, current_table)
        if any(r['Title'] == title for r in existing):
            return "DUPLICATE"

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

# --- FIX: ROBUST BATCH PROCESSOR ---
    def process_one_batch_item(item, is_pdf, pico_data, stage_mode):
        import io 
        try:
            if is_pdf:
                # Unpack the tuple (filename, bytes) we send from the main loop
                fname, fbytes = item
                # Create a fake file object for PyMuPDF
                fake_file = io.BytesIO(fbytes)
                text = extract_text_from_pdf(fake_file, strict_crop=True)
                name = fname
            else:
                # SAFE COLUMN MAPPING for CSV
                title_key = next((k for k in item.index if k.lower() in ['title', 'study title', 'name']), None)
                abstract_key = next((k for k in item.index if k.lower() in ['abstract', 'summary', 'text', 'description']), None)
                
                if not title_key: title_key = item.index[0] 
                if not abstract_key: abstract_key = item.index[1] if len(item.index) > 1 else title_key
                
                name = str(item[title_key])
                text = f"{name}\n{str(item[abstract_key])}"
                
            res = analyze_study(text, pico_data, stage=stage_mode)
            return name, text, res
        except Exception as e:
            # Return the error so we can see it in the UI
            return "Error", f"Failed: {str(e)}", None

    tabs_list = ["Screening", "Audit Records", "Dashboard"]
    if mode == "level_2": tabs_list.insert(1, "Meta-Miner")
    tabs = st.tabs(tabs_list)
    
    # --- TAB 1: SCREENING ---
    with tabs[0]:
        st1, st2 = st.tabs(["Single Audit", "Batch"])
        with st1:
            c1, c2 = st.columns([1.5, 1]) 
            with c1:
                f_to_display = None
                with st.expander("📂 Upload Document", expanded=True):
                    src = st.radio("Source", ["Upload PDF/Text", "Paste Text"], horizontal=True, label_visibility="collapsed")
                    if src == "Paste Text":
                        ti = st.text_input("Title"); ab = st.text_area("Content", height=400)
                        txt = f"Title: {ti}\nText: {ab}" if ab else ""
                        file_name = "Pasted Text"
                    else:
                        f = st.file_uploader("Choose File", type=['txt','pdf'], label_visibility="collapsed")
                        if f:
                            file_name = f.name
                            if f.type == "application/pdf": f_to_display = f
                            f.seek(0)
                            txt = extract_text_from_pdf(f, strict_crop=True) if f.type=="application/pdf" else str(f.read(),"utf-8")
                        else: txt = ""; file_name = ""

                if f_to_display: display_pdf(f_to_display)
            
            with c2:
                st.subheader("🤖 AI Analysis")
                if st.button("Run Screening", type="primary", use_container_width=True, disabled=not txt):
                    with st.spinner("Analyzing..."):
                        res = analyze_study(txt, st.session_state.pico, stage=mode)
                        nid = add_result_to_db(ti if 'ti' in locals() and ti else file_name, txt, res, "Single")
                        
                        if nid == "DUPLICATE":
                            st.warning("⚠️ Study with this title already exists in the database.")
                        else:
                            st.session_state.last_audit_id = nid
                            st.session_state.last_single_result = res
                
                if 'last_single_result' in st.session_state:
                    res = st.session_state.last_single_result
                    st.divider()
                    render_full_result_view({
                        'Decision': res.ScreeningDecision,
                        'Override_History': "",
                        'P': res.ReasoningLog.Population_Check, 'I': res.ReasoningLog.Intervention_Check,
                        'C': res.ReasoningLog.Comparator_Check, 'O': res.ReasoningLog.Outcome_Check,
                        'S': res.ReasoningLog.StudyDesign_Check, 'E': res.ReasoningLog.Exclusion_Check,
                        'Confidence': res.Confidence_Score
                    })
                    with st.expander("Reasoning Summary", expanded=True):
                        st.write(res.Reasoning_Summary)
                    
                    st.markdown("#### 🛠 Manual Override")
                    b1, b2 = st.columns(2)
                    if b1.button("Override -> INCLUDE", use_container_width=True, key="sing_ov_inc"):
                         db.update_result_decision(st.session_state.last_audit_id, "INCLUDE", "Manual Override", current_table)
                         st.session_state.last_single_result.ScreeningDecision = "INCLUDE"
                         st.rerun()
                    if b2.button("Override -> EXCLUDE", use_container_width=True, key="sing_ov_exc"):
                         db.update_result_decision(st.session_state.last_audit_id, "EXCLUDE", "Manual Override", current_table)
                         st.session_state.last_single_result.ScreeningDecision = "EXCLUDE"
                         st.rerun()

        with st2:
            st.info("⚡ Parallel Batch Processing (5x Speed)")
            if mode == "level_1":
                bf = st.file_uploader("Upload CSV", type=["csv"])
                if bf and st.button("Run Batch"):
                    df_upload = pd.read_csv(bf)
                    bar = st.progress(0)
                    rows = [r for _, r in df_upload.iterrows()]; total = len(rows)
                    
                    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                        pico = st.session_state.pico; stg = mode
                        futures = [executor.submit(process_one_batch_item, r, False, pico, stg) for r in rows]
                        for i, f in enumerate(concurrent.futures.as_completed(futures)):
                            name, text, res = f.result()
                            if res: # Only add if valid result
                                add_result_to_db(name, text, res, "Batch CSV")
                            bar.progress((i + 1) / total)
                    st.success("Done!")
            else:
                bfs = st.file_uploader("Upload PDFs", type=["pdf"], accept_multiple_files=True)
                if bfs and st.button("Run Batch"):
                    # 1. PRE-READ FILES
                    pdf_data = [(f.name, f.read()) for f in bfs]
                    
                    bar = st.progress(0)
                    total = len(pdf_data)
                    success_count = 0
                    
                    # 2. SMART WORKER ALLOCATION
                    # If Level 2 (Full Text), use 1 worker to save tokens. 
                    # If Level 1 (Abstracts), use 4 workers for speed.
                    workers = 1 if mode == "level_2" else 4
                    st.toast(f"Processing with {workers} concurrent worker(s)...")

                    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                        pico = st.session_state.pico; stg = mode
                        futures = [executor.submit(process_one_batch_item, p_data, True, pico, stg) for p_data in pdf_data]
                        
                        for i, f in enumerate(concurrent.futures.as_completed(futures)):
                            name, text, res = f.result()
                            if res:
                                add_result_to_db(name, text, res, "Batch PDF")
                                success_count += 1
                            else:
                                st.error(f"⚠️ Failed: {name}")
                            bar.progress((i + 1) / total)
                            
                    st.success(f"Batch Complete! Processed {success_count}/{total}.")

    # --- TAB 2: META-MINER ---
    if mode == "level_2":
        with tabs[1]:
            st.subheader("⛏️ Meta-Miner")
            c1, c2 = st.columns([1.5, 1])
            with c1:
                with st.expander("📂 Upload Systematic Review", expanded=True):
                    mf = st.file_uploader("Review PDF", type=["pdf"], label_visibility="collapsed")
                if mf: display_pdf(mf, height=800)
            
            with c2:
                if mf and st.button("Extract Citations", type="primary", use_container_width=True):
                    with st.spinner("Mining..."):
                        mf.seek(0)
                        txt = extract_text_from_pdf(mf, strict_crop=False)
                        citations = mine_citations(txt, st.session_state.pico)
                        st.session_state.last_mining_result = citations
                        st.session_state.miner_selections = {i: c.IsRelevant for i, c in enumerate(citations.Citations)}
                
                if 'last_mining_result' in st.session_state:
                    res = st.session_state.last_mining_result
                    curr_name = mf.name if mf else "Unknown"
                    st.markdown("#### Found Studies")
                    st.caption("Select studies to import. Scroll to see all candidates.")
                    
                    with st.container(height=650):
                        with st.container(border=True):
                            meta_sel = st.checkbox(f"**SOURCE REVIEW:** {curr_name}", key="sel_meta")
                            st.caption("The Systematic Review file itself.")

                        for i, c in enumerate(res.Citations):
                            is_checked = st.session_state.miner_selections.get(i, False)
                            with st.container(border=True):
                                col_chk, col_txt = st.columns([0.1, 0.9])
                                with col_chk:
                                    new_val = st.checkbox("", value=is_checked, key=f"miner_chk_{i}")
                                    st.session_state.miner_selections[i] = new_val
                                with col_txt:
                                    st.markdown(f"**{c.AuthorYear}** - {c.Title}")
                                    st.caption(f"Confidence: {c.Confidence}% | {c.Context}")
                                    with st.expander("View Reason"):
                                        st.write(c.Reason)
                    
                    st.divider()
                    if st.button("Add to Level 2 Screen Results", type="primary", use_container_width=True):
                        added_count = 0
                        # Check dupes manually for this block
                        existing = db.get_project_results(st.session_state.project_id, current_table)
                        existing_titles = [r['Title'] for r in existing]

                        if st.session_state.get("sel_meta", False):
                             if curr_name not in existing_titles:
                                 data = {"Title": curr_name, "Abstract": "Systematic Review Source File", "Decision": "INCLUDE", "Reason": "Mined Source", "Confidence": 100, "P":True,"I":True,"C":True,"O":True,"S":True,"E":False,"P_Reas":"","I_Reas":"","C_Reas":"","O_Reas":"","S_Reas":"","E_Reas":"","Source": f"Mined Source", "Override_History": ""}
                                 db.save_result(st.session_state.project_id, data, current_table)
                                 added_count += 1
                        
                        for i, c in enumerate(res.Citations):
                            if st.session_state.miner_selections.get(i, False):
                                if c.Title not in existing_titles:
                                    data = {
                                        "Title": c.Title, 
                                        "Abstract": f"AUTHOR: {c.AuthorYear}\nCONTEXT: {c.Context}\nREASON: {c.Reason}", 
                                        "Decision": "INCLUDE", 
                                        "Reason": c.Reason, 
                                        "Confidence": c.Confidence, 
                                        "P":True,"I":True,"C":True,"O":True,"S":True,"E":False,
                                        "P_Reas":"","I_Reas":"","C_Reas":"","O_Reas":"","S_Reas":"","E_Reas":"",
                                        "Source": f"Mined: {curr_name}", 
                                        "Override_History": ""
                                    }
                                    db.save_result(st.session_state.project_id, data, current_table)
                                    added_count += 1
                        
                        st.success(f"Imported {added_count} studies! (Skipped duplicates)")

    # --- TAB 3: AUDIT RECORDS ---
    idx = 2 if mode == "level_2" else 1
    with tabs[idx]:
        st.subheader("🗃️ Audit Records")
        res = db.get_project_results(st.session_state.project_id, current_table)
        df = pd.DataFrame(res)
        if not df.empty:
            
            # --- FIX: VISUAL RE-INDEXING (1, 2, 3...) ---
            df = df.sort_values(by='ID') # Ensure consistent order
            df['Display_ID'] = range(1, len(df) + 1)
            
            c_fil, c_view = st.columns([1, 2])
            with c_fil:
                dec = st.selectbox("Decision", ["All", "INCLUDE", "EXCLUDE", "UNCLEAR"])
                src_list = ["All"] + list(df['Source'].unique()) if 'Source' in df.columns else ["All"]
                src = st.selectbox("Source", src_list)
                max_c = st.slider("Max Confidence (Find uncertain)", 0, 100, 100)
                
                vdf = df[df['Confidence'] <= max_c]
                if dec != "All": vdf = vdf[vdf['Decision'] == dec]
                if src != "All": vdf = vdf[vdf['Source'] == src]
                
                # Use Display_ID for the radio button label, but keep ID for logic
                sel = st.radio("Select:", vdf['ID'], format_func=lambda x: f"#{vdf[vdf.ID==x]['Display_ID'].iloc[0]} {vdf[vdf.ID==x]['Title'].iloc[0][:30]}...")
            
            with c_view:
                if sel and not vdf.empty:
                    row = df[df.ID == sel].iloc[0]
                    # Show Display ID in Title
                    st.markdown(f"### #{row['Display_ID']}: {row['Title']}")
                    render_full_result_view(row)
                    st.info(f"**AI Reason:** {row['Reason']}")
                    with st.expander("Full Text / Abstract", expanded=False): st.write(row['Abstract'])
                    
                    c_b1, c_b2 = st.columns(2)
                    if c_b1.button("Override: INCLUDE", use_container_width=True): db.update_result_decision(int(row['ID']), "INCLUDE", "Manual Override", current_table); st.rerun()
                    if c_b2.button("Override: EXCLUDE", use_container_width=True): db.update_result_decision(int(row['ID']), "EXCLUDE", "Manual Override", current_table); st.rerun()

    # --- TAB 4: DASHBOARD ---
    idx = 3 if mode == "level_2" else 2
    with tabs[idx]:
        st.subheader("📊 Analytics")
        if not df.empty:
            total_studies = len(df)
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Total Studies", total_studies)
            m2.metric("Included", len(df[df['Decision']=='INCLUDE']))
            m3.metric("Excluded", len(df[df['Decision']=='EXCLUDE']))
            m4.metric("Unclear", len(df[df['Decision']=='UNCLEAR']))
            st.divider()
            
            ov_df = df[df['Override_History'] != ""]
            ov_num = len(ov_df)
            ov_pct = round((ov_num / total_studies) * 100, 1) if total_studies > 0 else 0
            
            ov_to_inc = len(ov_df[ov_df['Decision'] == 'INCLUDE'])
            ov_to_exc = len(ov_df[ov_df['Decision'] == 'EXCLUDE'])
            
            st.markdown("#### ⚠️ Override Analysis")
            o1, o2, o3, o4 = st.columns(4)
            o1.metric("Total Overrides", f"{ov_num}")
            o2.metric("Override Rate", f"{ov_pct}%")
            o3.metric("Overridden → INCLUDE", f"{ov_to_inc}")
            o4.metric("Overridden → EXCLUDE", f"{ov_to_exc}")
            
            st.divider()
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("#### Decisions by Source")
                if 'Source' in df.columns:
                    df['SourceType'] = df['Source'].apply(lambda x: "Mined" if "Mined" in str(x) else "Direct Upload")
                    st.bar_chart(df.groupby("SourceType")['Decision'].value_counts().unstack())
            with c2:
                st.markdown("#### Confidence Distribution")
                import altair as alt
                chart = alt.Chart(df).mark_bar().encode(
                    alt.X("Confidence:Q", bin=True, title="Confidence Score"),
                    alt.Y("count()", title="Number of Studies"),
                    tooltip=["count()"]
                ).interactive()
                st.altair_chart(chart, use_container_width=True)
            
            st.download_button("Download Full Data CSV", df.to_csv().encode('utf-8'), "audit_data.csv")