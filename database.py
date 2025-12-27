import sqlite3
import json
import hashlib

DB_NAME = "audit_app.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # UPDATED: Added 'email' column
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (username TEXT PRIMARY KEY, email TEXT, password TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS projects
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  user_id TEXT, name TEXT, pico_data TEXT, 
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # RE-ADDED: The separate Level 1 / Level 2 tables
    c.execute('''CREATE TABLE IF NOT EXISTS results_level_1
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  project_id INTEGER,
                  title TEXT, abstract TEXT, 
                  decision TEXT, reason TEXT, confidence INTEGER,
                  p_check BOOLEAN, i_check BOOLEAN, c_check BOOLEAN, 
                  o_check BOOLEAN, s_check BOOLEAN, e_check BOOLEAN,
                  p_reas TEXT, i_reas TEXT, c_reas TEXT, 
                  o_reas TEXT, s_reas TEXT, e_reas TEXT,
                  source TEXT, override_history TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS results_level_2
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  project_id INTEGER,
                  title TEXT, abstract TEXT, 
                  decision TEXT, reason TEXT, confidence INTEGER,
                  p_check BOOLEAN, i_check BOOLEAN, c_check BOOLEAN, 
                  o_check BOOLEAN, s_check BOOLEAN, e_check BOOLEAN,
                  p_reas TEXT, i_reas TEXT, c_reas TEXT, 
                  o_reas TEXT, s_reas TEXT, e_reas TEXT,
                  source TEXT, override_history TEXT)''')

    conn.commit()
    conn.close()

# --- USER FUNCTIONS (Updated) ---
def create_user(username, email, password):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    hashed_pw = hashlib.sha256(password.encode()).hexdigest()
    try:
        # Now inserting email as well
        c.execute("INSERT INTO users VALUES (?, ?, ?)", (username, email, hashed_pw))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False # Username already exists
    finally:
        conn.close()

def login_user(username, password):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    hashed_pw = hashlib.sha256(password.encode()).hexdigest()
    # We don't check email for login, just username/pass
    c.execute("SELECT * FROM users WHERE username=? AND password=?", (username, hashed_pw))
    user = c.fetchone()
    conn.close()
    return user is not None

# --- PROJECT FUNCTIONS ---
def create_project(user_id, name, pico_dict):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO projects (user_id, name, pico_data) VALUES (?, ?, ?)", 
              (user_id, name, json.dumps(pico_dict)))
    pid = c.lastrowid
    conn.commit()
    conn.close()
    return pid

def get_user_projects(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, name, pico_data FROM projects WHERE user_id=?", (user_id,))
    projects = []
    for row in c.fetchall():
        projects.append({"id": row[0], "name": row[1], "pico": json.loads(row[2])})
    conn.close()
    return projects

def update_project_pico(project_id, pico_dict):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE projects SET pico_data=? WHERE id=?", (json.dumps(pico_dict), project_id))
    conn.commit()
    conn.close()

# --- RESULT FUNCTIONS (Stage-Aware) ---
def save_result(project_id, data, stage_table):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    query = f'''INSERT INTO {stage_table} (
        project_id, title, abstract, decision, reason, confidence,
        p_check, i_check, c_check, o_check, s_check, e_check,
        p_reas, i_reas, c_reas, o_reas, s_reas, e_reas,
        source, override_history
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)'''
    
    c.execute(query, (
        project_id, data['Title'], data['Abstract'], data['Decision'], data['Reason'], data['Confidence'],
        data['P'], data['I'], data['C'], data['O'], data['S'], data['E'],
        data['P_Reas'], data['I_Reas'], data['C_Reas'], data['O_Reas'], data['S_Reas'], data['E_Reas'],
        data['Source'], data['Override_History']
    ))
    new_id = c.lastrowid
    conn.commit()
    conn.close()
    return new_id

def get_project_results(project_id, stage_table):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    query = f"SELECT * FROM {stage_table} WHERE project_id=?"
    c.execute(query, (project_id,))
    rows = c.fetchall()
    conn.close()
    
    results = []
    for row in rows:
        results.append({
            "ID": row['id'],
            "Title": row['title'],
            "Abstract": row['abstract'],
            "Decision": row['decision'],
            "Reason": row['reason'],
            "Confidence": row['confidence'],
            "P": bool(row['p_check']), "I": bool(row['i_check']), 
            "C": bool(row['c_check']), "O": bool(row['o_check']), 
            "S": bool(row['s_check']), "E": bool(row['e_check']),
            "P_Reas": row['p_reas'], "I_Reas": row['i_reas'], 
            "C_Reas": row['c_reas'], "O_Reas": row['o_reas'], 
            "S_Reas": row['s_reas'], "E_Reas": row['e_reas'],
            "Source": row['source'],
            "Override_History": row['override_history']
        })
    return results

def update_result_decision(result_id, new_decision, override_note, stage_table):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    query = f"UPDATE {stage_table} SET decision=?, override_history=? WHERE id=?"
    c.execute(query, (new_decision, override_note, result_id))
    conn.commit()
    conn.close()