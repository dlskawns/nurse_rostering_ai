from app.agents.main_graph import GraphGenerate

class GraphService:
    def __init__(self):
        self._graph = GraphGenerate()

    async def invoke(self, request: str, schema: str):
        """
        주어진 요청과 스키마로 그래프를 실행합니다.

        Args:
            request (str): 사용자 요청 문자열
            schema (list): 간호사 스키마 리스트

        Returns:
            dict: 그래프 실행 결과
        """
        print('\n\n\n\n\nrequest 이건???', request)
        print('\n\n\n\n\nschema 이건???', schema)
        try:
            response = await self._graph.ainvoke({"request": request, "schema": schema})
        except Exception as e:
            print('\n\n\n\n\n안온거지 씨발?? \n\n\n\n\n\n', response)
            response = [response['shift_results'], response['preference_results']]
            print('\n\n\n\n\n\n응답:', response, '\n\n\n\n\n\n')
            return response

graph_service = GraphService() 
