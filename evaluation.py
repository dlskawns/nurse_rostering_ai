import argparse
import time
import json
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os
from datetime import datetime, timedelta
import calendar

# --- 신규 Import ---
import optuna
from scipy.stats import zscore
from scipy.special import expit as sigmoid
# ---

from openpyxl.styles import PatternFill
from openpyxl.formatting.rule import CellIsRule
from openpyxl.utils import get_column_letter

# main_v2.py에서 필요한 함수 및 클래스를 가져옵니다.
# 해당 파일이 같은 디렉토리에 있다고 가정합니다.
try:
    from main_v2 import (
        load_test_data,
        create_nurses_from_data,
        NurseRosterConfig,
        Timer
    )
    # RosterSystem은 이제 roster_system.py에서 가져옵니다.
    from roster_system import RosterSystem
except ImportError as e:
    print(f"필요한 모듈을 가져오는 데 실패했습니다: {e}")
    print("main_v2.py와 roster_system.py가 evaluation.py와 같은 디렉토리에 있는지 확인하세요.")
    exit(1)


class RosterEvaluator:
    """근무표 생성 결과를 평가하는 클래스"""

    def __init__(self, roster_system, test_data):
        self.rs = roster_system
        self.roster = self.rs.roster  # (nurse, day, shift)
        self.nurses = self.rs.nurses
        self.config = self.rs.config
        self.num_days = self.rs.num_days
        self.shift_types = self.config.shift_types
        self.test_data = test_data
        self.nurse_id_map = {nurse.id: i for i, nurse in enumerate(self.nurses)}

    def _get_nurse_idx(self, nurse_id):
        return self.nurse_id_map.get(int(nurse_id))

    def evaluate_all(self):
        """모든 평가 지표를 계산합니다."""
        satisfaction, pref_details = self.evaluate_preference_satisfaction()
        constraints, constraint_details = self.evaluate_constraint_violations()
        
        results = {
            "preference_satisfaction": satisfaction,
            "constraint_violations": constraints,
        }
        details = {
            "preference_details": pref_details,
            "constraint_details": constraint_details,
        }
        return results, details

    def evaluate_preference_satisfaction(self):
        """선호도 충족도를 평가합니다."""
        off_requests = self.test_data.get('off_requests', {})
        shift_preferences = self.test_data.get('shift_preferences', {})
        
        total_off_req, met_off_req = 0, 0
        off_details = []
        off_idx = self.shift_types.index('OFF')

        for nurse_id, days in off_requests.items():
            n_idx = self._get_nurse_idx(nurse_id)
            if n_idx is None:
                continue
            
            for day in days:
                day_int = int(day)
                total_off_req += 1
                is_met = self.roster[n_idx, day_int - 1, off_idx] == 1
                if is_met:
                    met_off_req += 1
                off_details.append({
                    "nurse_name": self.nurses[n_idx].name,
                    "type": "OFF", "day": day_int, "shift": "OFF", "is_met": is_met
                })

        total_shift_req, met_shift_req = 0, 0
        shift_details = []

        for nurse_id, prefs in shift_preferences.items():
            n_idx = self._get_nurse_idx(nurse_id)
            if n_idx is None:
                continue
            
            for shift, dates in prefs.items():
                if shift not in self.shift_types:
                    continue
                shift_idx = self.shift_types.index(shift)
                for day in dates:
                    total_shift_req += 1
                    is_met = self.roster[n_idx, int(day) - 1, shift_idx] == 1
                    if is_met:
                        met_shift_req += 1
                    shift_details.append({
                        "nurse_name": self.nurses[n_idx].name,
                        "type": "Shift", "day": int(day), "shift": shift, "is_met": is_met
                    })
        
        summary = {
            "off_requests_total": total_off_req,
            "off_requests_met": met_off_req,
            "shift_preferences_total": total_shift_req,
            "shift_preferences_met": met_shift_req,
            "total_requests": total_off_req + total_shift_req,
            "total_met": met_off_req + met_shift_req,
            "satisfaction_rate": ((met_off_req + met_shift_req) / (total_off_req + total_shift_req) * 100) if (total_off_req + total_shift_req) > 0 else 100,
        }
        
        return summary, off_details + shift_details

    def evaluate_constraint_violations(self):
        """모든 제약 조건 위반을 평가합니다."""
        violations = {}
        details = {}

        # 각 제약 조건 평가 함수 호출
        for func_name in dir(self):
            if func_name.startswith("eval_C_"):
                violation_count, violation_details = getattr(self, func_name)()
                constraint_name = func_name.replace("eval_", "")
                violations[constraint_name] = violation_count
                details[constraint_name] = violation_details
        
        return violations, details

    def eval_C_OFF_WEEK2(self):
        """각 간호사는 한 주(월~일) 동안 OFF >= 2일"""
        violations = 0
        details = []
        off_idx = self.shift_types.index('OFF')
        first_day_weekday = self.rs.target_month.weekday()  # Monday is 0

        for n_idx, nurse in enumerate(self.nurses):
            # 첫 주
            first_week_len = 7 - first_day_weekday
            offs = np.sum(self.roster[n_idx, 0:first_week_len, off_idx])
            if offs < 2 * (first_week_len / 7): # 비례적으로 계산
                violations += 1
                details.append({"nurse": nurse.name, "week": 1, "offs": offs})

            # 중간 주
            for d in range(first_week_len, self.num_days - 6, 7):
                offs = np.sum(self.roster[n_idx, d:d+7, off_idx])
                if offs < 2:
                    violations += 1
                    details.append({"nurse": nurse.name, "week_start_day": d + 1, "offs": offs})
        return violations, details

    def eval_C_N_MAXCONSEC3(self):
        """Night (N) 3일 연속 초과 배정 금지 (즉, N 4회)"""
        violations = 0
        details = []
        n_idx_shift = self.shift_types.index('N')
        for n_idx, nurse in enumerate(self.nurses):
            for d in range(self.num_days - 3):
                if np.all(self.roster[n_idx, d:d+4, n_idx_shift] == 1):
                    violations += 1
                    details.append({"nurse": nurse.name, "start_day": d + 1})
        return violations, details

    def eval_C_N3_REST2(self):
        """N,N,N 뒤에 OFF,OFF 반드시 연속 배정"""
        violations = 0
        details = []
        n_idx_shift = self.shift_types.index('N')
        off_idx = self.shift_types.index('OFF')

        for n_idx, nurse in enumerate(self.nurses):
            for d in range(self.num_days - 4):
                is_n3 = np.all(self.roster[n_idx, d:d+3, n_idx_shift] == 1)
                # NNN 다음에 오는 근무가 OFF가 아닌 경우
                not_n4 = self.roster[n_idx, d+3, n_idx_shift] == 0
                if is_n3 and not_n4:
                    is_off2 = np.all(self.roster[n_idx, d+3:d+5, off_idx] == 1)
                    if not is_off2:
                        violations += 1
                        details.append({"nurse": nurse.name, "day_after_n3": d + 4})
        return violations, details
    
    def eval_C_E_NOT_NEXT_D(self):
        """어떤 날 E면 다음날 D 금지"""
        violations = 0
        details = []
        e_idx = self.shift_types.index('E')
        d_idx = self.shift_types.index('D')
        for n_idx, nurse in enumerate(self.nurses):
            for d in range(self.num_days - 1):
                if self.roster[n_idx, d, e_idx] == 1 and self.roster[n_idx, d + 1, d_idx] == 1:
                    violations += 1
                    details.append({"nurse": nurse.name, "day": d + 1})
        return violations, details

    def eval_C_REQ_D_E_N(self):
        """날짜 d, shift s의 배정 인원 >= 요구 인원. 부족한 경우만 위반으로 계산."""
        violations = 0
        details = []
        reqs = self.config.daily_shift_requirements
        for d in range(self.num_days):
            for shift, req_count in reqs.items():
                if shift in self.shift_types:
                    shift_idx = self.shift_types.index(shift)
                    actual_count = np.sum(self.roster[:, d, shift_idx])
                    if actual_count < req_count:
                        violations += int(req_count - actual_count)
                        details.append({"day": d + 1, "shift": shift, "required": req_count, "actual": int(actual_count)})
        return violations, details

    def eval_C_OFF_MONTH_FIX(self):
        """간호사별 월간 OFF = 설정값 M"""
        violations = 0
        details = []
        off_idx = self.shift_types.index('OFF')
        for n_idx, nurse in enumerate(self.nurses):
            target_offs = (
                self.config.global_monthly_off_days
                + self.config.standard_personal_off_days
                + nurse.personal_off_adjustment
            )
            actual_offs = np.sum(self.roster[n_idx, :, off_idx])
            if actual_offs != target_offs:
                violations += abs(int(actual_offs) - int(target_offs))
                details.append({"nurse": nurse.name, "target": target_offs, "actual": int(actual_offs)})
        return violations, details

    def eval_C_HN_WKND_OFF(self):
        """수간호사는 모든 주말(토/일) OFF"""
        violations = 0
        details = []
        off_idx = self.shift_types.index('OFF')
        first_day = self.rs.target_month
        
        for n_idx, nurse in enumerate(self.nurses):
            if nurse.is_head_nurse:
                for d in range(self.num_days):
                    current_day = first_day + timedelta(days=d)
                    if current_day.weekday() >= 5: # 5:토, 6:일
                        if self.roster[n_idx, d, off_idx] == 0:
                            violations += 1
                            details.append({"nurse": nurse.name, "day": d + 1})
        return violations, details

    def eval_C_N_MONTH15(self):
        """간호사 당 월간 Night <= 15회 (설정값 따름)"""
        violations = 0
        details = []
        n_idx_shift = self.shift_types.index('N')
        max_nights = self.config.max_night_shifts_per_month

        for n_idx, nurse in enumerate(self.nurses):
            actual_nights = np.sum(self.roster[n_idx, :, n_idx_shift])
            if actual_nights > max_nights:
                violations += 1  # 초과 시 1회 위반으로 카운트
                details.append({
                    "nurse": nurse.name,
                    "limit": max_nights,
                    "actual": int(actual_nights)
                })
        return violations, details

    def eval_C_OFF_7D2(self):
        """어떤 연속 7일 구간에서도 OFF >= 2일"""
        violations = 0
        details = []
        off_idx = self.shift_types.index('OFF')
        for n_idx, nurse in enumerate(self.nurses):
            for d in range(self.num_days - 6):
                offs = np.sum(self.roster[n_idx, d:d+7, off_idx])
                if offs < 2:
                    violations += 1
                    details.append({"nurse": nurse.name, "window_start_day": d + 1, "offs_in_window": int(offs)})
        return violations, details

    def eval_C_N2_REST2(self):
        """N,N 뒤에 OFF,OFF 연속 배정"""
        violations = 0
        details = []
        n_idx_shift = self.shift_types.index('N')
        off_idx = self.shift_types.index('OFF')
        for n_idx, nurse in enumerate(self.nurses):
            for d in range(self.num_days - 3):
                is_n2 = (self.roster[n_idx, d, n_idx_shift] == 1 and
                         self.roster[n_idx, d + 1, n_idx_shift] == 1)
                
                is_not_n3 = True
                if d + 2 < self.num_days:
                     is_not_n3 = self.roster[n_idx, d + 2, n_idx_shift] == 0

                if is_n2 and is_not_n3:
                    is_off2 = (d + 3 < self.num_days and
                               self.roster[n_idx, d + 2, off_idx] == 1 and
                               self.roster[n_idx, d + 3, off_idx] == 1)
                    if not is_off2:
                        violations += 1
                        details.append({"nurse": nurse.name, "n_start_day": d + 1})
        return violations, details
    
    def eval_C_OFF_EACH4D(self):
        """모든 연속 4일 구간에 최소 1 OFF"""
        violations = 0
        details = []
        off_idx = self.shift_types.index('OFF')
        for n_idx, nurse in enumerate(self.nurses):
            for d in range(self.num_days - 3):
                if np.sum(self.roster[n_idx, d:d+4, off_idx]) == 0:
                    violations += 1
                    details.append({"nurse": nurse.name, "window_start_day": d + 1})
        return violations, details

    def eval_C_OFF_CONSEC(self):
        """OFF는 단독 1일로 놓지 말 것 (work-OFF-work 패턴)"""
        violations = 0
        details = []
        off_idx = self.shift_types.index('OFF')
        for n_idx, nurse in enumerate(self.nurses):
            for d in range(1, self.num_days - 1):
                is_off = self.roster[n_idx, d, off_idx] == 1
                is_prev_work = np.sum(self.roster[n_idx, d - 1, :]) > 0 and self.roster[n_idx, d - 1, off_idx] == 0
                is_next_work = np.sum(self.roster[n_idx, d + 1, :]) > 0 and self.roster[n_idx, d + 1, off_idx] == 0
                if is_off and is_prev_work and is_next_work:
                    violations += 1
                    details.append({"nurse": nurse.name, "day": d + 1})
        return violations, details
    
    def eval_C_HN_DAYONLY(self):
        """수간호사 근무 시 항상 Day(D)"""
        violations = 0
        details = []
        d_idx = self.shift_types.index('D')
        off_idx = self.shift_types.index('OFF')
        for n_idx, nurse in enumerate(self.nurses):
            if nurse.is_head_nurse:
                for d in range(self.num_days):
                    is_working = np.sum(self.roster[n_idx, d, :]) > 0
                    is_off = self.roster[n_idx, d, off_idx] == 1
                    if is_working and not is_off:
                        is_day = self.roster[n_idx, d, d_idx] == 1
                        if not is_day:
                            violations += 1
                            shift_idx_arr = np.where(self.roster[n_idx, d, :] == 1)[0]
                            actual_shift = self.shift_types[shift_idx_arr[0]] if shift_idx_arr.size > 0 else "UNKNOWN"
                            details.append({"nurse": nurse.name, "day": d + 1, "assigned_shift": actual_shift})
        return violations, details


