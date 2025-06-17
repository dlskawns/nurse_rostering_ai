import json
import os

def get_nurse_data_from_source(file_path="test_data_shift.json"):
    """
    부서원 관리 페이지에서 관리되는 간호사 데이터를 가져옵니다.
    
    현재는 test_data_shift.json 파일에서 데이터를 읽어오는 것으로 대체합니다.
    향후에는 데이터베이스나 API를 통해 이 데이터를 가져오도록 확장될 수 있습니다.

    Args:
        file_path (str): 간호사 데이터가 저장된 JSON 파일 경로.

    Returns:
        list: 간호사 정보가 담긴 딕셔너리의 리스트.
              파일이 없거나 비어있는 경우 빈 리스트를 반환합니다.
    """
    if not os.path.exists(file_path):
        print(f"오류: 데이터 파일 '{file_path}'을(를) 찾을 수 없습니다.")
        return []

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get("nurses", [])
    except json.JSONDecodeError:
        print(f"오류: '{file_path}' 파일이 유효한 JSON 형식이 아닙니다.")
        return []
    except Exception as e:
        print(f"데이터를 읽는 중 오류가 발생했습니다: {e}")
        return []

if __name__ == '__main__':
    print("roster_executer.py 실행됨")
    print("-" * 20)
    
    nurse_data = get_nurse_data_from_source()
    
    if nurse_data:
        print(f"성공적으로 {len(nurse_data)}명의 간호사 데이터를 불러왔습니다.")
        print("첫 번째 간호사 데이터:")
        print(json.dumps(nurse_data[0], indent=2, ensure_ascii=False))
    else:
        print("간호사 데이터를 불러오지 못했습니다.") 