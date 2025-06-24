import operator
from langgraph.graph import StateGraph, END
from typing import TypedDict, Annotated, List
from app.agents.query_analyzer_agent import query_analyzer
from app.agents.shift_analyzer_agent import create_shift_analyzer
from app.agents.preference_analyzer_agent import create_preference_analyzer
from langgraph.prebuilt import create_react_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
# from agents.collector_agent import collector

def collector(state):
    """
    information collector
    """
    # print('-------collector-------')
    # print('state', state)
class ContextAnalyticsState(TypedDict):
    request: str                         # Query - 유저 input
    schema: object
    query_shift: List[str]
    query_preference: List[str]
    query_chat: List[str]
    query_others: List[str]
    shift_results: Annotated[list, operator.add]
    preference_results: Annotated[list, operator.add]
    model: object

def GraphGenerate():
    graph = StateGraph(ContextAnalyticsState)
    graph.add_node('query_analyzer', query_analyzer)
    graph.add_node('create_shift_analyzer', create_shift_analyzer)
    graph.add_node('create_preference_analyzer', create_preference_analyzer)
    graph.add_node('collector', collector)

    graph.set_entry_point('query_analyzer')
    graph.add_edge('query_analyzer', 'create_shift_analyzer')
    graph.add_edge('query_analyzer', 'create_preference_analyzer')

    graph.add_edge('create_shift_analyzer', "collector")
    graph.add_edge('create_preference_analyzer', 'collector')

    graph.add_edge('collector', END)

    app = graph.compile()
    return app