def run_single_generation(data, time_limit=30, use_lns=False, preference_matrix=None):
    """단일 근무표 생성을 실행하고 RosterSystem 객체를 반환합니다."""
    config_data = data.get('config', {})
    config = NurseRosterConfig(
        daily_shift_requirements=config_data.get('daily_shift_requirements', {"D": 3, "E": 3, "N": 2}),
        max_consecutive_work_days=config_data.get('max_consecutive_work_days', 6),
        global_monthly_off_days=config_data.get('global_monthly_off_days', 3),
        standard_personal_off_days=config_data.get('standard_personal_off_days', 8),
        enforce_two_offs_per_week=config_data.get('enforce_two_offs_per_week', True),
        max_night_shifts_per_month=config_data.get('max_night_shifts_per_month', 15),
        max_consecutive_nights=config_data.get('max_consecutive_nights', 2),
    )
    
    target_month = datetime.strptime(data['target_month'], '%Y-%m-%d').date()
    nurses = create_nurses_from_data(data['nurses'])
    
    # RosterSystem 초기화 시 선호도 행렬 전달
    roster_system = RosterSystem(nurses, target_month, config, preference_matrix=preference_matrix)
    
    # 선호도 행렬이 외부에서 주입되므로, 기존 apply 함수 호출은 필요 없음
    # (단, Optuna 최적화 과정이 아닌 최종 실행에서는 호출될 수 있으나,
    #  여기서는 build_scaled_preference_matrix에서 처리하므로 주석 처리)
    # if 'off_requests' in data:
    #     roster_system.apply_off_requests(data['off_requests'])
    # if 'shift_preferences' in data:
    #     roster_system.apply_shift_preferences(data['shift_preferences'])
        
    roster_system.optimize_roster_with_cp_sat(time_limit_seconds=time_limit)
    
    if use_lns:
        roster_system.optimize_with_lns(max_iterations=5, time_limit_per_iteration=10)
        
    return roster_system

