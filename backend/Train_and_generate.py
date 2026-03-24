import os
import pickle
from transformers import AutoTokenizer, AutoModelForCausalLM, Trainer, TrainingArguments
from datasets import Dataset

# Paths to the extracted Python and Go dataset directories
python_dir = 'C:/HP/Projects/Hackathon/code_search_net/python'
go_dir = 'C:/HP/Projects/Hackathon/code_search_net/go'

# Function to load and preprocess a .pkl file
print("Loading and preprocessing data...")
def load_pkl_data(directory):
    code_data = []
    # List all .pkl files in the directory
    for filename in os.listdir(directory):
        if filename.endswith('.pkl'):
            pkl_path = os.path.join(directory, filename)
            with open(pkl_path, 'rb') as f:
                data = pickle.load(f)
                code_data.extend(data)
    return code_data

# Load Python and Go datasets
python_data = load_pkl_data(python_dir)
go_data = load_pkl_data(go_dir)
print("Data loaded successfully.")
# Combine both datasets (Python + Go)
all_data = python_data + go_data

# Check if the data has been loaded correctly
print(f"Loaded {len(all_data)} code samples from Python and Go datasets.")

print(all_data[0])

# Extract code and docstring (assuming data contains 'code' and 'docstring' keys)
codes = [entry['function'] for entry in all_data]
docstrings = [entry['docstring'] for entry in all_data]

print(f"Sample code: {codes[0]}")
# Initialize the tokenizer for the model
tokenizer = AutoTokenizer.from_pretrained('bigcode/starcoderbase-3b')
print("Tokenizer initialized successfully.")

# Tokenize the code and docstrings
def preprocess_function(code, docstring):
    inputs = tokenizer(code, truncation=True, padding=True, max_length=512)
    labels = tokenizer(docstring, truncation=True, padding=True, max_length=512)
    inputs["labels"] = labels["input_ids"]
    return inputs

# Preprocess the data
tokenized_data = [preprocess_function(code, docstring) for code, docstring in zip(codes, docstrings)]
print("Data preprocessed successfully.")
# Check the tokenized data format
print(f"Tokenized the first sample: {tokenized_data[0]}")

# Convert the tokenized data into a format suitable for Hugging Face Dataset
dataset = Dataset.from_dict({
    'input_ids': [item['input_ids'] for item in tokenized_data],
    'attention_mask': [item['attention_mask'] for item in tokenized_data],
    'labels': [item['labels'] for item in tokenized_data],
})
print("Dataset created successfully.")
# Split the dataset into train and validation (80% train, 20% validation)
train_dataset = dataset.shuffle(seed=42).select(range(int(0.8 * len(dataset))))
eval_dataset = dataset.shuffle(seed=42).select(range(int(0.8 * len(dataset)), len(dataset)))

# Load the pre-trained model for causal language modeling
model = AutoModelForCausalLM.from_pretrained('bigcode/starcoderbase-3b')
print("Model loaded successfully.")
# Define training arguments
training_args = TrainingArguments(
    output_dir="./results",         # Output directory for model checkpoints
    num_train_epochs=3,             # Number of training epochs
    per_device_train_batch_size=4,  # Batch size per device during training
    per_device_eval_batch_size=8,   # Batch size per device during evaluation
    save_steps=2000,                # Save checkpoint every 2000 steps
    logging_steps=200,              # Log every 200 steps
    evaluation_strategy="epoch",    # Evaluate at the end of each epoch
    load_best_model_at_end=True,    # Load the best model based on evaluation
)
print("Training arguments defined successfully.")
# Initialize the Trainer
trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=train_dataset,
    eval_dataset=eval_dataset,
)
print("training started")
# Train the model
trainer.train()
print("Training completed successfully.")
# Save the fine-tuned model
trainer.save_model("fine_tuned_starcoderbase-3b")

# Optionally, save the tokenizer as well
tokenizer.save_pretrained("fine_tuned_starcoderbase-3b-tokenizer")
