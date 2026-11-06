"""SDK hello-world shape at 1.58.1; no custom agent loop or Orca identity."""

import json
import os
import sys
from pathlib import Path

from openhands.sdk import LLM, Agent, Conversation, Tool
from openhands.sdk.context import AgentContext
from openhands.sdk.conversation import get_agent_final_response
from openhands.sdk.security import NeverConfirm
from openhands.tools.file_editor import FileEditorTool
from openhands.tools.task_tracker import TaskTrackerTool
from openhands.tools.terminal import TerminalTool

if len(sys.argv) != 2:
    raise SystemExit(
        "usage: openhands-sdk 'task message' (plain terminal; no native Orca agent ID)"
    )

settings = json.loads((Path(__file__).parent / "profiles/openhands.json").read_text())
llm = LLM(**settings, api_key=os.environ["OMNIROUTE_API_KEY"], log_completions=False)
agent = Agent(
    llm=llm,
    agent_context=AgentContext(load_project_skills=True),
    tools=[
        Tool(name=TerminalTool.name),
        Tool(name=FileEditorTool.name),
        Tool(name=TaskTrackerTool.name),
    ],
)
conversation = Conversation(agent=agent, workspace=str(Path.cwd()), persistence_dir=None)
try:
    conversation.set_confirmation_policy(NeverConfirm())
    conversation.send_message(sys.argv[1])
    conversation.run()
    print(get_agent_final_response(conversation.state.events))
finally:
    conversation.close()
