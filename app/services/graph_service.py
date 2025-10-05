from agents.main_graph import GraphGenerate

class GraphService:
    def __init__(self):
        self._graph = GraphGenerate()

    async def invoke(self, request: str | list[str], schema: str, case: object | None, year: int, month: int):
        """
        주어진 요청과 스키마로 그래프를 실행합니다.

        Args:
            request (str): 사용자 요청 문자열
            schema (list): 간호사 스키마 리스트

        Returns:
            dict: 그래프 실행 결과
        """

        response = await self._graph.ainvoke({"request": request, "schema": schema, "case": case, "year": year, "month": month})        
        response = [response['shift_results'], response['preference_results']]
        import pprint
        pprint.pprint(response)
        return response

graph_service = GraphService() 
