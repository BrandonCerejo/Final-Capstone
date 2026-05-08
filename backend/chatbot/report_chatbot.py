import json
import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

API_KEY    = os.environ.get("GEMINI_API_KEY")
MODEL_NAME = "gemini-3.1-flash-lite-preview"

SYSTEM_PROMPT = """You are a helpful medical assistant embedded in a chest X-ray 
analysis application. The user has just received an AI-generated radiology report 
and may have questions about it.

Your rules — follow them strictly:
- Answer questions ONLY based on the radiology report provided in each message.
- Do NOT use any external medical knowledge beyond what is stated in the report.
- If a question cannot be answered from the report, say clearly:
  "I can only answer questions based on your report. That information isn't 
   included in your current report."
- Do NOT provide treatment advice, medication recommendations, or diagnoses 
  beyond what the report already states.
- Always remind the user to consult a qualified radiologist or physician for 
  clinical decisions.
- Keep answers clear, concise, and in plain English — avoid unnecessary jargon.
- If the user asks something unrelated to radiology or their report (e.g. 
  cooking, sports, general chat), politely decline and redirect them to ask 
  about their report.
- Maintain a warm, reassuring tone — the user may be anxious about their results.

  FORMATTING RULES (strictly follow these):
- When using bullet points, start each bullet with a plain dash and a space: "- item"
- Do NOT use markdown bold (**text**) anywhere in your response.
- Do NOT use markdown headers (##, ###) in your response.
- Use plain text labels followed by a colon for section headings if needed,
  e.g. "Common symptoms:" not "**Common symptoms:**"
- Use short paragraphs or dashed bullet lists to make answers easy to read."""


def build_prompt(report: dict, question: str) -> str:
    report_str = json.dumps(report, indent=2)
    return f"""Here is the patient's radiology report:

{report_str}

---

The patient asks: {question}

Answer based strictly on the report above."""


def ask_report_chatbot(report: dict, question: str, history: list[dict]) -> str:
    if not API_KEY:
        raise ValueError("GEMINI_API_KEY not set in environment / .env file.")

    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel(
        model_name=MODEL_NAME,
        system_instruction=SYSTEM_PROMPT,
        generation_config=genai.GenerationConfig(
            temperature=0.1,  
            top_p=0.9,
            max_output_tokens=1024,
        ),
    )

    chat = model.start_chat(history=history)
    user_message = build_prompt(report, question)
    response = chat.send_message(user_message)
    return response.text