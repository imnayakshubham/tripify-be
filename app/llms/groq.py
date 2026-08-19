"""Chat model factory. Swap the provider here and every agent follows."""

from langchain_groq import ChatGroq

from app.configs import MAX_OUTPUT_TOKENS, MODEL_NAME, REASONING_EFFORT


def get_llm() -> ChatGroq:
    return ChatGroq(
        model=MODEL_NAME,
        max_tokens=MAX_OUTPUT_TOKENS,
        reasoning_effort=REASONING_EFFORT,
    )
