# Output Templates

Use Korean unless the user requests another language. Keep the answer self-contained and lead with the decision.

## Structural principle

The report follows the three scored questions in order, so valuation and scenarios appear first:

- **Part A. 가격** — what does the current price assume, and is it cheap? (valuation, scenarios)
- **Part B. 펀더멘털** — is the business getting better? (outlook, catalysts, quality, capital return, macro)
- **Part C. 타이밍** — is now the entry point? (technicals, flows, events)
- **Part D. 결론** — risks, invalidation, score assembly, watchpoints, snapshot.

**Bridge rule:** end each Part with a one-line 소결 that states the sub-conclusion AND hands off to the next Part's question (e.g., "자산가치 기준으로는 싸다 — 그런데 싼 데는 이유가 있는지가 다음 질문이다."). This is mandatory; it is what makes the report read as one argument instead of a checklist.

## Initiation mode

Weight the report toward business structure, the growth bridge, the profit bridge, and valuation. Supporting evidence (technicals, flows, shareholder return) goes in the compact appendix.

```markdown
## [회사명] ([티커], [거래소]) — 종합 판단

| 분석 모드 | Initiation | 기준 주가 | [가격 · 날짜 · 종가/지연] |
|---|---|---|---|
| 재무 기준 | [최근 분기] | 컨센서스 기준일 | [YYYY-MM-DD, 출처] |
| 펀더멘털 | X.X/10 | 진입 타이밍 | X.X/10 · 커버리지 XX% |
| 종합 매수매력도 | X.X/10 — [등급] | 신뢰도 | [A-D] |
| 데이터 커버리지 | XX% | 분석 상태 | [확정/잠정/부분/핵심 근거 부족/제한] |

**한 줄 판단:** [무엇이 매력적이고 무엇이 제한하는지]
- 긍정 / 부정 / 결정적 변수: 각 1줄

> **쉽게 말하면:** [새로운 사실 추가 없이 결론만 평이하게]

## Part 1. 사업 구조 — 무엇을 팔아 돈을 버는가

### 1-1. 매출 구조 해부
| 부문/사이트/제품 | 최근 매출 | 비중 | 단가·물량 드라이버 |
[사업부, 공장/사이트, 모달리티, 지역 중 이 회사의 이익엔진에 맞는 축으로 분해]

### 1-2. 매출이 만들어지는 메커니즘
[수주→매출 전환, 가동률, 계약구조, 리드타임 등 이 사업의 매출 생성 규칙. 가능하면 정량 관계식으로]

### 1-3. 고객·지역 구조
[집중도, 상위 고객 비중, 통화 노출]

[시각화 1: 매출 구조·경로]

**소결(1):** [구조 요약 한 줄 + Part 2로의 다리]

## Part 2. 성장 브릿지 — 매출과 이익은 어떻게 변하는가 (핵심)

### 2-1. 매출 브릿지
| 드라이버 | FY0 | FY1E | FY2E | 증분 | 증분 비중 | 근거 |
[기존 기반 + 램프업 항목별 + 신규 모달리티/M&A + 기타 = 합계.
어떤 단일 드라이버가 성장의 최대 지분을 갖는지 명시]

### 2-2. 각 증분의 근거 (산업 × 점유율 × 기술·설비)
[증분마다: 전방시장 규모와 CAGR(출처·전망연도) → 그것을 확보할 설비/기술 → 함의되는 점유율.
산식을 노출할 것: 시장규모 × CAGR × 점유율, 또는 캐파 × 가동률 × 단가]

### 2-3. 회사 CAGR vs 산업 CAGR
[동일하면 '점유율 유지', 상회하면 '점유율 확대'로 명시 —
이것이 프리미엄 배수의 근거가 성장인지 마진인지를 결정한다]

### 2-4. 이익 브릿지
| 항목 | FY0 | FY1E | FY2E | 변동 요인 |
[매출총이익률 → 판관비(인건비/감가상각) → OPM → 순이익 → EPS(주식수·희석 포함)]

### 2-5. 컨센서스 모델에 미반영된 것
[최근 M&A, 미착공 설비, 계약 대기 등을 별도 정량화하고 연결 마진 영향까지 계산.
없으면 '없음'이라고 쓸 것]

[시각화 2: 매출·이익 경로와 마진]

**소결(2):** [성장의 실체 한 줄 + Part 3으로의 다리]

## Part 3. 밸류에이션과 시나리오

### 3-1. 피어 비교
| 항목 | 당사 | 피어1 | 피어2 | 피어3 |
[Fwd PER, EV/EBITDA, 성장률, OPM을 같은 기준연도로. 배수 차이를 마진·성장·구조로 설명]

### 3-2. 현재 주가가 전제하는 것
[리버스 DCF, 함의 성장률, 함의 마진, SOTP 잔여가치, 신사업 암묵가치 중 가능한 것으로 정량화.
불가하면 불가하다고 명시]

### 3-3. Bear / Base / Bull
| 시나리오 | 영업 가정 | 방식 | 적정가치 | 현재가 대비 | 발생 조건 |

[시각화 3: 피어 배수 vs 마진·성장]

**소결(3):** [가격 판단 한 줄]

## Part 4. 리스크와 무효화 조건
[가장 강한 반대 논리 + 측정 가능한 무효화 조건 3~4개. 각 조건은 어떤 시나리오를 기각하는지 연결]

## 부록 — 보조 지표 (각 2~3줄)
| 항목 | 요약 |
|---|---|
| 기술적 위치 | [추세·밴드 내 위치·지지/저항 1~2줄] |
| 수급 | [방향과 데이터 시차 1~2줄] |
| 주주환원 | [배당·자사주·환원율 1~2줄] |
| 기타 | [지배구조·ESG 등 결론에 영향 있는 것만] |

## 결론

### 점수 근거
| 구분 | 점수 | 핵심 근거 |

### 다음 확인 포인트
[id | 지표 | 충족 조건 | 기한 | 상태]

#### 재분석 기준 스냅샷
- 분석일 / 기준가격 / 가격 유형:
- 펀더멘털 / 타이밍 / 종합 / 신뢰도 / 분석 상태 / 커버리지:
- 세부 점수 (펀더멘털 6개 · 타이밍 4개, N/A는 N/A로):
- 컨센서스 스냅샷: FY1/FY2 매출·영업이익·EPS, 통화, 기준일, 애널리스트 수
- 밸류에이션 스냅샷: 주요 방법, 현재 배수, 피어 중앙값, 목표 배수, Bear/Base/Bull
- 매출 브릿지 스냅샷: 최대 성장 드라이버와 그 증분, 함의 점유율 전제
- 데이터 기준일: 가격 / 재무 / 컨센서스 / 수급 / 뉴스
- 핵심 논리 / 반대 논리 / 무효화 조건 / 관찰 포인트(구조화 객체)

(이 스냅샷을 프로젝트 파일로 저장하면 다음 업데이트 분석의 기준으로 사용됩니다.)

본 분석은 정보 제공 목적이며 투자 판단과 책임은 투자자 본인에게 있습니다.
```

