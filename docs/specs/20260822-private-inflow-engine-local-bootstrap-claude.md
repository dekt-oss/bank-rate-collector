# HANDOFF — Confidential Inflow Engine 로컬 Git 저장소 부트스트랩

- Date: 2026-08-22
- 목적: Claude Code가 사용자 Windows PC에서 **공개 `bank-rate-collector`와 완전히 분리된 로컬 전용 Git 저장소**를 만들고, 향후 내부 수신실적 기반 calibration/backtest/inference 엔진을 안전하게 개발할 기반을 구축한다.
- Public Source of Truth: `dekt-oss/bank-rate-collector` Issue #167 / PR #168
- Public calculation guide: `docs/specs/20260822-inflow-structural-v1-calculation-guide.md`
- Public evidence registry: `docs/specs/20260822-inflow-structural-v1-evidence-registry.md`
- 사용자 승인 상태: **로컬 private Git 저장소 생성 승인됨**
- 실제 내부자료: **아직 미수령 / 이번 작업에서 사용하지 않음**

---

# 0. 최우선 보안 규칙

이 작업은 공개 GitHub repository와 내부자료가 섞이지 않게 하는 것이 최우선이다.

## 절대 금지

1. `dekt-oss/bank-rate-collector` 공개 repo 내부 또는 하위 디렉터리에 private engine을 생성하지 않는다.
2. 실제 내부 Excel/CSV/DB/model artifact를 Git에 commit하지 않는다.
3. 이번 단계에서 GitHub/GitLab/외부 Git remote를 추가하지 않는다.
4. `git push`하지 않는다.
5. 실제 내부자료를 public repo, public GitHub Actions, cloud AI, 외부 SaaS에 업로드하지 않는다.
6. 실제 source-specific 내부 sheet명/column명/상품식별자를 public repo에 기록하지 않는다.
7. 사용자의 별도 승인 없이 private repository를 외부 서비스에 생성하지 않는다.

## 완료 시 반드시 증명할 것

```powershell
git remote -v
```

출력이 **비어 있어야 한다.**

---

# 1. 먼저 환경을 조사한다

Claude는 작업 전에 현재 PC를 조사한다.

확인:

```powershell
Get-Location
Get-PSDrive -PSProvider FileSystem
Get-Command git
Get-Command python -ErrorAction SilentlyContinue
Get-Command py -ErrorAction SilentlyContinue
Get-Command uv -ErrorAction SilentlyContinue
git --version
```

그리고 현재 경로 주변에 이미 다음 이름의 저장소/폴더가 있는지 확인한다.

- `bank-rate-collector`
- `inflow-engine-private`
- `bank-rate-private-data`

기존 경로가 있으면 덮어쓰지 않는다.

---

# 2. 저장 위치 결정

## 권장 구조

`D:` 드라이브가 존재하고 사용자 쓰기 가능한 경우 우선:

```text
D:\bank-rate-private\
├─ inflow-engine-private\       ← 로컬 Git, 코드만
└─ data\                        ← Git 밖, 실제 내부자료/산출물
   ├─ raw\
   ├─ processed\
   ├─ model-artifacts\
   └─ reports\
```

`D:`가 없으면:

```text
C:\bank-rate-private\
├─ inflow-engine-private\
└─ data\
```

### 중요한 조건

- `inflow-engine-private`와 `data`는 **형제 디렉터리**여야 한다.
- `data`를 Git repository 안에 만들지 않는다.
- public `bank-rate-collector` clone이 로컬에 있더라도 그 하위에 만들지 않는다.

경로 선택이 애매하거나 회사 보안정책상 저장 위치를 판단할 수 없으면 그때만 사용자에게 확인한다.

---

# 3. 로컬 Git 저장소 생성

예시:

