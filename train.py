import spacy
from spacy.training.example import Example
import random
import os
import csv
import shutil

# --- Part 1: Load all training data from the CSV file ---
def load_training_data(filepath="training_and_responses.csv"):
    intent_examples = []
    entity_examples = []
    intents = set()
    
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        next(reader)  # Skip the header row
        for i, row in enumerate(reader):
            if len(row) == 4:
                text, intent, response, entities_str = row
                intent_examples.append((text, intent))
                intents.add(intent)
                if entities_str:
                    entities = []
                    parts = entities_str.split('|')
                    for part in parts:
                        try:
                            label, value = part.split(':', 1)
                            start = text.lower().find(value.lower())
                            if start != -1:
                                end = start + len(value)
                                entities.append((start, end, label))
                        except ValueError:
                            pass # Silently ignore malformed entities
                    if entities:
                        entity_examples.append((text, {"entities": entities}))
            else:
                print(f"Warning: Skipping malformed row {i+2} in CSV.")

    return intent_examples, entity_examples, list(intents)

# --- Part 2: The Main Training Process ---
output_dir = "bank_nlu_model"
if os.path.exists(output_dir):
    shutil.rmtree(output_dir)
    print("Old model removed. Starting fresh training.")

INTENT_EXAMPLES, ENTITY_EXAMPLES, ALL_INTENTS = load_training_data()
print(f"Loaded {len(INTENT_EXAMPLES)} intent examples and {len(ENTITY_EXAMPLES)} entity examples.")

# --- THIS IS THE MAJOR UPGRADE ---
# Load a pre-trained English model instead of a blank one
nlp = spacy.load("en_core_web_sm")
print("Loaded pre-trained 'en_core_web_sm' model.")
# ---------------------------------

# Add the intent classifier (textcat) if it doesn't exist
if "textcat" not in nlp.pipe_names:
    textcat = nlp.add_pipe("textcat", last=True)
else:
    textcat = nlp.get_pipe("textcat")

for intent in ALL_INTENTS:
    textcat.add_label(intent)

# Add the entity recognizer (ner) if it doesn't exist
if "ner" not in nlp.pipe_names:
    ner = nlp.add_pipe("ner", last=True)
else:
    ner = nlp.get_pipe("ner")
    
# Add our custom entity labels.
ner.add_label("MONEY")
ner.add_label("ACCOUNT_NUMBER")
# NOTE: "PERSON" is already known by the pre-trained model, but we add it to be safe
ner.add_label("PERSON")

# --- This is the corrected training loop for fine-tuning ---
print("\n--- Starting Fine-Tuning ---")
# Disable other pipes during training for efficiency and to prevent conflicts
pipe_exceptions = ["textcat", "ner"]
unaffected_pipes = [pipe for pipe in nlp.pipe_names if pipe not in pipe_exceptions]

with nlp.disable_pipes(*unaffected_pipes):
    # Use nlp.begin_training() to initialize ONLY the new components
    optimizer = nlp.begin_training()
    for i in range(20):
        random.shuffle(INTENT_EXAMPLES)
        losses = {}

        # Fine-tune intents
        for text, intent in INTENT_EXAMPLES:
            doc = nlp.make_doc(text)
            cats = {k: 0.0 for k in ALL_INTENTS}
            cats[intent] = 1.0
            example = Example.from_dict(doc, {"cats": cats})
            nlp.update([example], sgd=optimizer, losses=losses)

        # Fine-tune entities
        for text, annotations in ENTITY_EXAMPLES:
            doc = nlp.make_doc(text)
            example = Example.from_dict(doc, annotations)
            nlp.update([example], sgd=optimizer, losses=losses)

        print(f"Epoch {i+1}, Losses: {losses}")
# --- End of corrected loop ---


# Save the final, fine-tuned model
nlp.to_disk(output_dir)
print(f"\n✅ Fine-tuned AI model saved to '{output_dir}'.")