def build_scaled_preference_matrix(thetas, test_data, nurses, config):
    """Z-score와 Sigmoid를 사용하여 선호도 행렬을 동적으로 스케일링합니다."""
    num_nurses = len(nurses)
    num_days = calendar.monthrange(
        datetime.strptime(test_data['target_month'], '%Y-%m-%d').year,
        datetime.strptime(test_data['target_month'], '%Y-%m-%d').month
    )[1]
    
    # 1. 기본 선호도 행렬 생성
    base_prefs = np.zeros((num_nurses, num_days, config.num_shifts))
    nurse_id_map = {nurse.id: i for i, nurse in enumerate(nurses)}
    
    # OFF 요청 적용
    off_requests = test_data.get('off_requests', {})
    off_idx = config.shift_types.index('OFF')
    for nurse_id, days in off_requests.items():
        n_idx = nurse_id_map.get(int(nurse_id))
        if n_idx is None: continue
        for day, score in days.items():
            base_prefs[n_idx, int(day) - 1, off_idx] = score

    # Shift 요청 적용
    shift_preferences = test_data.get('shift_preferences', {})
    for nurse_id, prefs in shift_preferences.items():
        n_idx = nurse_id_map.get(int(nurse_id))
        if n_idx is None: continue
        for shift, dates in prefs.items():
            if shift not in config.shift_types: continue
            s_idx = config.shift_types.index(shift)
            for day, score in dates.items():
                base_prefs[n_idx, int(day) - 1, s_idx] = score
    
    # 2. 스케일링 적용
    # 0이 아닌 값들만 추출하여 스케일링
    non_zero_indices = base_prefs > 0
    if np.any(non_zero_indices):
        non_zero_values = base_prefs[non_zero_indices]
        
        # Z-score 정규화 (표준편차가 0일 경우 대비)
        if np.std(non_zero_values) > 1e-6:
            scaled_values = zscore(non_zero_values)
        else:
            scaled_values = non_zero_values - np.mean(non_zero_values)
            
        # Sigmoid 압축
        sigmoid_values = sigmoid(scaled_values)
        
        # 스케일링된 값을 다시 원래 위치에 넣기
        base_prefs[non_zero_indices] = sigmoid_values

    # 3. Theta 가중치 적용
    scaled_matrix = np.zeros_like(base_prefs)
    
    # OFF 가중치 적용
    scaled_matrix[:, :, off_idx] = base_prefs[:, :, off_idx] * thetas['theta_off']
    
    # D, E, N 가중치 적용
    for shift_name in ['D', 'E', 'N']:
        s_idx = config.shift_types.index(shift_name)
        scaled_matrix[:, :, s_idx] = base_prefs[:, :, s_idx] * thetas['theta_shift']
        
    return scaled_matrix

