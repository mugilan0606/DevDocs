from transformers import AutoTokenizer, AutoModelForCausalLM, TrainingArguments, Trainer
import os
import torch
import tensorflow as tf

def generate_comment(code_snippet):
    print("Loading saved model for inference...")
    tf_model = tf.keras.models.load_model("starcoder_finetuned.h5")
    
    # FIXED: Define tokenizer before using it
    tokenizer = AutoTokenizer.from_pretrained("bigcode/starcoderbase-3b")

    prompt = f"### Code:\n{code_snippet}\n\n### Comment:\n"
    inputs = tokenizer(prompt, return_tensors="tf")

    output = tf_model.generate(input_ids=inputs["input_ids"], max_length=128)
    return tokenizer.decode(output[0], skip_special_tokens=True)

# ✅ Step 6: Test on Sample Code
sample_code = """
def quicksort(arr):
    if len(arr) <= 1:
        return arr
    pivot = arr[len(arr) // 2]
    left = [x for x in arr if x < pivot]
    middle = [x for x in arr if x == pivot]
    right = [x for x in arr if x > pivot]
    return quicksort(left) + middle + quicksort(right)
"""

print("\n🔹 Generated Comment:")
print(generate_comment(sample_code))