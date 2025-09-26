import sqlite3
import pandas as pd
import matplotlib.pyplot as plt

# Connect to your logs database
conn = sqlite3.connect("logs.db")

# Load logs into DataFrame
df = pd.read_sql_query("SELECT * FROM logs", conn)

# ---- Intent Distribution ----
intent_counts = df["intent"].value_counts()

plt.figure(figsize=(6,6))
intent_counts.plot(kind="pie", autopct='%1.1f%%')
plt.title("Intent Distribution")
plt.ylabel("")
plt.savefig("intent_distribution.png")
plt.close()

# ---- Top User Queries ----
query_counts = df["user_message"].value_counts().head(10)

plt.figure(figsize=(8,5))
query_counts.plot(kind="bar")
plt.title("Top 10 User Queries")
plt.xlabel("Query")
plt.ylabel("Count")
plt.xticks(rotation=45, ha="right")
plt.tight_layout()
plt.savefig("top_user_queries.png")
plt.close()

print("✅ Analytics generated: intent_distribution.png, top_user_queries.png")
