# app.py (Patched — requires account number between recipient and amount)
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from datetime import datetime
import spacy, os, csv, random, sqlite3, pandas as pd, subprocess, re

# Matplotlib for admin analytics image generation
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

app = Flask(__name__)
app.secret_key = "srt_bank_secret_key"

# -------------------------
# Load NLU model
# -------------------------
def load_model():
    global nlp_model
    try:
        nlp_model = spacy.load("bank_nlu_model")
        print("✅ NLU model loaded successfully.")
    except Exception as e:
        nlp_model = None
        print("❌ NLU model not found. Run train.py first. Error:", e)

load_model()

# -------------------------
# Load chatbot responses from CSV (robust)
# CSV columns: example,intent,response,source
# -------------------------
responses_dict = {}
def load_responses():
    global responses_dict
    responses_dict = {}
    file_path = "training_and_responses.csv"
    if not os.path.exists(file_path):
        print("❌ training_and_responses.csv not found.")
        return
    try:
        # Read CSV, skip header if present; handle malformed rows gracefully
        df = pd.read_csv(file_path, header=None, names=['example','intent','response','source'], on_bad_lines='skip', dtype=str)
        for idx, row in df.iterrows():
            intent = str(row['intent']).strip() if not pd.isna(row['intent']) else ""
            response = str(row['response']).strip() if not pd.isna(row['response']) else ""
            # skip blank intent
            if not intent:
                continue
            # allow blank response? skip empty response entries to avoid empty replies
            if response == "" or response.lower() == "nan":
                continue
            responses_dict.setdefault(intent, []).append(response)
        print("✅ Responses loaded from CSV. Intents:", list(responses_dict.keys()))
    except Exception as e:
        print(f"❌ Error loading CSV: {e}")

load_responses()

# -------------------------
# Logging helper (sqlite)
# -------------------------
def save_log(user_message, intent, entities, bot_response):
    try:
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
    except Exception as e:
        print("Error saving log:", e)
    finally:
        try:
            conn.close()
        except:
            pass

# -------------------------
# Dummy data / Users
# -------------------------
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

def logged_in():
    return "user" in session and session["user"] != "admin"

def is_admin():
    return session.get("user") == "admin"

