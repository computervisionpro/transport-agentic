
from dotenv import load_dotenv
import asyncio
import sys
from pathlib import Path

from agents import Agent, Runner, set_tracing_disabled
from agents.mcp import MCPServerStdio
from ops_logic import redact_text
from agents.items import ToolCallItem, ToolCallOutputItem

BASE_DIR = Path(__file__).resolve().parent
SERVER_PATH = BASE_DIR / "server.py"
load_dotenv(BASE_DIR / ".env")
set_tracing_disabled(True)


# asynchronous function call
async def main():
    question = " ".join(sys.argv[1:]) or (
                "Across all dates in trips.csv, which three routes had the worst "
                "average delays? Include median delay, on-time percentage, "
                "excluded records, and timetable limitations.")

    print("\nQ:", redact_text(question))
    print("\n\n Keep all the csv files closed before running the program")

    # start server.py and establishes an MCP connection with agent, then close it
    async with MCPServerStdio(
        name="Cityflo Operations MCP",
        params={"command": sys.executable, 
                "args": [str(SERVER_PATH)],
                }) as mcp_server:
          
        agent = Agent(
            name="Cityflo Ops Analyst",
            instructions="""
            You are an operations analyst.

            Answer in simple, plain English. Lead with the direct answer,
            then give a short bullet list with the most useful numbers.

            Use only facts returned by the MCP tools. Do not invent data.
            For route rankings, include the route, average delay, median
            delay, and on-time percentage. Say clearly when no usable trips
            exist for the requested date.

            Mention a data-quality or REC-114 limitation only when it could
            change the answer. Keep caveats to one short sentence. Also mention that 
            the threshold for on time is taken as 4 minutes or less, based on data provided.
            Mention that few R-35 trips are too delayed, which could be due to incorrect GPS data, 
            when R-35 is mentioned in the user's question or the answer.

            Never include rider phone numbers or verbatim complaint text.
            Refer to complaints only by ticket ID and category, if provided.

            Also, if required, mention a few trip ids as well, if the user asks for more info.
            """,
            model="gpt-5.6-luna",
            model_settings={
                            "reasoning": {"effort": "low"},
                            "verbosity": "medium",
                            },
            mcp_servers=[mcp_server],
                        )
        # print(agent.model)


        # runs the agent
        result = await Runner.run(agent, question)

        # tracing agent
        print("\n--- AGENT EXECUTION TRACE ---")
        tool_calls = [
                        item.tool_name
                        for item in result.new_items
                        if item.type == "tool_call_item"
                        ]
        print("Tools called:", tool_calls or "No tools called")

        print("\n\n---- Operations answer ----\n")
        print(redact_text(result.final_output))


if __name__ == "__main__":
    asyncio.run(main())
    
