# Chatbot knowledge files

Every `## ` section in the other `.md` files in this folder becomes one card in the
chatbot's knowledge base (`scripts/build_kb.py`). Keep sections short and factual.
Do not write model scores or counts here: those come from the real output files
(fusion metrics, XAI explanations, the manifest) so they never go stale.