def optimize_thetas(test_data, nurses, config, n_trials=30):
    """Optuna를 사용하여 최적의 theta 값을 찾습니다."""
    
    print("\n===== 선호도 가중치(theta) 최적화 시작 =====")
    
    def objective(trial):
        # 1. Theta 값 제안
        thetas = {
            'theta_off': trial.suggest_float("theta_off", 100, 2000, log=True),
            'theta_shift': trial.suggest_float("theta_shift", 10, 500, log=True),
        }
        
        # 2. 제안된 Theta로 선호도 행렬 생성
        preference_matrix = build_scaled_preference_matrix(thetas, test_data, nurses, config)
        
        # 3. 짧은 시간으로 근무표 생성
        rs = run_single_generation(
            test_data, 
            time_limit=10, # Optuna trial은 짧게
            use_lns=False,
            preference_matrix=preference_matrix
        )
        
        # 4. 결과 평가 및 점수 계산
        evaluator = RosterEvaluator(rs, test_data)
        results, _ = evaluator.evaluate_all()
        
        satisfaction_rate = results['preference_satisfaction']['satisfaction_rate']
        total_violations = sum(results['constraint_violations'].values())
        
        # Hard constraint 위반 시 매우 큰 페널티 부여
        # RosterSystem이 Hard Constraint를 사용하므로, 해를 찾지 못한 경우를 위반으로 간주
        if rs.roster.sum() == 0: # 해를 못찾으면 roster가 비어있음
             return -1_000_000

        # 점수 = 만족도 - (위반 * 페널티)
        # 현재 모든 제약이 Hard이므로, violation은 0이 되어야 함.
        # 따라서 만족도 자체가 점수가 됨
        score = satisfaction_rate
        
        return score

    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials)
    
    print(f"Theta 최적화 완료: {n_trials}회 시도")
    print(f"최적 점수: {study.best_value:.2f}")
    print(f"최적 파라미터: {study.best_params}")
    
    return study.best_params

