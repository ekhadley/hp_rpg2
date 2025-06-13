import os
import json
import anthropic
from flask_socketio import SocketIO

from utils import *
import model_tools
from model_tools import Toolbox
from callbacks import CallbackHandler, TerminalPrinter

class Narrator:
    def __init__(
            self,
            model_name: str,
            system_prompt: str,
            callback_handler: CallbackHandler,
            toolbox: Toolbox,
        ):
        self.model_name = model_name
        self.tb = toolbox
        self.client = anthropic.Anthropic()
        self.messages: list[dict] = []
        self.max_tokens = 4096#16384
        self.system_prompt = system_prompt
        self.system = [
            {
                "text": system_prompt,
                "type": "text",
                "cache_control": {"type": "ephemeral"},
            },
        ]
        self.cb = callback_handler

    def save(self, path: str) -> None:
        if not os.path.exists(path):
            with open(path, "w+") as f:
                json.dump({"messages": self.messages}, f, indent=4)
        else:
            with open(path, "r+") as f:
                data = json.load(f)
                data["messages"] = self.messages
                f.seek(0)
                json.dump(data, f, indent=4)
    
    def load(self, path: str) -> list[dict] | None:
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
                if "messages" in data:
                    self.messages = data["messages"]
                    return self.messages
        return None

    def addUserMessage(self, content) -> None:
        self.messages.append({
            "role": "user",
            "content": content,
        })
    def addAssistantMessage(self, content) -> None:
        self.messages.append({
            "role": "assistant",
            "content": content,
        })
    
    def getStream(self):
        return self.client.messages.stream(
                model=self.model_name,
                system=self.system,
                tools=self.tb.schemas,
                messages=self.messages,
                max_tokens=self.max_tokens,
                #thinking={
                    #"type": "enabled",
                    #"budget_tokens": 10_000
                #},
            )
    
    def run(self) -> None: 
        with self.getStream() as stream:
            currently_outputting_text = False
            for event in stream:
                print(event)
                if event.type == "text":
                    if debug() and not currently_outputting_text:
                        print(yellow, "Assistant producing text. . .", endc)
                        currently_outputting_text = True
                    self.cb.text_output(text=event.text)
                elif event.type == "content_block_start" and event.content_block.type == "tool_use":
                    if debug(): print(pink, f"tool call started: {event.content_block.name}", endc)
                    self.cb.tool_request(name=event.content_block.name, inputs={})
                elif event.type == "message_stop":
                    message = event.message
                    content = [content.to_dict() for content in message.content]
                    self.addAssistantMessage(content)
                    if message.stop_reason == "tool_use":
                        tool_names, tool_inputss, tool_results = [], [], []
                        for block in message.content:
                            if block.type == "tool_use":
                                tool_name = block.name
                                tool_names.append(tool_name)
                                tool_inputs = block.input
                                tool_inputss.append(tool_inputs)
                                tool_result = self.tb.getToolResult(tool_name, tool_inputs)
                                tool_call_id = block.id
                                tool_results.append({
                                    "type": "tool_result",
                                    "tool_use_id": tool_call_id,
                                    "content": tool_result
                                })
                        if debug(): print(pink, f"tool call completed: {tool_name}({tool_inputs}) with result: {truncateForDebug(tool_result)}", endc)
                        self.cb.tool_submit(names=tool_names, inputs=tool_inputss, results=[r['content'] for r in tool_results])
                        self.addUserMessage(tool_results)
                        self.run()
                        return
                elif debug() and event.type != "content_block_delta":
                    if currently_outputting_text:
                        print(yellow, "\nAssistant finished producing text.", endc)
                        currently_outputting_text = False
        self.cb.turn_end()



if __name__ == "__main__":
    basic_tb = Toolbox([ # demo
        model_tools.list_directory_tool_handler,
        model_tools.read_file_tool_handler,
        model_tools.random_number_tool_handler
    ])
    asst = Narrator(
        model_name = "claude-3-haiku-20240307",
        toolbox = basic_tb,
        system_prompt = "You are a helpful assistant that can use tools.",
        callback_handler = TerminalPrinter()
    )

    asst.addUserMessage("Hello assistant. Can you generate a random number from 1-10 and add to it the number of files in the current directory?")
    #asst.addUserMessage("Hello assistant. How many files are in the current directory?")
    #asst.addUserMessage("Hello assistant. Can you describe the contents of `utils.py`?")
    #asst.addUserMessage("Hello assistant. How are you?")
    asst.run()