# -------------------------
# Routes: Public / User
# -------------------------
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "").strip()
        if u in users and users[u] == p:
            session["user"] = u
            # clear conversation state on login
            session.pop("conversation_state", None)
            session.pop("transfer_details", None)
            if u == "admin":
                return redirect(url_for("admin_home"))
            return redirect(url_for("dashboard"))
        flash("Invalid credentials. Try again.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.route("/dashboard")
def dashboard():
    if not logged_in():
        return redirect(url_for("login"))
    return render_template("dashboard.html", user=session["user"], cards=cards_info, txns=transactions)

@app.route("/balance")
def balance():
    if not logged_in():
        return redirect(url_for("login"))
    return render_template("balance.html", profile=account_profile)

@app.route("/transactions")
def transactions_page():
    if not logged_in():
        return redirect(url_for("login"))
    txns_with_balance = []
    # compute running balance starting from current balance and going backwards
    running_balance = account_profile["balance"]
    for t in reversed(transactions):
        txn = t.copy()
        txn['balance'] = running_balance
        running_balance -= t['amount']
        txns_with_balance.append(txn)
    txns_with_balance.reverse()
    return render_template("transactions.html", txns=txns_with_balance)

@app.route("/loans")
def loans():
    if not logged_in():
        return redirect(url_for("login"))
    return render_template("loans.html", loans=loans_catalog)

@app.route("/cards")
def cards():
    if not logged_in():
        return redirect(url_for("login"))
    return render_template("cards.html", cards=cards_info)

@app.route("/branches")
def branches_list():
    if not logged_in():
        return redirect(url_for("login"))
    return render_template("branches.html", branches=branches)

@app.route("/chatbot")
def chatbot():
    if not logged_in():
        return render_template("chatbot.html", now=datetime.now().strftime("%d %b %Y, %I:%M %p"))

# -------------------------
# Admin pages: logs / training / retrain / analytics
# -------------------------
@app.route("/admin")
def admin_home():
    if not is_admin():
        flash("❌ Access denied.", "danger")
        return redirect(url_for("login"))
    return render_template("admin_home.html")

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
    if request.method == "POST":
        intent = request.form.get("intent", "").strip()
        example = request.form.get("example", "").strip()
        response = request.form.get("response", "").strip()
        if intent and example and response:
            with open(file_path, "a", encoding="utf-8", newline="") as f:
                writer = csv.writer(f, quoting=csv.QUOTE_ALL)
                writer.writerow([example, intent, response, "admin_added"])
            flash("✅ New training row added!", "success")
            load_responses()
        else:
            flash("⚠️ Please fill all fields.", "danger")

    rows = []
    if os.path.exists(file_path):
        try:
            df = pd.read_csv(file_path, header=None, names=['example','intent','response','source'], on_bad_lines='skip', dtype=str)
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
            df = pd.read_csv(file_path, header=None, names=['example','intent','response','source'], on_bad_lines='skip', dtype=str)
            if 0 <= row_index < len(df):
                df = df.drop(index=row_index).reset_index(drop=True)
                df.to_csv(file_path, index=False, header=False, quoting=csv.QUOTE_ALL)
                flash("✅ Training row deleted successfully.", "success")
                load_responses()
            else:
                flash("⚠️ Invalid row index.", "danger")
        except Exception as e:
            flash(f"❌ Error deleting row: {str(e)}", "danger")
    else:
        flash("⚠️ Training CSV file not found.", "danger")
    return redirect(url_for("admin_training"))

@app.route("/admin/retrain", methods=["POST"])
def retrain_model():
    if not is_admin():
        flash("❌ Access denied.", "danger")
        return redirect(url_for("login"))
    try:
        subprocess.run(["python", "train.py"], check=True)
        load_model()
        load_responses()
        flash("✅ Model retrained successfully!", "success")
    except Exception as e:
        flash(f"❌ Retrain failed: {str(e)}", "danger")
    return redirect(url_for("admin_training"))

@app.route("/admin/analytics", methods=["GET","POST"])
def admin_analytics():
    if not is_admin():
        flash("❌ Access denied.", "danger")
        return redirect(url_for("login"))

    analytics_dir = os.path.join("static", "analytics")
    os.makedirs(analytics_dir, exist_ok=True)

    if request.method == "POST":
        try:
            conn = sqlite3.connect("logs.db")
            df = pd.read_sql_query("SELECT intent, user_message FROM logs", conn)
            conn.close()
            if df.empty:
                flash("⚠️ No logs found for analysis.", "warning")
            else:
                # Intent distribution pie chart
                plt.figure(figsize=(6,6))
                df['intent'].value_counts().plot(kind='pie', autopct='%1.1f%%')
                plt.title("Intent Distribution")
                plt.tight_layout()
                plt.savefig(os.path.join(analytics_dir, "intent_distribution.png"))
                plt.close()

                # Top queries bar chart
                plt.figure(figsize=(10,4))
                df['user_message'].value_counts().head(10).plot(kind='bar')
                plt.title("Top 10 User Queries")
                plt.xlabel("Query")
                plt.ylabel("Count")
                plt.tight_layout()
                plt.savefig(os.path.join(analytics_dir, "top_queries.png"))
                plt.close()

                # Out-of-scope bar
                oos = (df['intent'] == 'out_of_scope').sum()
                total = len(df)
                plt.figure(figsize=(5,4))
                plt.bar(['In-Scope','Out-of-Scope'], [total - oos, oos])
                plt.title("Out-of-Scope Queries")
                plt.tight_layout()
                plt.savefig(os.path.join(analytics_dir, "out_of_scope.png"))
                plt.close()

                flash("✅ Analytics charts generated successfully!", "success")
        except Exception as e:
            flash(f"❌ Error generating analytics: {str(e)}", "danger")

    return render_template("admin_analytics.html")

# -------------------------
# Chat API: robust multi-step + entity autofill
# -------------------------
@app.route("/api/chat", methods=["POST"])
def api_chat():
    if not logged_in():
        return jsonify({"reply": "Authentication error.", "intent": "error"})

    data = request.get_json() or {}
    message = (data.get("message") or "").strip()

    if not nlp_model:
        return jsonify({"reply": "AI model not available.", "intent": "error"})

    # Ensure transfer_details exists
    transfer_details = session.get("transfer_details") or {}
    state = session.get("conversation_state")

    # -------------------------
    # Handle stateful flows first
    # -------------------------
    # Balance: waiting for account number (existing)
    if state == "awaiting_account_number":
        account_number = message.replace(" ", "")
        if account_number == account_profile["number"]:
            reply = f"💰 Your account balance is ₹{account_profile['balance']:.2f}."
        else:
            reply = "⚠️ Account number not recognized. Please try again."
        session.pop("conversation_state", None)
        session.pop("transfer_details", None)
        save_log(message, "check_balance", [("ACCOUNT_NUMBER", account_number)], reply)
        return jsonify({"reply": reply, "intent": "check_balance"})

    # Transfer: waiting for recipient (user just gave recipient name)
    if state == "awaiting_recipient":
        recipient = message.strip()
        transfer_details = {"recipient": recipient}
        session['transfer_details'] = transfer_details
        # NEW: ask for recipient's account number BEFORE amount
        session['conversation_state'] = "awaiting_recipient_account"
        reply = f"💸 What's {recipient}'s account number?"
        save_log(message, "transfer_money", [("recipient", recipient)], reply)
        return jsonify({"reply": reply, "intent": "transfer_money"})

    # NEW: waiting for recipient's account number (distinct from balance flow)
    if state == "awaiting_recipient_account":
        account_number = message.replace(" ", "")
        # basic validation: digits only, length 6-20
        if not re.match(r"^\d{6,20}$", account_number):
            reply = "⚠️ That doesn't look like a valid account number. Please enter digits only (6–20 digits)."
            save_log(message, "transfer_money", [("ACCOUNT_NUMBER", account_number)], reply)
            return jsonify({"reply": reply, "intent": "transfer_money"})

        # save account number
        transfer_details = session.get('transfer_details') or {}
        transfer_details['account_number'] = account_number
        session['transfer_details'] = transfer_details

        # If amount already present (NLU or user gave it earlier), go straight to confirmation
        if 'amount' in transfer_details and transfer_details['amount'] is not None:
            amount = transfer_details['amount']
            recipient = transfer_details.get('recipient', 'the recipient')
            session['conversation_state'] = "awaiting_confirmation"
            acct_mask = f" (Acc: ****{account_number[-4:]})" if len(account_number) >= 4 else ""
            reply = f"💡 Please confirm: Send ₹{amount:.2f} to {recipient}{acct_mask}? (yes/no)"
            save_log(message, "transfer_money", [("recipient", recipient), ("ACCOUNT_NUMBER", account_number), ("amount", amount)], reply)
            return jsonify({"reply": reply, "intent": "transfer_money"})

        # Otherwise ask for amount (normal flow)
        session['conversation_state'] = "awaiting_amount"
        recipient = transfer_details.get("recipient", "the recipient")
        reply = f"💸 How much would you like to send to {recipient}?"
        save_log(message, "transfer_money", [("recipient", recipient), ("ACCOUNT_NUMBER", account_number)], reply)
        return jsonify({"reply": reply, "intent": "transfer_money"})

    # Transfer: waiting for amount
    if state == "awaiting_amount":
        try:
            amount = float(message.replace("₹","").replace(",","").strip())
            recipient = transfer_details.get("recipient")
            if recipient is None:
                session.pop("conversation_state", None)
                session.pop("transfer_details", None)
                reply = "⚠️ Recipient missing. Please start the transfer again."
                save_log(message, "transfer_money", [], reply)
                return jsonify({"reply": reply, "intent": "transfer_money"})

            if amount <= 0:
                reply = "⚠️ Please enter a valid amount greater than 0."
                save_log(message, "transfer_money", [("recipient", recipient)], reply)
                return jsonify({"reply": reply, "intent": "transfer_money"})

            if amount > account_profile["balance"]:
                reply = f"⚠️ Insufficient balance! Your current balance is ₹{account_profile['balance']:.2f}."
                save_log(message, "transfer_money", [("recipient", recipient), ("amount", amount)], reply)
                return jsonify({"reply": reply, "intent": "transfer_money"})

            # ask for confirmation
            transfer_details["amount"] = amount
            session['transfer_details'] = transfer_details
            session['conversation_state'] = "awaiting_confirmation"

            # mask account number if exists
            acct = transfer_details.get("account_number")
            acct_mask = f" (Acc: ****{acct[-4:]})" if acct and len(acct) >= 4 else ""
            reply = f"💡 Please confirm: Send ₹{amount:.2f} to {recipient}{acct_mask}? (yes/no)"
            save_log(message, "transfer_money", [("recipient", recipient), ("amount", amount)], reply)
            return jsonify({"reply": reply, "intent": "transfer_money"})

        except ValueError:
            reply = "⚠️ Please enter a valid numeric amount."
            save_log(message, "transfer_money", [], reply)
            return jsonify({"reply": reply, "intent": "transfer_money"})

    # Transfer: waiting for confirmation
    if state == "awaiting_confirmation":
        recipient = transfer_details.get("recipient")
        amount = transfer_details.get("amount", 0)
        if message.lower() in ["yes", "y"]:
            account_profile["balance"] -= amount
            transactions.append({
                "date": datetime.now().strftime("%Y-%m-%d"),
                "desc": f"Transfer to {recipient}",
                "amount": -amount
            })
            acct = transfer_details.get("account_number")
            acct_mask = f" (Acc: ****{acct[-4:]})" if acct and len(acct) >= 4 else ""
            reply = f"✅ Successfully sent ₹{amount:.2f} to {recipient}{acct_mask}. Your new balance is ₹{account_profile['balance']:.2f}."
        else:
            reply = f"❌ Transfer of ₹{amount:.2f} to {recipient} canceled."
        session.pop("conversation_state", None)
        session.pop("transfer_details", None)
        save_log(message, "transfer_money", [("recipient", recipient), ("amount", amount)], reply)
        return jsonify({"reply": reply, "intent": "transfer_money"})

    # -------------------------
    # No active state: use NLU
    # -------------------------
    try:
        doc = nlp_model(message)
    except Exception as e:
        reply = "I'm sorry, I'm not sure how to help with that."
        save_log(message, "n/a", [], reply)
        return jsonify({"reply": reply, "intent": "n/a"})

    if not getattr(doc, "cats", None):
        reply = "I'm sorry, I'm not sure how to help with that."
        save_log(message, "n/a", [], reply)
        return jsonify({"reply": reply, "intent": "n/a"})

    # Build entities map (upper-cased labels)
    entities_map = {}
    for ent in getattr(doc, "ents", []):
        lab = ent.label_.upper()
        val = ent.text.strip()
        entities_map.setdefault(lab, []).append(val)

    predicted_intent = max(doc.cats, key=doc.cats.get)
    confidence = doc.cats[predicted_intent]

    # High-confidence pathway with auto-fill when entities present
    if confidence > 0.65:
        # Immediate balance if model found ACCOUNT_NUMBER
        if predicted_intent == "check_balance" and entities_map.get("ACCOUNT_NUMBER"):
            acct = entities_map["ACCOUNT_NUMBER"][0].replace(" ", "")
            if acct == account_profile["number"]:
                reply = f"💰 Your account balance is ₹{account_profile['balance']:.2f}."
            else:
                reply = "⚠️ Account number not recognized. Please try again."
            save_log(message, "check_balance", [("ACCOUNT_NUMBER", acct)], reply)
            return jsonify({"reply": reply, "intent": "check_balance"})

        # Immediate transfer if PERSON and MONEY and ACCOUNT_NUMBER present
        if predicted_intent == "transfer_money" and entities_map.get("PERSON") and entities_map.get("MONEY"):
            recipient = entities_map["PERSON"][0]
            raw_amount = entities_map["MONEY"][0]
            try:
                amount = float(''.join(ch for ch in raw_amount if (ch.isdigit() or ch == '.')))
            except:
                amount = None

            if amount is None:
                # couldn't parse amount — go to awaiting_amount (but require account first)
                session['conversation_state'] = 'awaiting_recipient_account'
                session['transfer_details'] = {"recipient": recipient}
                reply = f"💸 I couldn't parse the amount. What's {recipient}'s account number so I can continue?"
                save_log(message, "transfer_money", [("recipient", recipient)], reply)
                return jsonify({"reply": reply, "intent": "transfer_money"})

            # Validate amount
            if amount <= 0:
                reply = "⚠️ Please enter a valid amount greater than 0."
                save_log(message, "transfer_money", [("recipient", recipient), ("amount", amount)], reply)
                return jsonify({"reply": reply, "intent": "transfer_money"})

            if amount > account_profile["balance"]:
                reply = f"⚠️ Insufficient balance! Your current balance is ₹{account_profile['balance']:.2f}."
                save_log(message, "transfer_money", [("recipient", recipient), ("amount", amount)], reply)
                return jsonify({"reply": reply, "intent": "transfer_money"})

            # If NLU provided ACCOUNT_NUMBER entity too, proceed; otherwise ask for account number
            if entities_map.get("ACCOUNT_NUMBER"):
                acct = entities_map["ACCOUNT_NUMBER"][0].replace(" ", "")
                if not re.match(r"^\d{6,20}$", acct):
                    reply = "⚠️ Account number detected but invalid. Please provide the account number (digits only, 6–20 digits)."
                    save_log(message, "transfer_money", [("recipient", recipient), ("amount", amount), ("ACCOUNT_NUMBER", acct)], reply)
                    return jsonify({"reply": reply, "intent": "transfer_money"})
                # perform transfer
                account_profile["balance"] -= amount
                transactions.append({
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "desc": f"Transfer to {recipient}",
                    "amount": -amount
                })
                acct_mask = f" (Acc: ****{acct[-4:]})" if len(acct) >= 4 else ""
                reply = f"✅ Successfully sent ₹{amount:.2f} to {recipient}{acct_mask}. Your new balance is ₹{account_profile['balance']:.2f}."
                save_log(message, "transfer_money", [("recipient", recipient), ("amount", amount), ("ACCOUNT_NUMBER", acct)], reply)
                return jsonify({"reply": reply, "intent": "transfer_money"})
            else:
                # request account number before performing transfer
                session['conversation_state'] = 'awaiting_recipient_account'
                session['transfer_details'] = {"recipient": recipient, "amount": amount}
                reply = f"💸 Please provide {recipient}'s account number to proceed."
                save_log(message, "transfer_money", [("recipient", recipient), ("amount", amount)], reply)
                return jsonify({"reply": reply, "intent": "transfer_money"})

        # If not autofilled, move into multi-turn
        if predicted_intent == "check_balance":
            session['conversation_state'] = 'awaiting_account_number'
            reply = random.choice(responses_dict.get(predicted_intent, ["💰 Please provide your account number."]))
        elif predicted_intent == "transfer_money":
            session['conversation_state'] = 'awaiting_recipient'
            session['transfer_details'] = {}
            reply = random.choice(responses_dict.get(predicted_intent, ["💸 Who should I send money to?"]))
        else:
            reply = random.choice(responses_dict.get(predicted_intent, ["I don't have a response yet."]))
    else:
        predicted_intent = "out_of_scope"
        reply = random.choice(responses_dict.get('out_of_scope', ["I can only assist with banking questions."]))

    entities = [(ent.text, ent.label_) for ent in getattr(doc, "ents", [])]
    save_log(message, predicted_intent, entities, reply)
    return jsonify({"reply": reply, "intent": predicted_intent})

# -------------------------
# Run
# -------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
