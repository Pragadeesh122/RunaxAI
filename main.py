import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from functions.tool_router import execute_tool_call
from utils.summarizer import summarize_messages
from utils.streaming import stream_response, ToolCallProxy
from memory import get_user_memory, extract_and_save_memories
from prompts import ORCHESTRATOR
from llm.response_utils import usage_tokens

logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
logger = logging.getLogger("orchestrator")

MAX_PROMPT_TOKENS = 10000
MAX_TOOL_CALLS = 3


def main():
    print("Hello from RunaxAI!")
    user_id = os.getenv("LOCAL_USER_ID", "").strip()

    # Load semantic memory into system prompt
    system_prompt = ORCHESTRATOR
    user_memory = get_user_memory(user_id)
    if user_memory:
        system_prompt += f"\n\nKnown facts about the user:\n{user_memory}"
        logger.info("loaded user memory")

    messages = [{"role": "system", "content": system_prompt}]

    while True:
        content = input("")

        if content == "exit":
            # Extract and save memories before exiting
            if user_id:
                logger.info("extracting memories from conversation")
                extract_and_save_memories(messages, user_id)
            with open("results.json", "w") as file:
                json.dump(messages, file, indent=2)
            break

        messages.append({"role": "user", "content": content})
        tool_call_count = 0
        prompt_tokens = 0
        try:
            while True:
                content, tool_calls, usage = stream_response(messages)
                if usage:
                    prompt_tokens, _ = usage_tokens(usage)

                if not tool_calls or tool_call_count >= MAX_TOOL_CALLS:
                    if tool_call_count >= MAX_TOOL_CALLS:
                        logger.info(f"max tool calls reached ({MAX_TOOL_CALLS})")
                        stop_msg = {
                            "role": "system",
                            "content": "You have reached the maximum number of tool calls. Do NOT attempt any more tool calls. Respond with the best answer you can based on the information you have gathered so far.",
                        }
                        messages.append(stop_msg)
                        content, _, usage = stream_response(messages, use_tools=False)
                        messages.remove(stop_msg)
                        if usage:
                            prompt_tokens, _ = usage_tokens(usage)
                    logger.info("response: text")
                    break

                tool_call_count += 1
                tool_names = [tc["function"]["name"] for tc in tool_calls]
                logger.info(
                    f"tool_calls: {tool_names} ({tool_call_count}/{MAX_TOOL_CALLS})"
                )
                messages.append(
                    {"role": "assistant", "tool_calls": tool_calls, "content": None}
                )
                proxies = [ToolCallProxy(tc) for tc in tool_calls]
                with ThreadPoolExecutor() as executor:
                    futures = {
                        executor.submit(execute_tool_call, p): p for p in proxies
                    }
                    results = []
                    for future in as_completed(futures):
                        results.append((futures[future], future.result()))
                    # Preserve original tool call order
                    order = {p.id: i for i, p in enumerate(proxies)}
                    results.sort(key=lambda r: order[r[0].id])
                    for _, result in results:
                        messages.append(result[0])
        except KeyboardInterrupt:
            print("\nInterrupted.")
            break
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            print(f"Something went wrong: {e}")
            messages.pop()  # remove the failed user message
            continue

        messages.append({"role": "assistant", "content": content})

        if prompt_tokens > MAX_PROMPT_TOKENS:
            messages = summarize_messages(messages)

        print("----" * 30)


if __name__ == "__main__":
    main()
