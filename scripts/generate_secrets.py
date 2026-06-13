#!/usr/bin/env python3
"""
GameHub Production Cryptographic Secret Generation Utility
Generates high-entropy 32-character hex secret tokens to replace development placeholders.
"""
import os
import secrets
import sys

def main():
    prod_env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env.prod"))
    
    if not os.path.exists(prod_env_path):
        print(f"❌ Error: .env.prod file not found at {prod_env_path}", file=sys.stderr)
        sys.exit(1)
        
    # Generate 16 bytes = 32 hex character token
    secure_token = secrets.token_hex(16)
    
    with open(prod_env_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    modified = False
    new_lines = []
    
    for line in lines:
        if line.startswith("INTERNAL_API_SECRET_TOKEN="):
            current_val = line.split("=", 1)[1].strip()
            if current_val == "CHANGE_ME_IN_PRODUCTION" or not current_val:
                line = f"INTERNAL_API_SECRET_TOKEN={secure_token}\n"
                modified = True
        new_lines.append(line)
        
    if modified:
        with open(prod_env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        print("✅ Successfully generated secure tokens and updated .env.prod!")
        print(f"  - Generated INTERNAL_API_SECRET_TOKEN: {secure_token}")
    else:
        print("ℹ️ No placeholders or empty fields found for INTERNAL_API_SECRET_TOKEN in .env.prod.")

if __name__ == "__main__":
    main()
