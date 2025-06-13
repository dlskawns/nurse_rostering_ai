import json
from agents.main_graph import GraphGenerate
import pprint
graph = GraphGenerate()

with open('test_data_shift.json', 'r') as f:
    schema = json.load(f)


schema = schema['nurses']
response = graph.invoke({"request": "주말 출근은 최대한 N으로 하고싶어요.", "schema": schema})
pprint.pprint(response)