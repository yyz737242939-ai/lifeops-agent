import sys

from app.agents import Agent
from app.runtime.conversation_logger import start_logging_session


def _configure_terminal_encoding() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def main() -> None:
    _configure_terminal_encoding()
    print("=== LifeOps Agent ===")
    start_logging_session()

    agent = Agent()

    while True:
        user_input = input("\nYou: ")

        if user_input.lower() in ["exit", "quit"]:
            print("Bye!")
            break

        answer = agent.chat(user_input)

        print(f"\nAgent: {answer}")


if __name__ == "__main__":
    main()