```powershell
$Root = "D:\bank-rate-private"
$Repo = Join-Path $Root "inflow-engine-private"
$Data = Join-Path $Root "data"

New-Item -ItemType Directory -Force $Repo | Out-Null
New-Item -ItemType Directory -Force (Join-Path $Data "raw") | Out-Null
New-Item -ItemType Directory -Force (Join-Path $Data "processed") | Out-Null
New-Item -ItemType Directory -Force (Join-Path $Data "model-artifacts") | Out-Null
New-Item -ItemType Directory -Force (Join-Path $Data "reports") | Out-Null

Set-Location $Repo
git init -b main
```

실제 경로는 환경 조사 결과에 맞춘다.

---

# 4. 초기 repository 구조

다음 최소 구조를 만든다.

```text
inflow-engine-private/
├─ README.md
├─ AGENTS.md
├─ pyproject.toml
├─ .python-version
├─ .gitignore
├─ .env.example
├─ configs/
│  └─ public_contract.example.yaml
├─ docs/
│  ├─ architecture.md
│  ├─ data-boundary.md
│  └─ model-governance.md
├─ scripts/
│  └─ check_sensitive_files.py
├─ src/
│  └─ inflow_engine/
│     ├─ __init__.py
│     ├─ contracts/
│     │  └─ public_forecast.py
│     ├─ intake/
│     │  └─ __init__.py
│     ├─ features/
│     │  └─ __init__.py
│     ├─ models/
│     │  └─ __init__.py
│     ├─ backtest/
│     │  └─ __init__.py
│     └─ inference/
│        └─ __init__.py
└─ tests/
   ├─ test_repository_safety.py
   └─ test_public_forecast_contract.py
```

이번 단계에서는 실제 내부자료용 source mapper나 실제 모델 fitting 코드를 구현하지 않는다.

---

# 5. Python 환경

공개 프로젝트와 호환성을 위해 Python 3.12를 우선 사용한다.

`uv`가 있으면:

```powershell
uv python install 3.12
uv venv --python 3.12
```

초기 `pyproject.toml` 최소 의존성:

- `pydantic`
- dev: `pytest`, `ruff`

향후 실제 calibration 단계에서 필요한 라이브러리(`pandas`, `numpy`, `statsmodels`, `scikit-learn` 등)는 **데이터 구조가 확인된 뒤** 추가한다. 지금 무작정 ML stack을 설치하지 않는다.

---

# 6. `.gitignore` — 강한 차단

최소 다음을 차단한다.

```gitignore
# Secrets / local config
.env
.env.*
!.env.example
*.pem
*.key
*.p12
*.pfx

# Internal/raw/derived data
*.xlsx
*.xls
*.xlsm
*.csv
*.tsv
*.parquet
*.feather
*.arrow
*.db
*.sqlite
*.sqlite3
*.duckdb
*.sav
*.dta

# Model artifacts
*.pkl
*.pickle
*.joblib
*.onnx
*.pt
*.pth
*.ckpt
*.bin
*.model

# Reports potentially containing internal statistics
reports/
artifacts/
outputs/

# Python
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.ruff_cache/

# IDE / OS
.vscode/
.idea/
.DS_Store
Thumbs.db

# Explicit local private paths
private-data/
data/
raw/
processed/
model-artifacts/
```

테스트용 fixture가 필요하면 실제 내부자료를 복제하지 않고 `tests/fixtures/synthetic/` 아래 **완전 합성 데이터**만 코드로 생성하거나 작은 JSON fixture로 관리한다.

---

# 7. 데이터 경계

실제 데이터 root는 repository 안에 hard-code하지 않는다.

환경변수:

```text
INFLOW_PRIVATE_DATA_ROOT=D:\bank-rate-private\data
```

실제 값은 `.env` 또는 사용자 로컬 환경에만 두고 `.env`는 Git에서 제외한다.

`.env.example`에는 값 없는 설명만 둔다.

```text
INFLOW_PRIVATE_DATA_ROOT=
```

코드는 이 경로 밖으로 data write를 시도하지 않게 한다.