def format_roster_to_dataframe(roster_system):
    """
    Formats the roster and creates summary DataFrames for Excel export.
    Returns three DataFrames: roster, daily summary, and shortage summary.
    """
    rs = roster_system
    num_days = rs.num_days
    days = pd.date_range(start=rs.target_month, periods=num_days, freq='D')
    
    nurse_names = [n.name for n in rs.nurses]
    # 'YYYY-MM-DD (ddd)' format for columns
    column_headers = [d.strftime('%Y-%m-%d') for d in days]
    excel_column_headers = [d.strftime('%Y-%m-%d (%a)') for d in days]
    
    # Roster DataFrame
    roster_df = pd.DataFrame(index=nurse_names, columns=excel_column_headers)
    roster_df.index.name = "간호사"
    
    for day_idx, col_header in enumerate(excel_column_headers):
        for nurse_idx, nurse in enumerate(rs.nurses):
            shift_idx_arr = np.where(rs.roster[nurse_idx, day_idx] == 1)[0]
            if len(shift_idx_arr) > 0:
                shift = rs.config.shift_types[shift_idx_arr[0]]
                roster_df.loc[nurse.name, col_header] = shift
            else:
                roster_df.loc[nurse.name, col_header] = '-'
    
    # Add shift counts summary columns
    for shift in rs.config.shift_types:
        roster_df[f'{shift}_count'] = roster_df[excel_column_headers].apply(lambda row: (row == shift).sum(), axis=1)
        
    # Daily Summary DataFrame
    summary_index = ['D', 'E', 'N', 'OFF']
    summary_df = pd.DataFrame(index=summary_index, columns=excel_column_headers)
    summary_df.index.name = "일별 합계"
    for shift in summary_index:
        summary_df.loc[shift] = (roster_df[excel_column_headers] == shift).sum()

    # Shortage DataFrame
    shortage_index = ['D', 'E', 'N']
    shortage_df = pd.DataFrame(index=shortage_index, columns=excel_column_headers)
    shortage_df.index.name = "부족 SHIFT"
    reqs = rs.config.daily_shift_requirements
    for shift in shortage_index:
        required = reqs.get(shift, 0)
        actual = summary_df.loc[shift]
        shortage_df.loc[shift] = actual - required
        
    return roster_df, summary_df, shortage_df

