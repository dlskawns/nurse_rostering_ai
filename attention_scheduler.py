import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

@dataclass
class NurseToken:
    """간호사 토큰 정보를 담는 데이터 클래스"""
    experience_years: int
    is_night_nurse: bool
    is_head_nurse: bool
    remaining_off_days: int
    nurse_id: int
    embedding_dim: int = 64

    def to_vector(self) -> torch.Tensor:
        """간호사 정보를 벡터로 변환"""
        # 경력/역할 one-hot (0-5년, 5-10년, 10년 이상)
        exp_vec = torch.zeros(3)
        if self.experience_years < 5:
            exp_vec[0] = 1
        elif self.experience_years < 10:
            exp_vec[1] = 1
        else:
            exp_vec[2] = 1
            
        # 기본 특성 벡터
        features = torch.tensor([
            self.is_night_nurse,
            self.is_head_nurse,
            self.remaining_off_days / 10.0  # 정규화
        ], dtype=torch.float)
        
        # ID 임베딩 (LoRA 스타일)
        id_emb = torch.randn(32)  # 32차원 개인 임베딩
        
        # 전체 벡터 연결
        return torch.cat([exp_vec, features, id_emb])

@dataclass
class DayToken:
    """일자 토큰 정보를 담는 데이터 클래스"""
    day_index: int
    is_weekend: bool
    is_holiday: bool
    embedding_dim: int = 32

    def to_vector(self) -> torch.Tensor:
        """일자 정보를 벡터로 변환"""
        # 주차 정보 (0-4)
        week_num = self.day_index // 7
        week_vec = F.one_hot(torch.tensor(week_num), num_classes=5)
        
        # 요일 정보 (0-6)
        day_of_week = self.day_index % 7
        day_vec = F.one_hot(torch.tensor(day_of_week), num_classes=7)
        
        # 주말/공휴일 플래그
        flags = torch.tensor([self.is_weekend, self.is_holiday])
        
        return torch.cat([week_vec, day_vec, flags])

@dataclass
class ShiftToken:
    """근무 교대 토큰 정보를 담는 데이터 클래스"""
    shift_type: str  # 'D', 'E', 'N', 'OFF'
    embedding_dim: int = 8

    def to_vector(self) -> torch.Tensor:
        """근무 교대 정보를 벡터로 변환"""
        shift_map = {'D': 0, 'E': 1, 'N': 2, 'OFF': 3}
        shift_idx = shift_map[self.shift_type]
        return F.one_hot(torch.tensor(shift_idx), num_classes=4)