## Update mode

Keep the response roughly one-third of Initiation mode unless changes are extensive. Same A→B→C→D order applies to the "무엇이 바뀌었나" table rows.

```markdown
## [회사명] 업데이트 — [이전 분석일] 대비
**현재 기준:** [가격, 시점] | 분석 상태: [확정/잠정/부분/핵심 근거 부족/제한]  
**점수:** 펀더멘털 [이전→현재] | 타이밍 [이전→현재] | 종합 [이전→현재]  
**세부 점수 변화:** [변동이 있는 구성 항목만: 예. 전망 5.0→4.0, 기술 2.5→4.0]  
**등급 / 신뢰도:** ...

**결론:** [투자논리가 강화·유지·약화됐는지]
> **쉽게 말하면:** ...

### 무엇이 바뀌었나 (가격·밸류 → 펀더멘털 → 타이밍 순)
| 항목 | 이전 | 현재 | 점수 영향 |

### 기존 관찰 포인트 회수
| id | 지표 | 충족 조건 | 결과 | 판정(met/missed/delayed/not_verifiable) | 다음 단계 |
[이전 스냅샷의 estimate/valuation 스냅샷과 현재 수치를 비교해 EPS·배수·적정가치 변화를 '무엇이 바뀌었나' 표에 반영할 것]

### 새로운 사실과 컨센서스 변화
[지난 분석 이후만]

### 수정된 시나리오와 무효화 조건
[필요할 때만]

### 다음 확인 포인트
...

#### 재분석 기준 스냅샷
...

본 분석은 정보 제공 목적이며 투자 판단과 책임은 투자자 본인에게 있습니다.
```

## Event mode

```markdown
## [이벤트]가 [회사명]에 미치는 영향
**기준 가격/시점:** ...  
**대비 기준:** [직전 스냅샷 YYYY-MM-DD / 스냅샷 없음 → 방향성만 표기하고 ±수치 금지]  
**기존 기대 대비:** 긍정 / 중립 / 부정  
**점수 영향:** [직전 스냅샷이 있을 때만 ±X.X, 없으면 방향(↑/→/↓)만]

**결론:** ...
> **쉽게 말하면:** ...

### 1. 확인된 사실
### 2. 시장 기대와 실제 결과의 차이
### 3. 매출·이익·현금흐름·가치평가 영향
### 4. 일회성인가 구조적 변화인가
### 5. 주가 반응과 수급 해석
### 6. 남은 불확실성과 다음 이벤트

#### 재분석 기준 스냅샷
[이벤트로 점수가 변경된 경우 반드시 갱신 스냅샷 출력]

본 분석은 정보 제공 목적이며 투자 판단과 책임은 투자자 본인에게 있습니다.
```

## Focused mode

Answer only the requested dimension. Do not output an overall score unless enough evidence has been reviewed to support it.

```markdown
## [회사명] — [요청 항목] 결론
**기준:** ...
**판단:** ...
> **쉽게 말하면:** ...

### 핵심 근거
### 비교 또는 계산
### 반대 근거와 한계
### 판단을 바꿀 조건

본 분석은 정보 제공 목적이며 투자 판단과 책임은 투자자 본인에게 있습니다.
```

## Optional visualization (Initiation / Update)

When the user asks for charts or the environment supports cheap chart generation (e.g., code execution with matplotlib), offer up to three visuals — never more:

1. **가격 맥락 차트**: 52주 밴드 + 현재가 + Bear/Base/Bull 적정가치 범위를 한 축에 표시
2. **점수 브레이크다운**: 펀더멘털/타이밍 구성 항목의 가로 막대
3. **밸류에이션 비교**: 피어 대비 핵심 배수 막대

Default is OFF (text only). In code-execution environments matplotlib is cheap; in inline-SVG environments each visual costs meaningful tokens — generate only on request.

## Presentation rules

- Use tables for comparable numerical evidence, not for every section.
- Keep decimals to one place for scores and to economically meaningful precision for financial data.
- Label estimates with `E`, consensus, company guidance, or analyst assumption.
- Distinguish `Fact`, `Consensus`, `Assumption`, and `Inference` when ambiguity could change the conclusion.
- Do not add an exhaustive news list; include only items that affect estimates, valuation, risk, positioning, or catalysts.
- Do not repeat the same rationale in the conclusion, catalyst, macro, and risk sections. A1 states the market's assumption; A3 quantifies it; B2 tests it — each exactly once.
