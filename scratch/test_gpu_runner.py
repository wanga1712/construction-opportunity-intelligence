import os
from src.services.ai_client import generate

print("Calling Qwen 2.5:7b via shared ai_client...")
response = generate("Назови три типа гидроизоляции одним предложением.", model="qwen2.5:7b")
print("RESPONSE:", response)

print("\nChecking ollama ps:")
os.system("ollama ps")

print("\nChecking nvidia-smi:")
os.system("nvidia-smi")