def plot_results(run_data, output_dir):
    """평가 결과를 플롯으로 저장합니다."""
    if not run_data:
        return

    df = pd.DataFrame(run_data)
    
    # 1. 선호도 충족률 플롯
    plt.figure(figsize=(12, 6))
    plt.plot(df['run'], df['satisfaction_rate'], marker='o', linestyle='-', label='Satisfaction Rate (%)')
    plt.title('Preference Satisfaction Rate per Run')
    plt.xlabel('Run Number')
    plt.ylabel('Satisfaction Rate (%)')
    plt.grid(True)
    plt.ylim(0, 105)
    plt.legend()
    plt.savefig(os.path.join(output_dir, "preference_satisfaction_plot.png"))
    plt.close()
    
    # 2. 제약 조건 위반 횟수 플롯
    plt.figure(figsize=(12, 6))
    plt.plot(df['run'], df['total_violations'], marker='o', linestyle='-', color='r', label='Total Violations')
    plt.title('Total Constraint Violations per Run')
    plt.xlabel('Run Number')
    plt.ylabel('Number of Violations')
    plt.grid(True)
    plt.legend()
    plt.savefig(os.path.join(output_dir, "constraint_violations_plot.png"))
    plt.close()

def main(args):
    """메인 평가 로직"""
    test_data = load_test_data(args.data_file)
    
    # --- Optuna 최적화 단계 추가 ---
    # 평가에 사용할 config, nurses 객체 미리 생성
    eval_config = NurseRosterConfig()
    eval_nurses = create_nurses_from_data(test_data['nurses'])
    
    best_thetas = optimize_thetas(test_data, eval_nurses, eval_config, n_trials=args.optuna_trials)
    
    print("\n===== 최적 Theta로 최종 평가 실행 =====")
    # 최적화된 Theta로 최종 선호도 행렬 생성
    optimized_pref_matrix = build_scaled_preference_matrix(best_thetas, test_data, eval_nurses, eval_config)
    
    # --- 기존 평가 로직 ---
    all_run_data = []
    all_details = {"preference": [], "constraint": []}
    all_rosters = []
    previous_roster = None

    # 결과 저장 디렉토리 생성
    output_dir = "evaluation_results"
    os.makedirs(output_dir, exist_ok=True)

    for i in range(args.num_runs):
        print(f"\n===== Running Evaluation: Run {i+1}/{args.num_runs} =====")
        
        start_time = time.time()
        with Timer(f"Generation Run {i+1}"):
            rs = run_single_generation(
                test_data, 
                time_limit=args.time_limit, 
                use_lns=False, # Hard constraint에서는 LNS 의미가 적음
                preference_matrix=optimized_pref_matrix
            )
        end_time = time.time()
        
        all_rosters.append(rs)
        evaluator = RosterEvaluator(rs, test_data)
        results, details = evaluator.evaluate_all()

        generation_speed = end_time - start_time
        pref_satisfaction = results['preference_satisfaction']
        constraint_violations = results['constraint_violations']
        
        # 유연성 측정
        flexibility = 0
        if previous_roster is not None:
            diff = np.sum(rs.roster != previous_roster)
            total_elements = rs.roster.size
            flexibility = (diff / total_elements) * 100 if total_elements > 0 else 0
        previous_roster = rs.roster.copy()
        
        run_summary = {
            "run": i + 1,
            "generation_speed": generation_speed,
            "total_requests": pref_satisfaction['total_requests'],
            "total_met": pref_satisfaction['total_met'],
            "satisfaction_rate": pref_satisfaction['satisfaction_rate'],
            "total_violations": sum(constraint_violations.values()),
            "flexibility_vs_previous_run(%)": flexibility,
            **{f"violations_{k}": v for k, v in constraint_violations.items()}
        }
        all_run_data.append(run_summary)
        
        # 상세 결과 저장
        pref_df = pd.DataFrame(details['preference_details'])
        pref_df['run'] = i + 1
        all_details['preference'].append(pref_df)

        cons_list = []
        for cons, cons_dets in details['constraint_details'].items():
            if cons_dets:
                df = pd.DataFrame(cons_dets)
                df['constraint'] = cons
                cons_list.append(df)
        if cons_list:
            cons_df = pd.concat(cons_list, ignore_index=True)
            cons_df['run'] = i + 1
            all_details['constraint'].append(cons_df)

    # Excel로 결과 저장
    excel_path = os.path.join(output_dir, "evaluation_report.xlsx")
    with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
        pd.DataFrame(all_run_data).to_excel(writer, sheet_name='Summary', index=False)
        
        if all_details['preference']:
            pd.concat(all_details['preference'], ignore_index=True).to_excel(writer, sheet_name='Preference_Violations', index=False)
        if all_details['constraint']:
            pd.concat(all_details['constraint'], ignore_index=True).to_excel(writer, sheet_name='Constraint_Violations', index=False)
        
        # 각 실행별 근무표를 별도 시트에 저장
        for i, roster_system in enumerate(all_rosters):
            roster_df, summary_df, shortage_df = format_roster_to_dataframe(roster_system)
            sheet_name = f'Run_{i+1}_Roster'
            
            # 1. 근무표 저장
            roster_df.to_excel(writer, sheet_name=sheet_name)
            ws = writer.sheets[sheet_name]

            # 2. 일별 합계 저장
            summary_start_excel_row = ws.max_row + 3
            summary_df.to_excel(
                writer, 
                sheet_name=sheet_name, 
                startrow=summary_start_excel_row - 1,
                header=False
            )

            # 3. 부족분 저장
            shortage_start_excel_row = ws.max_row + 2
            shortage_df.to_excel(
                writer,
                sheet_name=sheet_name,
                startrow=shortage_start_excel_row - 1,
                header=False
            )

            # 4. 부족분 조건부 서식 적용
            red_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
            rule = CellIsRule(operator='lessThan', formula=['0'], stopIfTrue=True, fill=red_fill)
            
            # 서식 적용 범위 계산
            formatting_start_row = shortage_start_excel_row
            formatting_end_row = formatting_start_row + len(shortage_df) - 1
            start_col = 2
            end_col = start_col + len(shortage_df.columns) - 1
            
            data_range = f"{get_column_letter(start_col)}{formatting_start_row}:{get_column_letter(end_col)}{formatting_end_row}"
            ws.conditional_formatting.add(data_range, rule)

    print(f"\nEvaluation report saved to {excel_path}")
    print("The report includes Summary, Preference_Violations, Constraint_Violations, and individual Roster sheets for each run.")

    # 플롯 생성
    plot_results(all_run_data, output_dir)
    print(f"Plots saved in {output_dir} directory.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Nurse Rostering Evaluation Module")
    parser.add_argument(
        "--num_runs",
        type=int,
        default=1,
        help="Number of times to run the roster generation for evaluation."
    )
    parser.add_argument(
        "--data_file",
        type=str,
        default="test_data_shift.json",
        help="Path to the test data JSON file."
    )
    parser.add_argument(
        "--time_limit",
        type=int,
        default=60, # Hard Constraint는 더 오래 걸릴 수 있으므로 시간 증가
        help="Time limit in seconds for the CP-SAT solver."
    )
    parser.add_argument(
        "--optuna_trials",
        type=int,
        default=5, # Optuna 시도 횟수
        help="Number of trials for Optuna to find best thetas."
    )
    args = parser.parse_args()
    main(args) 