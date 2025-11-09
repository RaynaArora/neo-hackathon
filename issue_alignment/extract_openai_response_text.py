
def extract_response_text(response) -> str:
    """Return the first text segment from an OpenAI response object."""
    # New style: response.output -> list of messages -> list of content blocks
    for message in getattr(response, "output", []) or []:
        for block in getattr(message, "content", []) or []:
            text = getattr(block, "text", None)
            if text:
                return text

    # Legacy style: response.content may be list-like or object with .text
    content = getattr(response, "content", None)
    if isinstance(content, (list, tuple)):
        for block in content:
            text = getattr(block, "text", None)
            if text:
                return text
    text = getattr(content, "text", None)
    if text:
        return text

    return ""