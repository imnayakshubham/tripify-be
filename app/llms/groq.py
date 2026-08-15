"""Chat model factory. Swap the provider here and every agent follows."""

from langchain_groq import ChatGroq

from app.configs import MODEL_NAME


def get_llm() -> ChatGroq:
    return ChatGroq(model=MODEL_NAME)
