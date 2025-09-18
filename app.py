# app.py (Final, Complete, and Fixed Version)

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from datetime import datetime
import spacy
import os
import csv
import random

app = Flask(__name__)
app.secret_key = "srt_bank_secret_key"

# --- Part 1: Load the AI Brain and the Chatbot's Responses ---
# This happens only once when the application starts.
try:
    nlp_model = spacy.load("bank_nlu_model")
    print("✅ NLU model loaded successfully.")
except IOError:
    nlp_model = None
    print("❌ Error: Could not find 'bank_nlu_model'. Please run train.py first.")

# Load all possible chatbot responses from the CSV into a dictionary.
# This makes the bot's replies easy to manage.
responses_dict = {}
try:
    with open("training_and_responses.csv", 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        next(reader) # Skip the header row
        for row in reader:
            if len(row) >= 4:
                intent = row[1]
                response = row[2]
                if intent not in responses_dict:
                    responses_dict[intent] = []
                if response: # Only add responses that are not empty
                    responses_dict[intent].append(response)
    print("✅ Chatbot responses loaded from CSV.")
except FileNotFoundError:
    print("❌ Error: 'training_and_responses.csv' not found.")
    responses_dict = {}

# --- Part 2: Your Dummy Data and Helper Functions ---
# This data simulates a real bank database for the project.
users = {"teja": "srt123", "sri": "bank123"}
account_profile = { "name": "Teja", "number": "96182240", "type": "Savings", "balance": 75000.00 }
transactions = [
    {"date": "2025-08-20", "desc": "Zomato Order", "amount": -450.00},
    {"date": "2025-08-18", "desc": "Amazon Purchase", "amount": -2999.00},
    {"date": "2025-08-15", "desc": "Flipkart Refund", "amount": 1500.00},
    {"date": "2025-08-10", "desc": "Rent Payment", "amount": -15000.00},
]
loans_catalog = [ {"type": "Personal Loan", "rate": "11.25% p.a."}, {"type": "Home Loan", "rate": "8.50% p.a."} ]
cards_info = { "debit": {"status": "Active", "last4": "4321"}, "credit": {"status": "Active", "last4": "9988"} }
branches = [
    {"city": "Hyderabad", "name": "SRT Bank - HiTech City", "address": "Plot 21, Cyber Towers", "ifsc": "SRTB0000123"},
    {"city": "Bengaluru", "name": "SRT Bank - Indiranagar", "address": "100ft Rd, HAL 2nd Stage", "ifsc": "SRTB0000456"},
    {"city": "Mumbai", "name": "SRT Bank - BKC", "address": "G Block, Bandra Kurla Complex", "ifsc": "SRTB0000789"},
]

# This helper function checks if a user is currently logged in.
def logged_in():
    return "user" in session

# --- Part 3: All Your Page Routes (The Website Map) ---
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "").strip()
        if u in users and users[u] == p:
            session["user"] = u
            return redirect(url_for("dashboard"))
        flash("Invalid credentials. Try again.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear() # Clear all session data, including conversations
    return redirect(url_for("home"))

@app.route("/dashboard")
def dashboard():
    if not logged_in(): return redirect(url_for("login"))
    return render_template("dashboard.html", user=session["user"], cards=cards_info, txns=transactions)

# --- These routes make the dashboard cards work ---
@app.route("/balance")
def balance():
    if not logged_in(): return redirect(url_for("login"))
    return render_template("balance.html", profile=account_profile)

@app.route("/transactions")
def transactions_page():
    if not logged_in(): return redirect(url_for("login"))
    txns_with_balance = []
    running_balance = account_profile["balance"]
    temp_txns = transactions[:]
    for t in reversed(temp_txns):
        txn = t.copy()
        txn['balance'] = running_balance
        running_balance -= t['amount']
        txns_with_balance.append(txn)
    txns_with_balance.reverse()
    return render_template("transactions.html", txns=txns_with_balance)

@app.route("/loans")
def loans():
    if not logged_in(): return redirect(url_for("login"))
    return render_template("loans.html", loans=loans_catalog)

@app.route("/cards")
def cards():
    if not logged_in(): return redirect(url_for("login"))
    return render_template("cards.html", cards=cards_info)

@app.route("/branches")
def branches_list():
    if not logged_in(): return redirect(url_for("login"))
    return render_template("branches.html", branches=branches)

@app.route("/chatbot")
def chatbot():
    if not logged_in(): return redirect(url_for("login"))
    return render_template("chatbot.html", now=datetime.now().strftime("%d %b %Y, %I:%M %p"))
# --- END OF PAGE ROUTES ---


# --- Part 4: The Final, Upgraded Chatbot API ---
@app.route("/api/chat", methods=["POST"])
def api_chat():
    if not "user" in session:
        return jsonify({"reply": "Authentication error.", "intent": "error"})

    data = request.get_json() or {}
    message = (data.get("message") or "").strip()
    
    # --- Part A: Handle multi-step conversations ---
    # This block runs only if the bot is already in a conversation
    if 'conversation_state' in session:
        state = session.get('conversation_state')
        doc = nlp_model(message)
        
        # --- Balance Check Flow ---
        if state == 'awaiting_account_number':
            acc_num = next((ent.text for ent in doc.ents if ent.label_ == 'ACCOUNT_NUMBER'), None)
            if acc_num and acc_num == account_profile['number']:
                reply = f"Thank you for verifying. Your current balance is ₹{account_profile['balance']:.2f}. Is there anything else I can help with?"
                session.pop('conversation_state', None) # End conversation
            else:
                reply = "That account number doesn't seem to match our records. Please try again."
            return jsonify({"reply": reply, "intent": "slot_filling"})

        # --- Send Money Flow ---
        transfer_details = session.get('transfer_details', {})
        if state == 'awaiting_recipient':
            recipient = next((ent.text.title() for ent in doc.ents if ent.label_ == 'PERSON'), None)
            if recipient:
                transfer_details['recipient'] = recipient
                session['transfer_details'] = transfer_details
                session['conversation_state'] = 'awaiting_amount'
                reply = f"OK. How much would you like to send to {recipient}?"
            else:
                reply = "Sorry, I didn't catch a name. Who do you want to send money to?"
            return jsonify({"reply": reply, "intent": "slot_filling"})

        elif state == 'awaiting_amount':
            amount = next((''.join(filter(str.isdigit, ent.text)) for ent in doc.ents if ent.label_ == 'MONEY'), None)
            if amount:
                transfer_details['amount'] = amount
                session['transfer_details'] = transfer_details
                session['conversation_state'] = 'awaiting_confirmation'
                reply = f"Please confirm: send ₹{amount} to {transfer_details['recipient']}? (yes/no)"
            else:
                reply = "Sorry, I didn't understand the amount. How much?"
            return jsonify({"reply": reply, "intent": "slot_filling"})

        elif state == 'awaiting_confirmation':
            if 'yes' in message.lower():
                amount_val = float(transfer_details['amount'])
                if account_profile['balance'] >= amount_val:
                    account_profile['balance'] -= amount_val
                    new_txn = {"date": datetime.now().strftime("%Y-%m-%d"), "desc": f"Transfer to {transfer_details['recipient']}", "amount": -amount_val}
                    transactions.insert(0, new_txn)
                    reply = f"✅ Success! Sent ₹{amount_val} to {transfer_details['recipient']}. Your new balance is ₹{account_profile['balance']:.2f}."
                else:
                    reply = "Transaction failed: insufficient balance."
            else:
                reply = "OK, I've cancelled the transaction."
            
            session.pop('conversation_state', None)
            session.pop('transfer_details', None)
            return jsonify({"reply": reply, "intent": "slot_filling"})
    
    # --- Part B: Handle new conversations ---
    if not nlp_model: return jsonify({"reply": "Sorry, AI model not available.", "intent": "error"})

    doc = nlp_model(message)
    if not doc.cats:
        return jsonify({"reply": "I'm sorry, I'm not sure how to help with that.", "intent": "n/a"})
        
    predicted_intent = max(doc.cats, key=doc.cats.get)
    confidence = doc.cats[predicted_intent]

    if confidence > 0.65:
        # Start a conversation if the intent requires it
        if predicted_intent == 'check_balance':
            session['conversation_state'] = 'awaiting_account_number'
        elif predicted_intent == 'transfer_money':
            session['conversation_state'] = 'awaiting_recipient'
            session['transfer_details'] = {} # Initialize empty details
        
        if predicted_intent in responses_dict:
            reply = random.choice(responses_dict[predicted_intent])
        else:
            reply = "I don't have a specific response for that yet."
    else:
        predicted_intent = 'out_of_scope' # Re-classify as out_of_scope
        reply = random.choice(responses_dict.get('out_of_scope', ["I can only assist with banking questions."]))

    return jsonify({"reply": reply, "intent": predicted_intent})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