class MultiHeadAttentionScheduler(nn.Module):
    """멀티헤드 어텐션 기반 스케줄러"""
    def __init__(
        self,
        n_heads: int = 4,
        nurse_dim: int = 64,
        day_dim: int = 32,
        shift_dim: int = 8,
        pair_dim: int = 16,
        dropout: float = 0.1
    ):
        super().__init__()
        self.n_heads = n_heads
        self.nurse_dim = nurse_dim
        self.day_dim = day_dim
        self.shift_dim = shift_dim
        self.pair_dim = pair_dim
        
        # 입력 및 출력 차원 계산
        self.query_dim = nurse_dim + day_dim  # 간호사 + 일자 차원
        self.key_dim = shift_dim + pair_dim   # 근무 + 페어 차원
        self.head_dim = 32  # 각 헤드의 차원
        
        # 모델 초기화 시 실제 차원 출력 (디버깅용)
        print(f"초기화 차원 - Query: {self.query_dim}, Key: {self.key_dim}, Head: {self.head_dim}")
        
        # Query 변환 행렬
        self.W_Q = nn.Linear(self.query_dim, n_heads * self.head_dim)
        
        # Key 변환 행렬
        self.W_K = nn.Linear(self.key_dim, n_heads * self.head_dim)
        
        # Value 변환 행렬
        self.W_V = nn.Linear(self.key_dim, n_heads * self.head_dim)
        
        # 출력 변환 행렬
        self.W_O = nn.Linear(n_heads * self.head_dim, 1)
        
        self.dropout = nn.Dropout(dropout)
        
        # 헤드별 가중치 (학습 가능)
        self.head_weights = nn.Parameter(torch.ones(n_heads) / n_heads)
        
    def forward(
        self,
        nurse_tokens: List[NurseToken],
        day_tokens: List[DayToken],
        shift_tokens: List[ShiftToken],
        pair_matrix: torch.Tensor,
        mask: Optional[torch.Tensor] = None
    ) -> torch.Tensor:
        """순방향 계산"""
        n_nurses = len(nurse_tokens)
        n_days = len(day_tokens)
        n_shifts = len(shift_tokens)
        batch_size = n_nurses * n_days
        
        # 토큰 벡터화 및 차원 확인
        nurse_vecs = torch.stack([n.to_vector() for n in nurse_tokens])
        day_vecs = torch.stack([d.to_vector() for d in day_tokens])
        shift_vecs = torch.stack([s.to_vector() for s in shift_tokens])
        
        # 실제 차원 출력 (디버깅용)
        print(f"실제 차원 - Nurse: {nurse_vecs.shape[1]}, Day: {day_vecs.shape[1]}, Shift: {shift_vecs.shape[1]}")
        print(f"데이터 크기 - Nurses: {n_nurses}, Days: {n_days}, Shifts: {n_shifts}")
        
        # Query 생성 (간호사 × 일자)
        Q = []
        for nurse_vec in nurse_vecs:
            for day_vec in day_vecs:
                Q.append(torch.cat([nurse_vec, day_vec]))
        Q = torch.stack(Q)  # [batch_size, query_dim]
        
        # 실제 Q 차원 출력 (디버깅용)
        print(f"Q 텐서 차원: {Q.shape}, W_Q 가중치 차원: {self.W_Q.weight.shape}")
        
        # Key/Value 생성 (근무 × 페어)
        K = []
        V = []
        
        # 페어 매트릭스 평균 계산 (차원 조정)
        pair_features = pair_matrix.mean(dim=0).mean(dim=0)  # [pair_dim]
        
        for shift_vec in shift_vecs:
            # 각 시프트에 대해 페어 특성 결합
            K.append(torch.cat([shift_vec, pair_features]))
            V.append(torch.cat([shift_vec, pair_features]))
            
        K = torch.stack(K)  # [n_shifts, key_dim]
        V = torch.stack(V)  # [n_shifts, key_dim]
        
        # 실제 K 차원 출력 (디버깅용)
        print(f"K 텐서 차원: {K.shape}, W_K 가중치 차원: {self.W_K.weight.shape}")
        
        # 멀티헤드 어텐션 계산
        Q = self.W_Q(Q).view(batch_size, self.n_heads, self.head_dim)  # [batch, n_heads, head_dim]
        K = self.W_K(K).view(n_shifts, self.n_heads, self.head_dim)    # [n_shifts, n_heads, head_dim]
        V = self.W_V(V).view(n_shifts, self.n_heads, self.head_dim)    # [n_shifts, n_heads, head_dim]
        
        # 수정된 어텐션 계산 (차원 불일치 처리)
        scores = torch.zeros(batch_size, self.n_heads, n_shifts, device=Q.device)
        
        for i in range(batch_size):
            for h in range(self.n_heads):
                for j in range(n_shifts):
                    # 각 간호사-일자 조합과 각 시프트 간의 유사도 계산
                    scores[i, h, j] = torch.dot(Q[i, h], K[j, h]) / np.sqrt(self.head_dim)
        
        # 마스크 적용
        if mask is not None:
            scores = scores.masked_fill(mask == 0, -1e9)
        
        # Softmax
        attn = F.softmax(scores, dim=-1)  # [batch, n_heads, n_shifts]
        attn = self.dropout(attn)
        
        # 헤드별 가중치 적용
        weighted_attn = attn * self.head_weights.view(1, -1, 1)
        
        # 가중합 계산
        output = torch.zeros(batch_size, self.n_heads, self.head_dim, device=Q.device)
        for i in range(batch_size):
            for h in range(self.n_heads):
                # 각 간호사-일자 조합에 대해 모든 시프트의 가중 합 계산
                weighted_sum = torch.zeros(self.head_dim, device=Q.device)
                for j in range(n_shifts):
                    weighted_sum += weighted_attn[i, h, j] * V[j, h]
                output[i, h] = weighted_sum
        
        # 헤드 결합 & 최종 변환
        output = output.view(batch_size, -1)
        return self.W_O(output)  # [batch_size, 1]

    def generate_constraint_mask(
        self,
        nurse_tokens: List[NurseToken],
        day_tokens: List[DayToken],
        shift_tokens: List[ShiftToken],
        previous_assignments: torch.Tensor,
        config: 'NurseRosterConfig'
    ) -> torch.Tensor:
        """제약조건을 마스크로 변환"""
        batch_size = len(nurse_tokens) * len(day_tokens)
        n_shifts = len(shift_tokens)
        mask = torch.ones(batch_size, self.n_heads, n_shifts)
        
        # OFF 인덱스 미리 찾기
        off_idx = next(k for k, s in enumerate(shift_tokens) if s.shift_type == 'OFF')
        night_idx = next(k for k, s in enumerate(shift_tokens) if s.shift_type == 'N')
        day_idx = next(k for k, s in enumerate(shift_tokens) if s.shift_type == 'D')
        
        for i, nurse in enumerate(nurse_tokens):
            for j, day in enumerate(day_tokens):
                batch_idx = i * len(day_tokens) + j
                
                # 각 간호사의 현재까지 휴무일 수 계산
                total_off_days = previous_assignments[i, :day.day_index + 1, off_idx].sum()
                
                # 현재까지의 전체 일수
                total_days_so_far = day.day_index + 1
                
                # 전체 월의 일수 (31일 가정)
                total_days_in_month = 31
                
                # 1. 휴무일 분배 제약
                max_allowed_off = config.global_monthly_off_days + config.standard_personal_off_days + config.max_additional_off_days
                
                # 현재 시점까지 예상되는 최대 허용 휴무일
                expected_off_ratio = max_allowed_off / total_days_in_month
                expected_off_days = expected_off_ratio * total_days_so_far
                
                # 휴무일이 이미 많은 경우 OFF 마스크 0으로 설정 (금지)
                if total_off_days >= expected_off_days * 1.2:  # 20% 이상 많으면 OFF 금지
                    mask[batch_idx, :, off_idx] = 0
                
                # 2. 야간 연속 근무 제한
                if day.day_index >= 2:
                    prev_nights = previous_assignments[i, day.day_index-2:day.day_index, night_idx].sum()
                    if prev_nights == 2:  # 이전 2일 연속 야간
                        mask[batch_idx, :, night_idx] = 0
                
                # 3. 야간→주간 제한
                if day.day_index > 0 and previous_assignments[i, day.day_index-1, night_idx] == 1:
                    mask[batch_idx, :, day_idx] = 0
                
                # 4. 경험자 필수 근무
                if nurse.experience_years < config.min_experience_per_shift:
                    for k, shift in enumerate(shift_tokens):
                        if shift.shift_type in ['N', 'E']:
                            mask[batch_idx, :, k] = 0
                
                # 5. 7일 연속 근무 제한
                if day.day_index >= 6:
                    prev_work = previous_assignments[i, day.day_index-6:day.day_index].sum(axis=1)
                    if prev_work.all():  # 이전 6일 연속 근무
                        # 이 경우만 OFF 마스크 1로 설정 (허용)
                        mask[batch_idx, :, off_idx] = 1  # OFF만 허용
                        mask[batch_idx, :, :off_idx] = 0
                        mask[batch_idx, :, off_idx+1:] = 0
                
                # 6. 3일 연속 OFF 제한
                if day.day_index >= 2:
                    prev_offs = previous_assignments[i, day.day_index-2:day.day_index, off_idx].sum()
                    if prev_offs == 2:  # 이전 2일 연속 휴무
                        mask[batch_idx, :, off_idx] = 0  # 3일째 OFF 금지
                
                # 7. 간호사 유형 최적화
                if nurse.is_night_nurse and mask[batch_idx, :, night_idx].any():
                    # 야간 전담 간호사는 야간 근무 선호
                    non_night_indices = [k for k, s in enumerate(shift_tokens) 
                                       if s.shift_type != 'N' and s.shift_type != 'OFF']
                    
                    # 야간 근무 확률 증가를 위해 다른 근무의 마스크 값 감소
                    for idx in non_night_indices:
                        mask[batch_idx, :, idx] *= 0.5
                
        return mask

