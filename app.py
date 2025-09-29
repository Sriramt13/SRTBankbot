from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from datetime import datetime
import spacy, os, csv, random, sqlite3, pandas as pd, subprocess

app = Flask(__name__)
app.secret_key = "srt_bank_secret_key"

# --- Load AI Model ---
def load_model():
    global nlp_model
    try:
        nlp_model = spacy.load("bank_nlu_model")
        print("✅ NLU model loaded successfully.")
    except IOError:
        nlp_model = None
        print("❌ NLU model not found. Run train.py first.")

load_model()

# --- Load Chatbot Responses ---
responses_dict = {}
def load_responses():
    global responses_dict
    responses_dict = {}
    file_path = "training_and_responses.csv"
    if not os.path.exists(file_path):
        print("❌ training_and_responses.csv not found.")
        return
    try:
        df = pd.read_csv(file_path, header=None, names=['example','intent','response','source'], on_bad_lines='skip')
        for _, row in df.iterrows():
            responses_dict.setdefault(row['intent'], []).append(row['response'])
        print("✅ Responses loaded from CSV.")
    except Exception as e:
        print(f"❌ Error loading CSV: {e}")

load_responses()

# --- Database Logs ---
def save_log(user_message, intent, entities, bot_response):
    conn = sqlite3.connect("logs.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_message TEXT,
            intent TEXT,
            entities TEXT,
            bot_response TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute(
        "INSERT INTO logs (user_message, intent, entities, bot_response) VALUES (?, ?, ?, ?)",
        (user_message, intent, str(entities), bot_response)
    )
    conn.commit()
    conn.close()

# --- Users & Dummy Data ---
users = {"teja": "srt123", "sri": "bank123", "admin": "admin123"}

account_profile = {"name": "Teja", "number": "96182240", "type": "Savings", "balance": 75000.00}
transactions = [
    {"date": "2025-08-20", "desc": "Zomato Order", "amount": -450.00},
    {"date": "2025-08-18", "desc": "Amazon Purchase", "amount": -2999.00},
    {"date": "2025-08-15", "desc": "Flipkart Refund", "amount": 1500.00},
    {"date": "2025-08-10", "desc": "Rent Payment", "amount": -15000.00},
]
cards_info = {"debit": {"status": "Active", "last4": "4321"}, "credit": {"status": "Active", "last4": "9988"}}
loans_catalog = [{"type": "Personal Loan", "rate": "11.25% p.a."}, {"type": "Home Loan", "rate": "8.50% p.a."}]
branches = [
    {"city": "Hyderabad", "name": "SRT Bank - HiTech City", "address": "Plot 21, Cyber Towers", "ifsc": "SRTB0000123"},
    {"city": "Bengaluru", "name": "SRT Bank - Indiranagar", "address": "100ft Rd, HAL 2nd Stage", "ifsc": "SRTB0000456"},
    {"city": "Mumbai", "name": "SRT Bank - BKC", "address": "G Block, Bandra Kurla Complex", "ifsc": "SRTB0000789"},
]

def logged_in(): return "user" in session and session["user"] != "admin"
def is_admin(): return session.get("user") == "admin"

# --- Routes ---
@app.route("/")
def home(): return render_template("index.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        u = request.form.get("username","").strip()
        p = request.form.get("password","").strip()
        if u in users and users[u] == p:
            session["user"] = u
            if u == "admin": return redirect(url_for("admin_home"))
            return redirect(url_for("dashboard"))
        flash("Invalid credentials. Try again.","danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.route("/admin")
def admin_home():
    if not is_admin():
        flash("❌ Access denied.", "danger")
        return redirect(url_for("login"))
    return render_template("admin_home.html")

@app.route("/dashboard")
def dashboard():
    if not logged_in(): return redirect(url_for("login"))
    return render_template("dashboard.html", user=session["user"], cards=cards_info, txns=transactions)

@app.route("/balance")
def balance():
    if not logged_in(): return redirect(url_for("login"))
    return render_template("balance.html", profile=account_profile)

@app.route("/transactions")
def transactions_page():
    if not logged_in(): return redirect(url_for("login"))
    txns_with_balance=[]
    running_balance=0
    for t in transactions:
        running_balance += t['amount']
        txn = t.copy()
        txn['balance'] = running_balance
        txns_with_balance.append(txn)
    return render_template("transactions.html", txns=txns_with_balance)

@app.route("/loans")
def loans(): return render_template("loans.html", loans=loans_catalog) if logged_in() else redirect(url_for("login"))
@app.route("/cards")
def cards(): return render_template("cards.html", cards=cards_info) if logged_in() else redirect(url_for("login"))
@app.route("/branches")
def branches_list(): return render_template("branches.html", branches=branches) if logged_in() else redirect(url_for("login"))
@app.route("/chatbot")
def chatbot(): return render_template("chatbot.html", now=datetime.now().strftime("%d %b %Y, %I:%M %p")) if logged_in() else redirect(url_for("login"))

@app.route("/admin/logs")
def view_logs():
    if not is_admin():
        flash("❌ Access denied.", "danger")
        return redirect(url_for("login"))
    conn = sqlite3.connect("logs.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM logs ORDER BY timestamp DESC LIMIT 50")
    logs = cursor.fetchall()
    conn.close()
    return render_template("admin_logs.html", logs=logs)

@app.route("/admin/training", methods=["GET","POST"])
def admin_training():
    if not is_admin():
        flash("❌ Access denied.", "danger")
        return redirect(url_for("login"))
    file_path = "training_and_responses.csv"
    if request.method=="POST":
        intent = request.form.get("intent","").strip()
        example = request.form.get("example","").strip()
        response = request.form.get("response","").strip()
        if intent and example and response:
            with open(file_path,"a",encoding="utf-8",newline="") as f:
                writer = csv.writer(f, quoting=csv.QUOTE_ALL)
                writer.writerow([example,intent,response,"admin_added"])
            flash("✅ New training row added!","success")
            load_responses()
        else:
            flash("⚠️ Please fill all fields.","danger")
    rows=[]
    if os.path.exists(file_path):
        try:
            df = pd.read_csv(file_path, header=None, names=['example','intent','response','source'], on_bad_lines='skip')
            rows = df.values.tolist()
        except Exception:
            rows = []
    return render_template("admin_training.html", rows=rows)

@app.route("/admin/training/delete/<int:row_index>", methods=["POST"])
def delete_training_row(row_index):
    if not is_admin():
        flash("❌ Access denied.", "danger")
        return redirect(url_for("login"))
    file_path = "training_and_responses.csv"
    if os.path.exists(file_path):
        try:
            df = pd.read_csv(file_path, header=None, names=['example','intent','response','source'], on_bad_lines='skip')
            if 0 <= row_index < len(df):
                df = df.drop(index=row_index).reset_index(drop=True)
                df.to_csv(file_path, index=False, header=False, quoting=csv.QUOTE_ALL)
                flash("✅ Training row deleted successfully.","success")
                load_responses()
            else:
                flash("⚠️ Invalid row index.","danger")
        except Exception as e:
            flash(f"❌ Error deleting row: {str(e)}","danger")
    else:
        flash("⚠️ Training CSV file not found.","danger")
    return redirect(url_for("admin_training"))

@app.route("/admin/retrain", methods=["POST"])
def retrain_model():
    if not is_admin():
        flash("❌ Access denied.", "danger")
        return redirect(url_for("login"))
    try:
        subprocess.run(["python","train.py"], check=True)
        load_model()
        load_responses()
        flash("✅ Model retrained successfully!","success")
    except Exception as e:
        flash(f"❌ Retrain failed: {str(e)}","danger")
    return redirect(url_for("admin_training"))

# --- Chat API with Fixed Transfer Flow ---
@app.route("/api/chat", methods=["POST"])
def api_chat():
    if not logged_in():
        return jsonify({"reply": "Authentication error.", "intent": "error"})
    
    data = request.get_json() or {}
    message = (data.get("message") or "").strip()
    
    if not nlp_model:
        return jsonify({"reply": "AI model not available.", "intent": "error"})
    
    state = session.get("conversation_state")
    transfer_details = session.get("transfer_details", {})

    # --- Check Balance ---
    if state == "awaiting_account_number":
        account_number = message.replace(" ","")
        if account_number == account_profile["number"]:
            reply = f"💰 Your account balance is ₹{account_profile['balance']:.2f}."
        else:
            reply = "⚠️ Account number not recognized. Please try again."
        session.pop("conversation_state", None)
        save_log(message, "check_balance", [("ACCOUNT_NUMBER", account_number)], reply)
        return jsonify({"reply": reply, "intent": "check_balance"})

    # --- Transfer Money Flow ---
    if state == "awaiting_recipient":
        session['transfer_details'] = {"recipient": message}
        session['conversation_state'] = "awaiting_amount"
        reply = f"💸 How much would you like to send to {message}?"
        save_log(message, "transfer_money", [("recipient", message)], reply)
        return jsonify({"reply": reply, "intent": "transfer_money"})

    if state == "awaiting_amount":
        try:
            amount = float(message.replace("₹","").replace(",","").strip())
            recipient = transfer_details.get("recipient")
            if amount <= 0:
                reply = "⚠️ Please enter a valid amount greater than 0."
            elif amount > account_profile["balance"]:
                reply = f"⚠️ Insufficient balance! Your current balance is ₹{account_profile['balance']:.2f}."
            else:
                # Ask for confirmation
                transfer_details["amount"] = amount
                session['transfer_details'] = transfer_details
                session['conversation_state'] = "awaiting_confirmation"
                reply = f"💡 Please confirm: Send ₹{amount:.2f} to {recipient}? (yes/no)"
                save_log(message, "transfer_money", [("recipient", recipient), ("amount", amount)], reply)
                return jsonify({"reply": reply, "intent": "transfer_money"})
        except ValueError:
            reply = "⚠️ Please enter a valid numeric amount."
            save_log(message, "transfer_money", [], reply)
            return jsonify({"reply": reply, "intent": "transfer_money"})

    if state == "awaiting_confirmation":
        recipient = transfer_details.get("recipient")
        amount = transfer_details.get("amount")
        if message.lower() in ["yes", "y"]:
            account_profile["balance"] -= amount
            transactions.append({
                "date": datetime.now().strftime("%Y-%m-%d"),
                "desc": f"Transfer to {recipient}",
                "amount": -amount
            })
            reply = f"✅ Successfully sent ₹{amount:.2f} to {recipient}. Your new balance is ₹{account_profile['balance']:.2f}."
        else:
            reply = f"❌ Transfer of ₹{amount:.2f} to {recipient} canceled."
        session.pop("conversation_state", None)
        session.pop("transfer_details", None)
        save_log(message, "transfer_money", [("recipient", recipient), ("amount", amount)], reply)
        return jsonify({"reply": reply, "intent": "transfer_money"})

    # --- NLU Processing ---
    doc = nlp_model(message)
    if not doc.cats:
        reply = "I'm sorry, I'm not sure how to help with that."
        save_log(message, "n/a", [], reply)
        return jsonify({"reply": reply, "intent": "n/a"})

    predicted_intent = max(doc.cats, key=doc.cats.get)
    confidence = doc.cats[predicted_intent]

    if confidence > 0.65:
        if predicted_intent == "check_balance":
            session['conversation_state'] = 'awaiting_account_number'
            reply = "💰 Please provide your account number."
        elif predicted_intent == "transfer_money":
            session['conversation_state'] = 'awaiting_recipient'
            session['transfer_details'] = {}
            reply = "💸 Who should I send money to?"
        else:
            reply = random.choice(responses_dict.get(predicted_intent, ["I don't have a response yet."]))
    else:
        predicted_intent = "out_of_scope"
        reply = random.choice(responses_dict.get('out_of_scope', ["I can only assist with banking questions."]))

    entities = [(ent.text, ent.label_) for ent in doc.ents]
    save_log(message, predicted_intent, entities, reply)
    return jsonify({"reply": reply, "intent": predicted_intent})

if __name__=="__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