---

# 8. Public contract와 private model을 분리한다

private repository의 public-facing contract는 현재 public PR #168의 방향을 따른다.

공개로 나갈 수 있는 의미는 최소한 다음뿐이다.

```text
version
generated_at
status
amount_unit
rate_unit
scenarios[]
  rate_pct
  predicted_new_money
  predicted_rollover
  predicted_total
  incremental_total
  surface_interest_delta
  optional lower/upper interval
```

다음은 private runtime 밖으로 나가면 안 된다.

- coefficient
- beta/gamma
- calibration status/detail
- training metrics
- feature importance
- raw feature
- source file/sheet/column
- sample size/detail that reveals internal dataset
- data fingerprint
- model artifact path
- private model registry metadata

초기 `src/inflow_engine/contracts/public_forecast.py`에는 이 allowlist와 fail-closed validation의 **private-side mirror**를 만든다.

단, public repo의 코드를 그대로 복붙해 두 저장소가 독립적으로 drift하게 만들지 않는다. 이번 bootstrap에서는 최소 interface contract와 테스트만 두고, 실제 연결 방식은 public PR #168 merge 이후 별도 단계에서 결정한다.

---

# 9. Sensitive-file pre-commit gate

`.gitignore`만 믿지 않는다.

`scripts/check_sensitive_files.py`를 만들고 **Git index에 올라간 파일**을 검사한다.

최소 거부 대상:

- `.xlsx`, `.xls`, `.xlsm`
- `.csv`, `.tsv`, `.parquet`, `.feather`, `.arrow`
- `.db`, `.sqlite*`, `.duckdb`
- `.pkl`, `.pickle`, `.joblib`, `.onnx`, `.pt`, `.pth`, `.ckpt`
- `.env`, private key/certificate
- `raw/`, `processed/`, `model-artifacts/`, `data/`

예외는 코드/문서와 명시적으로 합성임이 검증되는 `tests/fixtures/synthetic/`만 허용한다.

`.githooks/pre-commit` 또는 동등한 local hook에서 위 script를 실행한다.

```powershell
git config core.hooksPath .githooks
```

hook이 실제로 작동하는지 dummy forbidden file을 index에 올리는 **negative test**를 하고, 실패 확인 뒤 즉시 파일을 삭제한다. 실제 내부자료로 테스트하지 않는다.

---

# 10. README에 현재 모델 상태를 기록한다

README 첫 부분에 다음을 명확히 쓴다.

```text
이 저장소는 내부 수신실적 기반 calibration/backtest/inference를 위한 로컬 전용 저장소다.
현재 실제 내부자료는 포함하지 않는다.
public bank-rate-collector와 Git history/remote를 공유하지 않는다.
실제 데이터는 Git working tree 밖의 INFLOW_PRIVATE_DATA_ROOT에서만 읽는다.
```

그리고 public baseline을 다음처럼 설명한다.

- `inflow-structural-v1`은 uncalibrated structural baseline
- 신규수신: exponential/log-link style multiplier
- 재예치: logistic probability shift
- 현재 low/base/high coefficient는 stress assumption
- private engine은 향후 실제 history로 challenger를 학습·검증
- challenger가 time-based out-of-sample에서 baseline을 이길 때만 승격 후보

---

# 11. `AGENTS.md`에 강제할 규칙

최소 다음을 넣는다.

1. 이 repo는 confidential/local-only다.
2. remote 추가·push는 사용자의 명시적 승인 없이는 금지한다.
3. 실제 internal data를 Git에 추가하지 않는다.
4. 모든 모델 변경은 Current / Target / Evidence를 분리한다.
5. 실제 coefficient를 문헌에서 임의로 가져오지 않는다.
6. 실제 data coverage 확인 전 feature/schema를 확정하지 않는다.
7. time series는 random split하지 않는다.
8. model promotion에는 out-of-sample comparison이 필요하다.
9. public output은 sanitized contract만 허용한다.
10. 검증하지 못한 것은 `미검증`으로 보고한다.

