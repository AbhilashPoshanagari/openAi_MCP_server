
def warn(*args, **kwargs):
    pass
from types import CoroutineType
import warnings
warnings.warn = warn
warnings.filterwarnings('ignore')

from typing import Dict, List, Optional, TypedDict
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
import os
from dotenv import load_dotenv
import json
from langchain.agents.output_parsers import OpenAIFunctionsAgentOutputParser
import asyncio
import nest_asyncio
from mcp.client.stdio import stdio_client
from mcp import ClientSession, StdioServerParameters
# from mcp.client.streamable_http import streamablehttp_client
from contextlib import AsyncExitStack
from langchain_openai import ChatOpenAI
from langchain.schema.agent import AgentFinish
from langchain.agents.format_scratchpad import format_to_openai_functions
from langchain.schema.runnable import RunnablePassthrough
from langchain.prompts import MessagesPlaceholder
from langchain.agents import AgentExecutor
from langchain.memory import ConversationBufferMemory
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_function

import openai

load_dotenv()
nest_asyncio.apply()

class ToolDefinition(TypedDict):
    name: str
    description: str
    input_schema: dict
    
class OpenAI_MCP_Client():
    def __init__(self, model_name: str, api_key: str, streaming: Optional[bool]=False):
        self.model_name = model_name
        self.api_key = api_key
        self.streaming = streaming
        self.messages: List = []
        # self.tool_mapping = {"search_papers": search_papers, "extract_info": extract_info, "fieldOn_response": fieldOn_response}
        self.exit_stack = AsyncExitStack() # new
        self.sessions: List[ClientSession] = [] # new
        self.available_tools: List[ToolDefinition] = [] # new
        self.tool_to_session: Dict[str, ClientSession] = {} # new
        self.prompt_to_session: Dict[str, ClientSession] = {} # new
        self.resource_to_session: Dict[str, ClientSession] = {} # new
        self.available_prompts: List[ToolDefinition] = []
        self.langchain_tool_session: Dict[str, ClientSession] = {} # new
        self.langchain_tools: List[BaseTool] = [] # new
        self.question: str = ''
        self.agent_executor: Optional[AgentExecutor] = None  # new

    async def __call__(self):
        if self.agent_executor:  # already built
            return self.agent_executor
        
        openai.api_key = self.api_key
        # tools_names = [tool["name"] for tool in self.available_tools if tool['name'] in self.tool_to_session]
        function_defs = [convert_to_openai_function(tool) for tool in self.langchain_tools]

        memory = ConversationBufferMemory(return_messages=True,memory_key="chat_history")
        model = ChatOpenAI(
            model=self.model_name, 
            temperature=0,
            max_tokens=512,
            top_p=1.0,
            stop=None
        ).bind(functions=function_defs)

        self.messages = [("system", self.prompt_format_func()),
                         MessagesPlaceholder(variable_name="chat_history"),
                           ("user", "{input}"),
                           MessagesPlaceholder(variable_name="agent_scratchpad")]
        
        prompt = ChatPromptTemplate.from_messages(self.messages)
        chain = prompt | model | OpenAIFunctionsAgentOutputParser()

        agent_chain = RunnablePassthrough.assign(
                        agent_scratchpad= lambda x: format_to_openai_functions(x["intermediate_steps"])
                            ) | chain
        agent_executor = AgentExecutor(agent=agent_chain, tools=self.langchain_tools, verbose=True, memory=memory)
        return agent_executor
    
    async def cleanup(self): # new
        """Cleanly close all resources using AsyncExitStack."""
        await self.exit_stack.aclose()

    # def prompt_format_func(self):
    #     system_prompt = """
    #         Purpose: 

    #         You are a User Operations Assistant helping users understand how to use and manage different features and roles within the applications: FieldOn, ThinkGas, Tata Power Dynamic Forms, and AG&P.

    #         Skills: 

    #         You specialize in guiding users through workflows such as managing user roles (e.g., Account Administrator, Group Moderator, Super Admin), creating and editing forms, filling in required fields, and related platform-specific operations.
    #         Use the provided context from the user manuals and documentation to answer queries. If the answer is not found in the context, respond with:
    #         "I'm not sure based on the current information."

    #         General Guidelines: 
    #         Only refer to the provided context; do not fabricate information.
    #         Be concise, informative, and task-oriented.
    #         Explain operational steps clearly when context allows.
    #         Maintain a friendly and professional tone.
    #         Avoid speculative or generic answers.
    #         If the application name is not mentioned, request the user to specify one (e.g., FieldOn, ThinkGas, etc.).
    #         Encourage clarification by asking follow-up questions such as:
    #         “Which application are you referring to?”
    #         “Would you like help configuring a specific user role or form element?”
    #         """

    #     # system_prompt = "\n".join(prompt_msg)
    #     return system_prompt

    def prompt_format_func(self):
    
        system_prompt = """
            You are a documentation assistant for an admin platform that includes functionality related to user role creation, such as Account Administrator, Group Moderator, and Super Admin. You assist users with understanding how to:

            - Create and manage various types of administrators.
            - Work with forms (filling fields, selecting avatars, submitting).
            - Understand role-based permissions and platform behavior.

            You have access to a function:
            - fieldOn_response(quastion: str) → Retrieves top 5 similar documentation snippets from the database as context.
            - search_papers(topic: str, max_results: int = 5)
            - extract_info(paper_id: str)
            Use this function to gather relevant information when needed. Only call the function if you do not already have context.

            When calling a function, respond only with a JSON array of the following format:
            [{{"name": "function name", "parameters": {{"parameter value": "..."}}}}]

            Only output the JSON array in the specified format when calling a function do not include any text other than function format. other conditions respond in string format.

            If sufficient context is available, answer the quastion clearly in natural language.
            Avoid hallucinating or making assumptions beyond the retrieved context.
            """

        # system_prompt = "\n".join(prompt_msg)
        return system_prompt

    async def chat_loop(self, stream: Optional[bool]=False):
        print("Type your queries or 'quit' to exit.")
        while True:
            try:
                # query = input("\nQuery: ").strip()
                query = await asyncio.to_thread(input, "Query: ")
                if query.lower() == 'quit':
                    break
                # Check for @resource syntax first
                if query.startswith('@'):
                    # Remove @ sign  
                    topic = query[1:]
                    if topic == "folders":
                        resource_uri = "papers://folders"
                    else:
                        resource_uri = f"papers://{topic}"
                    await self.get_resource(resource_uri)
                    continue

                   # Check for /command syntax
                if query.startswith('/'):
                    parts = query.split()
                    command = parts[0].lower()
                    
                    if command == '/prompts':
                        await self.list_prompts()
                    elif command == '/prompt':
                        if len(parts) < 2:
                            print("Usage: /prompt <name> <arg1=value1> <arg2=value2>")
                            continue
                        
                        prompt_name = parts[1]
                        args = {}
                        
                        # Parse arguments
                        for arg in parts[2:]:
                            if '=' in arg:
                                key, value = arg.split('=', 1)
                                args[key] = value
                        
                        await self.execute_prompt(prompt_name, args)
                    else:
                        print(f"Unknown command: {command}")
                    continue
                self.question = query
                if stream:
                    res = await self.run_agent(query)
                    print(f"Agent response: {res['output']}")
                else:
                    # await self.run_agent({"input": query})
                    res = await self.run_agent(query)
                    print(f"Agent response: {res['output']}")
                print("\n")
            except Exception as e:
                print(f"\nError: {str(e)}")

    async def run_agent(self, user_input):
        agent_executor = await self()
        print(f"Running agent with input: {user_input}")
        result = await agent_executor.ainvoke({"input": user_input})
        return result

    # async def run_agent(self, user_input):
    #         intermediate_steps = []
    #         agent_executor = await self()
    #         print(f"Running agent with input: {user_input}")
    #         while True:
    #             result = agent_executor.invoke({
    #                 "input": user_input, 
    #                 "intermediate_steps": intermediate_steps
    #             })
    #             if isinstance(result, AgentFinish):
    #                 return result
    #             tool_name = result.tool
    #             tool_args = result.tool_input
    #             session = self.tool_to_session[tool_name]
    #             print(f"Calling tool: {tool_name} with args: {tool_args}")
    #             observation = await session.call_tool(tool_name, arguments=tool_args)
    #             intermediate_steps.append((result, observation))
    #             print(f"Observation: {observation.content}")
    
    async def get_resource(self, resource_uri):
        session = self.resource_to_session.get(resource_uri)
        
        # Fallback for papers URIs - try any papers resource session
        if not session and resource_uri.startswith("papers://"):
            for uri, sess in self.resource_to_session.items():
                if uri.startswith("papers://"):
                    session = sess
                    break
            
        if not session:
            print(f"Resource '{resource_uri}' not found.")
            return
        
        try:
            result = await session.read_resource(uri=resource_uri)
            if result and result.contents:
                print(f"\nResource: {resource_uri}")
                print("Content:")
                print(result.contents[0].text)
            else:
                print("No content available.")
        except Exception as e:
            print(f"Error: {e}")
    
    async def list_prompts(self):
        """List all available prompts."""
        if not self.available_prompts:
            print("No prompts available.")
            return
        
        print("\nAvailable prompts:")
        for prompt in self.available_prompts:
            print(f"- {prompt['name']}: {prompt['description']}")
            if prompt['arguments']:
                print(f"  Arguments:")
                for arg in prompt['arguments']:
                    arg_name = arg.name if hasattr(arg, 'name') else arg.get('name', '')
                    print(f"    - {arg_name}")
    
    async def execute_prompt(self, prompt_name, args):
        """Execute a prompt with the given arguments."""
        session = self.prompt_to_session.get(prompt_name)
        if not session:
            print(f"Prompt '{prompt_name}' not found.")
            return
        
        try:
            result = await session.get_prompt(prompt_name, arguments=args)
            if result and result.messages:
                prompt_content = result.messages[0].content
                
                # Extract text from content (handles different formats)
                if isinstance(prompt_content, str):
                    text = prompt_content
                elif hasattr(prompt_content, 'text'):
                    text = prompt_content.text
                else:
                    # Handle list of content items
                    text = " ".join(item.text if hasattr(item, 'text') else str(item) 
                                  for item in prompt_content)
                
                print(f"\nExecuting prompt '{prompt_name}'...")
                print(f'prompt {text}')
                # await self.process_query(text)
        except Exception as e:
            print(f"Error: {e}")


    async def connect_to_server(self, server_name: str, server_config: dict) -> None:
        """Connect to a single MCP server."""
        try:
            print(f"Connecting to {server_name} with config: {server_config}")
            server_params = StdioServerParameters(**server_config)
            stdio_transport = await self.exit_stack.enter_async_context(
                stdio_client(server_params)
            ) # new
            read, write = stdio_transport
            session = await self.exit_stack.enter_async_context(
                ClientSession(read, write)
            ) # new

            # try:
            #     # read_stream, write_stream, session_id = await streamablehttp_client(...)
            #     streamable_transport = await self.exit_stack.enter_async_context(
            #             streamablehttp_client(url=server_config["url"])
            #         )
            #     read_stream, write_stream, session_id = streamable_transport
            #     self.exit_stack.push_async_callback(read_stream.aclose)
            #     self.exit_stack.push_async_callback(write_stream.aclose)
            # except Exception as e:
            #     print("Stream setup failed:", e)

            await session.initialize()            
            self.sessions.append(session)

            lang_tools = await load_mcp_tools(session)
            for tool in lang_tools:
                if tool.name not in [t.name for t in self.langchain_tools]:
                    self.langchain_tools.append(tool)

            response = await session.list_tools()
            tools = response.tools
            print(f"\nConnected to {server_name} with tools:", [t.name for t in tools])
            
            for tool in tools: # new
                self.tool_to_session[tool.name] = session
                self.available_tools.append({
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.inputSchema
                })

            # List available prompts
            prompts_response = await session.list_prompts()
            if prompts_response and prompts_response.prompts:
                for prompt in prompts_response.prompts:
                    self.prompt_to_session[prompt.name] = session
                    self.available_prompts.append({
                        "name": prompt.name,
                        "description": prompt.description,
                        "arguments": prompt.arguments
                    })

            # List available resources
            resources_response = await session.list_resources()
            if resources_response and resources_response.resources:
                for resource in resources_response.resources:
                    resource_uri = str(resource.uri)
                    self.resource_to_session[resource_uri] = session

        except Exception as e:
            print(f"Failed to connect to {server_name}: {e}")
    
    async def connect_to_servers(self): # new
        """Connect to all configured MCP servers."""
        try:
            with open("/home/abhilash/NLP_basics/MCP_server/openAI/server_config.json", "r") as file:
                data = json.load(file)
            
            servers = data.get("mcpServers", {})
            
            for server_name, server_config in servers.items():
                print(server_name, server_config)
                await self.connect_to_server(server_name, server_config)
        except Exception as e:
            print(f"Error loading server configuration: {e}")
            raise
    
async def main():
    chatbot = OpenAI_MCP_Client(
                streaming=False,
                model_name="gpt-4o-mini",
                api_key=os.environ['OPENAI_API_KEY']
                )
    try:
        # the mcp clients and sessions are not initialized using "with"
        # like in the previous lesson
        # so the cleanup should be manually handled
        await chatbot.connect_to_servers() # new! 
        await chatbot.chat_loop(stream=False)
    finally:
        print("Task completed : ")
        await chatbot.cleanup() #new!
    
if __name__ == "__main__":
    asyncio.run(main())