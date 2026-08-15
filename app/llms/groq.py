"""Chat model factory. Swap the provider here and every agent follows."""

from langchain_groq import ChatGroq

from app.configs import GROQ_MODEL_NAME


def get_llm() -> ChatGroq:
    return ChatGroq(model=GROQ_MODEL_NAME)