---

# 12. 초기 테스트

이번 bootstrap에서 최소 다음 테스트를 만든다.

## 12.1 Repository safety

- 실제 Git remote가 0개인지 점검 가능한 helper
- forbidden extension/path 목록 테스트
- `.env.example`은 허용, `.env`는 거부
- synthetic fixture 경로는 허용

## 12.2 Public output contract

합성 payload 기준:

- 허용 필드 → PASS
- `beta` → FAIL
- `training_metrics` → FAIL
- `source_file` → FAIL
- `feature_importance` → FAIL
- `predicted_total != new_money + rollover` → FAIL
- NaN / infinity → FAIL

실제 model training은 하지 않는다.

---

# 13. 이번 단계에서 만들지 않을 것

- 실제 Excel mapper
- 실제 내부 column schema
- 실제 고려저축은행 상품 ID map
- 실제 coefficient
- 실제 model artifact
- XGBoost/RandomForest 등의 후보모델
- database
- API server
- cloud deployment
- public dashboard 연결
- external remote

자료가 오기 전에 구조를 과도하게 확정하지 않는다.

---

# 14. 검증 명령

환경에 맞게 실행하되 최소:

```powershell
uv run ruff check src tests scripts
uv run pytest -q
git status --short
git diff --check
git remote -v
git log --oneline --decorate -5
```

`git remote -v`는 비어 있어야 한다.

추가로 다음을 확인한다.

```powershell
git ls-files
```

출력에 data/raw Excel/CSV/DB/model artifact가 하나도 없어야 한다.

---

# 15. 로컬 commit

모든 검증이 통과하면 **로컬 commit만** 만든다.

권장 commit:

```text
chore: bootstrap confidential inflow engine local repository
```

`git push`는 하지 않는다.

---

# 16. Claude의 adversarial self-review

완료 전에 반드시 “내가 실수로 내부자료를 공개할 수 있는 경로가 남았다고 가정”하고 다음을 다시 본다.

- repo가 public clone 내부에 있지 않은가?
- `data`가 `.git` 아래에 있지 않은가?
- Git remote가 정말 없는가?
- `.gitignore`에 빠진 주요 spreadsheet/database/model 확장자가 없는가?
- `git ls-files`에 민감 후보가 없는가?
- pre-commit gate가 실제로 forbidden fixture를 거부했는가?
- README/AGENTS가 future agent에게 local-only 규칙을 충분히 전달하는가?
- public output contract에 private metadata가 들어갈 틈이 없는가?

하나라도 확신할 수 없으면 완료로 선언하지 않는다.

---

# 17. Claude 최종 보고 형식

최종 답변에는 아래를 실제 실행 결과로 보고한다.

## 생성 위치

```text
Private repo: <실제 절대경로>
Private data root: <실제 절대경로>
```

## Git 상태

```text
Branch: main
Remote: none
Latest local commit: <sha>
```

## 검증

| 검증 | 결과 |
| --- | --- |
| Ruff | PASS/FAIL |
| Pytest | PASS/FAIL + count |
| git diff --check | PASS/FAIL |
| git remote -v | EMPTY 확인 |
| git ls-files sensitive audit | PASS/FAIL |
| pre-commit negative probe | PASS/FAIL |

## 미검증

실제 내부자료가 없으므로 다음은 반드시 미검증으로 남긴다.

- 실제 source mapping
- 실제 data quality
- 실제 coefficient
- 예측정확도
- champion/challenger 성능
- dashboard integration

## 다음 단계

사용자가 내부자료를 제공하면 별도 승인 후:

```text
source-specific mapping
→ canonical intake gate
→ leakage/data quality audit
→ feature table
→ time-based baseline/challenger backtest
→ prediction interval
→ promotion decision
```

으로 넘어간다.