class AttentionBasedRosterGenerator:
    """어텐션 기반 근무표 생성기"""
    def __init__(
        self,
        roster_system: 'RosterSystem',
        n_heads: int = 4,
        learning_rate: float = 1e-4
    ):
        self.roster_system = roster_system
        self.nurses = roster_system.nurses
        self.config = roster_system.config
        self.num_days = roster_system.num_days
        
        # 토큰 생성
        self.nurse_tokens = [
            NurseToken(
                experience_years=nurse.experience_years,
                is_night_nurse=nurse.is_night_nurse,
                is_head_nurse=nurse.is_head_nurse,
                remaining_off_days=nurse.remaining_off_days,
                nurse_id=nurse.id
            )
            for nurse in self.nurses
        ]
        
        self.day_tokens = [
            DayToken(
                day_index=i,
                is_weekend=(i % 7) >= 5,
                is_holiday=False  # TODO: 공휴일 정보 추가
            )
            for i in range(self.num_days)
        ]
        
        self.shift_tokens = [
            ShiftToken(shift_type=shift)
            for shift in self.config.shift_types
        ]
        
        # 실제 벡터 차원 확인
        sample_nurse_vec = self.nurse_tokens[0].to_vector()
        sample_day_vec = self.day_tokens[0].to_vector()
        sample_shift_vec = self.shift_tokens[0].to_vector()
        
        actual_nurse_dim = sample_nurse_vec.shape[0]
        actual_day_dim = sample_day_vec.shape[0]
        actual_shift_dim = sample_shift_vec.shape[0]
        
        # 페어 매트릭스 초기화 (임시로 랜덤 값 사용)
        self.pair_dim = 16
        self.pair_matrix = torch.randn(len(self.nurses), len(self.nurses), self.pair_dim)
        
        # 어텐션 모델 초기화 (실제 차원 사용)
        self.model = MultiHeadAttentionScheduler(
            n_heads=n_heads,
            nurse_dim=actual_nurse_dim,
            day_dim=actual_day_dim, 
            shift_dim=actual_shift_dim,
            pair_dim=self.pair_dim
        )
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=learning_rate)
        
    def generate_roster(self) -> np.ndarray:
        """근무표 생성"""
        print("\n어텐션 기반 근무표 생성 시작...")
        
        # 초기 근무표
        roster = np.zeros((len(self.nurses), self.num_days, len(self.config.shift_types)))
        
        # 각 일자에 대해 순차적으로 처리
        for day in range(self.num_days):
            print(f"\r{day+1}일차 처리 중...", end="")
            
            # 제약조건 마스크 생성
            mask = self.model.generate_constraint_mask(
                self.nurse_tokens,
                [self.day_tokens[day]],
                self.shift_tokens,
                roster,
                self.config
            )
            
            # Night Nurse는 D 시프트 절대 불가능하도록 마스크 수정
            day_idx = self.config.shift_types.index('D')
            for nurse_idx, nurse in enumerate(self.nurses):
                if nurse.is_night_nurse:
                    # 야간 전담 간호사는 절대 주간 근무를 할 수 없음
                    mask[nurse_idx * 1, :, day_idx] = 0
            
            # 어텐션 스코어 계산
            scores = self.model(
                self.nurse_tokens,
                [self.day_tokens[day]],
                self.shift_tokens,
                self.pair_matrix,
                mask
            )
            
            # scores 출력 디버깅 (형상 확인)
            print(f"\rDay {day+1}: scores 텐서 형상: {scores.shape}")
            
            # 점수 재구성: [batch_size, 1] -> [n_nurses, n_shifts]
            # batch_size는 n_nurses * 1 (1개 일자만 처리)
            
            # 문제: scores는 [n_nurses, 1] 형태이지만 우리는 [n_nurses, n_shifts] 형태가 필요합니다
            # 임시 해결책: 모든 교대에 대해 동일한 기본 점수 사용 + 마스크 적용
            n_shifts = len(self.config.shift_types)
            # 각 간호사에 대해 각 교대별 기본 점수 생성 (0.5로 초기화)
            base_scores = torch.ones((len(self.nurses), n_shifts)) * 0.5
            
            # scores 값을 전체 교대에 전파 (scores는 [n_nurses, 1])
            for n_idx in range(len(self.nurses)):
                base_scores[n_idx] = base_scores[n_idx] * scores[n_idx, 0]
                
            # 마스크 적용하여 유효하지 않은 교대는 매우 낮은 점수로
            for n_idx in range(len(self.nurses)):
                for s_idx in range(n_shifts):
                    # 마스크가 0인 곳은 점수를 -100으로 설정 (효과적으로 제외)
                    if mask[n_idx * 1, 0, s_idx] == 0:
                        base_scores[n_idx, s_idx] = -100.0
                        
            # 재구성된 점수를 사용
            reshaped_scores = base_scores
            
            # D, E, N 교대 요구 사항을 추적하기 위한 카운터
            shift_counts = {shift: 0 for shift in self.config.daily_shift_requirements}
            
            # 첫 번째 패스: 교대별 필수 인원 우선 할당
            for shift, required in self.config.daily_shift_requirements.items():
                shift_idx = self.config.shift_types.index(shift)
                
                # 해당 시프트에 적합한 간호사 선택
                eligible_nurses = []
                for nurse_idx, nurse in enumerate(self.nurses):
                    # 야간 전담 간호사는 D 교대 불가
                    if shift == 'D' and nurse.is_night_nurse:
                        continue
                        
                    # 할당 가능한지 확인 (마스크가 허용하고 아직 할당되지 않음)
                    if mask[nurse_idx * 1, 0, shift_idx] > 0 and not np.any(roster[nurse_idx, day]):
                        # 재구성된 점수 사용
                        score = reshaped_scores[nurse_idx, shift_idx].item()
                        eligible_nurses.append((nurse_idx, score))
                
                # 점수 기준 내림차순 정렬
                eligible_nurses.sort(key=lambda x: x[1], reverse=True)
                
                # 필요 인원만큼 할당
                for i in range(min(required, len(eligible_nurses))):
                    nurse_idx = eligible_nurses[i][0]
                    roster[nurse_idx, day, shift_idx] = 1
                    shift_counts[shift] += 1
            
            # 두 번째 패스: 남은 간호사들 할당
            for nurse_idx in range(len(self.nurses)):
                # 이미 할당된 간호사 건너뛰기
                if np.any(roster[nurse_idx, day]):
                    continue
                    
                # 마스크된 확률 분포에서 샘플링
                valid_shifts = mask[nurse_idx * 1].any(dim=0)
                nurse = self.nurses[nurse_idx]
                
                # D, E, N 요구사항이 아직 충족되지 않은 경우 해당 교대 우선 배정
                unfilled_shifts = []
                for shift, required in self.config.daily_shift_requirements.items():
                    if shift_counts[shift] < required:
                        # 야간 전담 간호사는 D 교대 불가
                        if shift == 'D' and nurse.is_night_nurse:
                            continue
                        shift_idx = self.config.shift_types.index(shift)
                        if valid_shifts[shift_idx]:
                            unfilled_shifts.append((shift, shift_idx))
                
                if unfilled_shifts:
                    # 아직 요구사항을 충족하지 못한 시프트 중 하나 선택
                    # 재구성된 점수 사용
                    selected = sorted(unfilled_shifts, key=lambda x: -reshaped_scores[nurse_idx, x[1]])[0]
                    shift, shift_idx = selected
                    roster[nurse_idx, day, shift_idx] = 1
                    shift_counts[shift] += 1
                    continue
                
                # OFF에 대한 선호도 조정 (재구성된 점수 사용)
                shift_probs = F.softmax(reshaped_scores[nurse_idx] * valid_shifts, dim=0)
                
                # 야간 전담 간호사는 야간 근무 선호도 상승, D 근무 금지
                if nurse.is_night_nurse:
                    day_idx = self.config.shift_types.index('D')
                    shift_probs[day_idx] = 0 # 데이 근무 확률 0
                    
                    night_idx = self.config.shift_types.index('N')
                    if valid_shifts[night_idx]:
                        shift_probs[night_idx] *= 1.5
                
                # 확률 정규화 및 샘플링
                if shift_probs.sum() > 0:
                    shift_probs /= shift_probs.sum()
                    try:
                        shift_idx = torch.multinomial(shift_probs, 1).item()
                        roster[nurse_idx, day, shift_idx] = 1
                        
                        # D, E, N 카운트 업데이트
                        shift = self.config.shift_types[shift_idx]
                        if shift in shift_counts:
                            shift_counts[shift] += 1
                    except RuntimeError as e:
                        # 샘플링 오류 시 가장 높은 확률 선택
                        print(f"\n샘플링 오류: {e}, 최대 확률 선택으로 대체")
                        shift_idx = torch.argmax(shift_probs).item()
                        roster[nurse_idx, day, shift_idx] = 1
                        
                        shift = self.config.shift_types[shift_idx]
                        if shift in shift_counts:
                            shift_counts[shift] += 1
                else:
                    # 유효한 시프트가 없으면 OFF 할당
                    off_idx = self.config.shift_types.index('OFF')
                    roster[nurse_idx, day, off_idx] = 1
            
            # 교대 요구사항 충족 확인
            for shift, required in self.config.daily_shift_requirements.items():
                shift_idx = self.config.shift_types.index(shift)
                current = np.sum(roster[:, day, shift_idx])
                
                if current < required:
                    print(f"\n경고: {day+1}일 {shift} 교대 인원이 부족합니다 ({current}/{required})")
                    
                    # 부족한 인원 강제 배정 시도
                    missing = int(required - current)  # 정수로 명시적 변환
                    available_nurses = [
                        n_idx for n_idx, nurse in enumerate(self.nurses)
                        if (shift != 'D' or not nurse.is_night_nurse)  # D 교대라면 야간 전담이 아닌 간호사만
                        and (roster[n_idx, day, self.config.shift_types.index('OFF')] == 1)  # OFF로 배정된 간호사만
                    ]
                    
                    if available_nurses and missing > 0:
                        print(f"부족한 {shift} 교대 인원 강제 배정 시도...")
                        for i in range(min(missing, len(available_nurses))):
                            n_idx = available_nurses[i]
                            # OFF에서 해당 교대로 변경
                            roster[n_idx, day] = 0
                            roster[n_idx, day, shift_idx] = 1
                            shift_counts[shift] += 1
                
                elif current > required:
                    print(f"\n경고: {day+1}일 {shift} 교대 인원이 초과되었습니다 ({current}/{required})")
                    
                    # 초과 인원 조정 시도 (OFF로 변환)
                    excess = int(current - required)  # 정수로 명시적 변환
                    if excess > 0:
                        # 해당 교대에 배정된 간호사 찾기
                        assigned_nurses = [
                            n_idx for n_idx in range(len(self.nurses))
                            if roster[n_idx, day, shift_idx] == 1
                        ]
                        
                        # 초과 간호사를 OFF로 배정
                        print(f"초과 {shift} 교대 인원 조정 시도...")
                        # 경험이 적은 간호사부터 OFF로 변경
                        assigned_nurses.sort(key=lambda n_idx: self.nurses[n_idx].experience_years)
                        for i in range(min(excess, len(assigned_nurses))):
                            n_idx = assigned_nurses[i]
                            # 해당 교대에서 OFF로 변경
                            off_idx = self.config.shift_types.index('OFF')
                            roster[n_idx, day] = 0
                            roster[n_idx, day, off_idx] = 1
                            shift_counts[shift] -= 1
        
        print("\n근무표 생성 완료!")
        return roster

    def update_pair_matrix(self, satisfaction_scores: torch.Tensor):
        """페어 매트릭스 업데이트"""
        # 만족도 점수를 기반으로 페어 매트릭스 조정
        n_nurses = len(self.nurses)
        for i in range(n_nurses):
            for j in range(n_nurses):
                if i != j:
                    score = satisfaction_scores[i] * satisfaction_scores[j]
                    self.pair_matrix[i, j] *= (1 + 0.1 * score)  # 점진적 조정
        
        # 정규화
        self.pair_matrix = F.normalize(self.pair_matrix, dim=-1)
