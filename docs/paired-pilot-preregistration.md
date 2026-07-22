# Phase 2b Paired Pilot 사전등록 계약

> 계약 버전: `phase2b-pilot-prereg-v1.1`
> manifest schema: `paired-pilot-manifest-v1`
> 상태: construction/validity 계약 고정, 60-task manifest 미작성, 실행 미승인
> 목적: Phase 2a smoke의 통제 원칙을 60-task variance/discordance pilot로 일반화한다.

`v1.1`은 2026-07-22의 result-blind protocol amendment다. project instruction parity를
resource reproducibility에서 분리된 eligibility rule로 만들고, global instruction
context를 manifest 환경 pin으로 추가했다. task/evaluator/agent 결과는 보지 않았다.

## 1. 현재 이 문서가 승인하는 것

이 문서와 [`paired-pilot-manifest-v1.schema.json`](../experiments/schemas/paired-pilot-manifest-v1.schema.json)은
task와 evaluator를 만드는 절차 및 최종 manifest의 형식을 고정한다. 실제 task 60개,
보호 evaluator artifact, 완성된 manifest, agent 실행은 아직 승인하거나 사전등록하지
않는다.

세 artifact를 구분한다.

1. **construction contract**: 지금 고정하는 이 문서와 JSON Schema;
2. **experiment manifest**: task/evaluator validity review가 끝난 뒤 생성하고 결과를
   보기 전에 별도 commit으로 동결할 60-task instance;
3. **run authorization**: manifest validation과 agent-free dry run 뒤 사용자가 별도로
   승인하는 120-execution 실행 기록.

현재 Phase 2a parser/runner는 `paired-pilot-manifest-v1`을 지원하지 않는다. smoke
명령에 이 schema를 넣으면 거부되는 것이 의도한 fail-closed 동작이다. Phase 2b용
validator, planner, runner는 construction contract와 독립 검토가 끝난 뒤 별도 구현한다.

## 2. Pilot 목적과 금지된 해석

계획 단위는 60 task와 Claude Code/Codex의 120 independent execution이다. 이 pilot의
목적은 다음을 추정하는 것이다.

- objective evaluator와 lifecycle pipeline의 validity/coverage;
- complete/discordant/one-sided/incomplete pair 비율;
- language와 task category별 분산 및 희소성;
- infrastructure, evaluator, quota, resource missingness;
- 신규 confirmatory round의 표본수와 보고 가능한 strata.

60-task 결과로 agent 승자, 기본 policy promotion, target-workload aggregate, 언어×범주
cell 순위를 주장하지 않는다. quota 20/20/20은 실험분포이며 실제 workload weight가
아니다. pilot task는 confirmatory round에서 재사용하지 않는다.

## 3. 역할 분리와 blind

최종 manifest는 개인 이름 대신 안정적인 role ID를 기록한다. task author,
evaluator author, validity reviewer의 세 construction 집합은 서로 겹치지 않는다는
attestation을 요구한다. frozen artifact를 다루는 run operator와 analyst는 이 세 역할과
겹치지 않는 편이 좋지만, manifest를 바꿀 수 없고 blind가 유지되면 서로 겹칠 수 있다.

| 역할 | 결과를 보기 전 책임 | 보면 안 되는 것 |
|---|---|---|
| task author | source/provenance, task 문구, acceptance criteria, 예상 수정 범위 | agent별 결과 |
| evaluator author | task 문구만으로 보호 evaluator와 assertion inventory 작성 | agent identity/output |
| validity reviewer | task–assertion 대응, evaluator 완전성, negative control, leakage 검토 | agent별 결과 |
| run operator | frozen manifest 그대로 환경 검증·실행 | evaluator golden artifact 내용 |
| analyst | frozen analysis plan으로 event/result 집계 | 동결 전 agent 결과 |

한 사람이 불가피하게 여러 역할을 맡아야 하면 작업을 진행하지 않고 protocol amendment와
conflict mitigation을 먼저 기록한다. task와 evaluator를 같은 대화에서 동시에 생성한
출력은 독립 construction으로 인정하지 않는다. evaluator author에게 agent 이름, 예상
우열, 과거 smoke 결과를 제공하지 않는다.

## 4. Task set construction

### 4.1 고정 quota와 strata

- native Korean 20;
- native English 20;
- 실제 혼합 언어 지시 20;
- category는 `implementation`, `debugging`, `testing`, `refactoring`,
  `repository-analysis-planning`을 각각 12개 포함;
- language와 category는 marginal reporting strata다. 3×5 cell은 확증 단위로
  사용하지 않는다;
- low-risk, isolated-checkout-only task만 허용한다.

Korean과 English는 상대 언어 task의 단순 번역으로 채우지 않는다. mixed task는
identifier만 영어인 것을 뜻하지 않고 지시·문서·acceptance criteria에서 두 언어가
실제로 필요한 작업이어야 한다. 번역쌍은 별도 language-sensitivity 연구로 분리하고
pilot primary set에 넣지 않는다.

### 4.2 Source와 provenance

각 task는 다음을 결과 확인 전에 고정한다.

- source kind/reference/revision과 선택 이유;
- 원문 언어, native 여부, adaptation 이력, license/사용 조건;
- repository ID, exact commit/tree, fixture path/hash;
- description/objective/constraints와 명시적 acceptance criteria;
- required capability, 예상 resource bucket, exact modified-file allowlist;
- task author role ID와 construction timestamp;
- confirmatory reuse 금지 표시.

실제 이슈나 patch에서 파생한 task는 원래 정답 patch가 agent workspace나 prompt에
노출되지 않게 한다. task source 선택은 특정 agent의 알려진 강·약점을 맞추는 방식이
아니라 사전에 고정한 quota와 eligibility 규칙으로 수행한다. 후보 탈락 row와 사유도
ledger에 남겨 selection bias를 검토할 수 있게 한다.

license/use basis는 **exact candidate revision에 실제로 존재하는 artifact**로 판정한다.
저장소 metadata classifier의 추정이나 현재 default branch의 license를 과거 pinned
revision에 소급 적용하지 않으며, "public repository"라는 사실 자체를 use basis로 보지
않고, 불명확한 custom license를 임의 SPDX identifier로 분류하지 않는다. base와 solution
revision의 license가 다르면 양쪽을 구분해 보고하고 `pass` 처리하지 않는다. 근거가 없어
`license-or-use-basis`를 충족할 수 없는 후보는 `license-or-use-basis-unavailable`로
terminal 처리한다. 이 사유는 공개 저장소에 새 use basis를 부여하지 않고, 충족 불가능한
inclusion criterion이 무기한 `screening`으로 남지 않게 하는 표현일 뿐이다.

### 4.3 제3자 코드의 사용 범위와 공개 경계

**이 저장소는 public MIT 오픈소스다.** 따라서 방법론, 설계 문서, candidate ledger, 판정
사유, 측정치는 **모두 공개된다.** 공개되지 않는 것은 제3자 저장소의 코드, 정답 patch 본문,
agent가 만든 diff, evaluator golden artifact뿐이다. 구분은 "내부냐 공개냐"가 아니라
**어느 artifact가 version control에 들어가느냐**다.

이 성격이 license 범위 판단의 근거다. 오픈소스 프로젝트는 재현 가능성 요구를 받게 되고,
"이 실험을 어떻게 재현하느냐"에 답하려면 fixture나 evaluator를 공개하고 싶어지는 압력이
생긴다. 그 순간 copyleft 조건이 실제로 발동한다. 지금 배포 계획이 없더라도 permissive로
한정해 두면 그때 선택권이 남는다.

이 pilot은 제3자 공개 저장소의 코드를 fixture로 사용한다. license 조건을 실제로 지키려면
**무엇을 하고 무엇을 공개하지 않는지**가 규정돼 있어야 하므로 여기 고정한다.

#### 허용 license 범위 (permissive 한정)

법적 여유를 최대한 확보하기 위해 **재배포 조건이 없는 permissive license만** 사용한다.
`GET /licenses`의 13종 중 다음 7종만 eligible이다.

```text
mit · apache-2.0 · bsd-2-clause · bsd-3-clause · bsl-1.0 · unlicense · cc0-1.0
```

제외: `gpl-2.0` · `gpl-3.0` · `agpl-3.0` · `lgpl-2.1` · `mpl-2.0` · `epl-2.0`.
copyleft와 weak-copyleft는 파생물 배포 시 조건이 발동하므로, 지금 배포 계획이 없더라도
**나중에 계획이 생겼을 때 되돌릴 수 없는 상태를 만들지 않기 위해** 미리 제외한다.

이 축소는 **agent 결과와 무관한 eligibility 판단**이다. 다만 Stage 1의 license별 저장소
개수를 본 뒤에 결정했으므로 result-blind 여부를 정확히 기록한다 — 관측한 것은 license
분포이지 agent 성능이 아니다. Stage 1 수집 결과 자체는 감사 가능성을 위해 원본 그대로
보존하고, eligible 부분집합만 별도로 표시한다.

앞서 "license family 선별은 license type에 따른 불필요한 source selection"이라며 배제했던
판단을 뒤집는다. 그 논리는 **재배포하지 않는다는 전제에서만** 성립하는데, 이 저장소가 public
오픈소스인 이상 그 전제를 계속 유지한다고 장담할 수 없다.

#### 제공자 전송 (미확인 항목)

이 실험은 제3자 저장소 코드를 격리 checkout에 두고 **호스팅 coding agent(Claude Code,
Codex)를 그 위에서 실행**한다. 즉 그 코드가 각 제공자 서버로 전송된다. 다음은 아직
확인하지 않았으며, 60-task 실행 승인 전에 확인해 여기 기록한다.

- 각 제공자의 제출 콘텐츠 학습 사용 여부와 해당 계정·제품의 설정값;
- 데이터 보존 기간;
- 그 전송이 각 저장소 license와 충돌하지 않는지.

permissive 한정으로 좁힌 뒤에는 이 축의 위험도 함께 낮아지지만, 확인 자체를 생략하지 않는다.

**하는 일**: pinned base revision을 격리 checkout으로 materialize하고, 그 안에서 agent를
실행하고, 보호 evaluator로 채점하고, 결과의 식별자와 지표를 기록한다. 모두 로컬 실행이며
파생물을 제3자에게 전달하지 않는다.

**version control에 넣는 것**: 저장소·이슈 URL, base/solution revision, tree hash, 변경 파일
**경로**, license 근거, 판정 사유, 그리고 원문·정답 artifact의 **hash**.

**version control에 넣지 않는 것**: 저장소 코드, 정답 patch 본문, agent가 만든 diff,
evaluator golden artifact. 이들은 로컬 보호 경로에만 둔다.

**license 조건이 달라지는 조건**: 위 경계를 넘어 **fixture·정답 patch·agent 산출물을
재배포하려면** 그 시점에 license 의무가 실제로 발동한다. copyleft 계열(GPL/AGPL/LGPL/MPL/EPL)은
파생물 배포 조건이, permissive 계열(MIT/Apache/BSD)은 저작권 고지 유지가, Apache-2.0은
`NOTICE` 파일 요구가 걸린다. 따라서 **재배포를 계획하게 되면 license 범위 제한을 자의적
선별이 아니라 요건으로 다시 검토**해야 하며, 이 절을 먼저 개정한다.

공개 benchmark에서 가져온 pool(SWE-bench Multilingual 등)은 저장소 license와 별개로
**dataset 자체의 이용 약관**을 따로 확인해야 한다. 아직 확인하지 않았다.

이 문서와 ledger는 제3자 저장소에 대한 판정 사유를 공개한다. 사유는 이 실험의 포함 기준에
대한 기술적 서술로 한정하고 저장소나 작성자에 대한 평가로 쓰지 않는다.

### 4.4 Repository와 환경

repository별 exact commit/tree와 fixture hash를 기록하고 두 agent checkout이 동일한
object에서 만들어졌음을 검증한다. workspace에는 다른 branch/ref, 상대 agent 결과,
보호 evaluator/golden artifact, secret, production credential을 노출하지 않는다.
network, push, production mutation은 허용하지 않는다.

#### Project instruction parity (`v1.1` amendment)

후보의 exact pinned base에서 두 CLI가 자동으로 받는 **project-level effective
instruction**이 의미상 동등해야 한다. 판정은 다음을 분리해 기록한다.

- pinned tree inventory: exact base의 실제 파일·symlink·import 관계;
- behavioral evidence: 특정 CLI/version이 실제 marker를 출력한 discovery case;
- official-document evidence: 실측하지 않은 precedence, traversal, fallback rule;
- unmeasured claim: 위 근거로 결정할 수 없는 나머지 case.

동등하면 `instruction-parity=pass`, 명백히 다르면 `fail`과
`instruction-parity-mismatch`, inventory나 discovery 근거가 불충분하면 `unknown`이다.
default branch prevalence는 작업 우선순위 신호일 뿐 pinned candidate 판정에 쓰지 않는다.
후보 instruction 파일을 삭제·변경해 parity를 만들지 않는다. 이 rule은 project fixture의
동등성만 다루며 `reproducible-within-budget`과 독립이다.

이 amendment의 candidate 판정은 Codex 기본값인
`project_doc_fallback_filenames=[]`를 고정한다. 완성 manifest도 반드시 빈 배열을 가져야 한다.
fallback을 바꾸면 `CLAUDE.md`-only 후보의 판정이 달라질 수 있으므로 단순 환경 변경이 아니라
새 result-blind protocol amendment와 전체 parity 재심사가 필요하다.

`selected-for-task-authoring`은 이 eligibility를 포함한 candidate screening을 통과했다는
**construction queue 상태**다. final pilot task, authored prompt, evaluator, validity review,
manifest 포함, agent 실행을 뜻하지 않는다.

#### Global instruction context (`v1.1` amendment)

2026-07-22 비공개 user-level instruction inventory를 result-blind하게 비교한 결과, 양쪽
global instruction은 존재하지만 의미상 같지 않았다. 개인 환경의 경로, 파일명, import와
내용은 repository에 공개하지 않으며 equivalence 결과만 남긴다. 이 비대칭은 후보 fixture
밖의 environment confounder이고 candidate 파일을 바꿔 보정하지 않는다.

완성 manifest의 `environment.global_instruction_context`는 실행 전에 다음 중 하나를 고정한다.

1. 의미상 동등한 global guidance;
2. 양쪽의 격리된 empty agent home.

어느 경로든 Claude/Codex effective instruction hash, empty Codex fallback 배열, 검증 시각을
기록한다. 알려진 비대칭 상태의 hash만 기록하는 것은 confounder를 문서화할 뿐 gate를 닫지
못한다. 현재 환경은 `gate_status=unresolved`이며 이 gate가 닫히기 전에는 실행하지 않는다.

### 4.5 Licensed-repository-first source frame (Frame B)

기존 Korean-bearing pool은 삭제하거나 재정의하지 않는다. 이 frame은 agent 결과와
무관한 eligibility 실패(license 근거 부재)를 이유로 추가하는 **result-blind
amendment**이며, 기존 pool과 제외 row는 선택 경로 감사를 위해 모두 보존한다. 두 pool은
분리된 `source_pool_id`를 갖고 합산 보고하지 않는다.

`license:` qualifier는 **repository search에만** 사용하고 issue search에서 지원된다고
가정하지 않는다.

#### License 상태 모델

license 판정은 다음 네 상태로 구분한다. repository metadata classifier 결과는
**early-priority cache로만** 쓰고 terminal 판정으로 쓰지 않는다.

| 상태 | 의미 | terminal 근거 |
|---|---|---|
| `classifier-confirmed-spdx` | repository metadata가 SPDX를 보고 | 아님 (revision 확인 필요) |
| `classifier-none-uninspected-tree` | metadata에 license 없음, exact revision 미검사 | **아님** |
| `exact-revision-license-confirmed` | pinned revision artifact에서 사용조건 확인 | 근거 |
| `exact-revision-no-license-basis` | pinned revision의 LICENSE/COPYING/NOTICE/manifest/README를 **모두** 확인했으나 사용조건 없음 | 근거 |

`exact-revision-no-license-basis`는 다섯 경로를 모두 검사했을 때만 부여한다. 일부만
검사했으면 검사 범위를 명시해 기록하고 exclusion 근거로 쓰지 않는다. GitHub classifier는
최종 근거가 아니므로 `selected` 전 exact revision artifact 검사는 항상 필요하다.

#### License keyword 범위

수집 frame은 `GET /licenses` 응답 전체를 snapshot으로 고정해 만든다. eligible 범위는
그와 별개로 §4.3이 permissive 7종으로 한정한다 — frame을 넓게 잡아 감사 가능성을 남기고,
eligibility는 좁게 적용해 법적 여유를 확보한다.

```text
record   API version · retrieval timestamp · 반환된 key/SPDX 전체 목록
         · canonical JSON SHA-256
use      그 snapshot에서 repository search keyword로 사용 가능하다고 검증된 전체 목록
exclude  other · noassertion · null 등 명시적 사용조건을 제공하지 않는 값
freeze   수율을 본 뒤 keyword를 추가하거나 제거하지 않는다
```

사용 가능한 keyword 수를 `L`이라 하고, Stage 1 최대 요청은 `6 × L`이다.
`GET /licenses` snapshot에서 `L = 13`이 확정됐고, 그에 따른 exact query **78개**는 결과를
보기 전에 [`frameb-stage1-queries-2026-07-19.json`](../experiments/frameb-stage1-queries-2026-07-19.json)으로
동결했다. 그 artifact는 query 문자열 전체와 canonical SHA-256, 고정 파라미터, 기록 요건을 담는다.

#### Stage 1 — repository frame

```text
endpoint    GET /search/repositories                        (search bucket)
query       "{KO_TERM}" in:readme,description license:{LICENSE}
            fork:false archived:false created:<=2026-07-18 pushed:>=2025-07-19
sort        updated, order desc
KO_TERM     사용법 · 설치 · 기여 · 개발 · 실행 · 테스트     (6개 고정)
LICENSE     GET /licenses snapshot의 검증된 전체 목록        (L개)
queries     6 × L
cap         query당 100 (첫 페이지), pagination 없음
dedup       repository numeric id
record      query별 total_count · returned · truncated · snapshot SHA-256
```

`sort=updated`는 중립 표본이라는 뜻이 **아니다.** `stars`보다 popularity/maturity 편향을
덜 직접적으로 도입하고, 최근 활동 저장소가 fixture 재현 가능성이 높다는 operational
discovery 기준일 뿐이다. `pushed:>=` cutoff와 `updated` 정렬은 activity bias를 **중복으로**
도입한다. 이 pool을 Korean OSS 대표표본이나 target workload 분포로 해석하지 않는다.

pagination 없는 capped discovery frame이므로 다음을 함께 기록한다.

- `total_count > 100`이면 상위 100개만 포함됐음을 명시한다;
- 누락분을 무작위 표본처럼 해석하지 않는다;
- `updated` rank가 결과 선택에 직접 영향을 준다;
- 부족분을 query 재실행으로 보충하지 않는다.

#### Stage 2 — issue frame

Stage 1이 만든 repository 집합 **안에서만** 검색한다.

```text
sampling    Stage 1 dedup 결과가 150개 이상이면 seed "phase2b-licensed-frame-v1"의
            SHA-256("{seed}:{repository_id}") 오름차순 상위 150; 150개 미만이면 전부
endpoint    GET /search/issues, repository당 정확히 1회      (search bucket)
query       repo:{full_name} is:issue is:closed linked:pr created:<=2026-07-18
sort        created, order desc
cap         repository당 반환 상위 100 (1 page)
korean      title+"\n\n"+body의 Hangul 음절 비율 >= 0.10 이고 Hangul >= 50자
per-repo    candidate 최대 2개, 동일 seed의 SHA-256 rank로 선택
dedup       issue URL, 그리고 기존 411 pool과의 교차 중복 제거
```

Hangul 규칙은 **discovery filter일 뿐 native 판정이 아니다.**
`native-language-source`는 계속 instance별 수동 판정 대상이다.

#### Rate limit 준수

인증 토큰을 사용하지 않는다. 환경에 저장된 credential을 탐색하거나 출력하지 않는다.

GitHub REST의 **core와 search는 별도 bucket**이므로 총 요청을 단일 한도로 계산하지
않는다. 수집 전 read-only `GET /rate_limit`을 호출해 core와 search 각각의
limit/remaining/reset을 snapshot으로 기록한다. 실행 중에는 각 응답의
`x-ratelimit-resource`, `remaining`, `reset`, `retry-after`를 따르고, 403/429를 받으면
reset 이전에 반복 요청하지 않는다. 예상 wall time은 bucket별로 따로 계산해 기록한다.

| bucket | 사용 endpoint |
|---|---|
| core | `/licenses`, `/repos/*/git/trees`, `/repos/*/git/blobs`, `/repos/*/contents` |
| search | `/search/repositories`, `/search/issues` |

#### 기존 pool의 조기 필터

기존 411 pool은 남은 행을 순서대로 전수 review하지 않는다. **repository ID로 dedup한 뒤
license 결과를 repository 단위로 cache해 cheap early filter로만** 쓰고, 동일 repository에
요청을 반복하지 않는다. 이 cache는 우선순위 신호이며 terminal 판정이 아니다.

#### Frame D와 Frame C

Frame D(조직 frame)는 **열지 않는다.** 결과를 보고 특정 기업 목록을 만들지 않으며,
사용하려면 포함 조직을 정하는 외부·객관적 기준, 전체 조직 목록, cutoff,
repo/issue enumeration 규칙, 조직당 cap을 결과 확인 전에 고정해야 한다. 사용하게 되면
B와 분리된 `source_pool_id`를 갖고 mature Korean OSS bias를 known limitation으로 남긴다.

Frame C(native task authoring)는 B pool의 실제 license·native·exact-base·evaluator
수율을 확인할 때까지 보류한다. Korean만 authored task로 채우고 English는 upstream
issue로 채우는 방식은 source-construction confounding이므로 허용하지 않는다.

#### Resource bucket 정의

`paired-pilot-manifest-v1`은 task마다 `estimated_resource_bucket`을 `small` 또는 `medium`으로
요구하지만 두 값의 의미를 정의하지 않았다. Phase 2a는 4개 task가 모두 `small`이라 구분이
필요 없었다. 여기서 **evaluator wall time을 기준으로** 정의한다.

```text
small    보호 evaluator 1회 실행이 30초 이내
medium   보호 evaluator 1회 실행이 30초 초과 120초 이내
```

기준을 시간으로 잡는 이유는 이 schema가 **용량을 제약하지 않기 때문**이다. 디스크·메모리
관련 필드가 manifest schema에 존재하지 않으며, 실제로 강제되는 예산은
`evaluator.timeout_seconds`, `agents.time_limit_seconds`,
`maximum_active_wall_time_seconds`뿐이다. 환경 크기가 큰 toolchain이라도 evaluator가 제한
시간 안에 끝나면 이 실험의 예산을 위협하지 않는다. Phase 2a가 사전 등록해 실제로 사용한
`evaluator.timeout_seconds = 120`을 `medium`의 상한으로 그대로 잇는다.

실측한 절차와 toolchain별 비용, 그리고 evaluator를 workspace 밖으로 뺄 때 생기는 제약은
[provisioned-environment 재현 절차](provisioned-reproduction.md)에 있다.

측정은 **cold 상태**에서 한다. paired runner는 attempt마다 새 checkout을 쓰므로 빌드
캐시나 scratch 디렉터리 재사용을 가정하지 않는다.

`reproducible_within_budget`이 `pass`가 되려면 bucket 배정만으로는 부족하고 §4.5의 조건이
모두 실측돼야 한다. 특히 **base·negative·positive control을 agent 없이 재현**해야 하며,
빌드나 기존 suite가 통과했다는 사실만으로는 negative control을 대신하지 않는다.

#### Quota

60 task와 ko/en/mixed 각 20, category 각 12는 고정 marginal quota다. 수율이 낮다는
이유로 45-task나 불균형 quota로 축소하지 않는다. 충족하지 못하면
**construction incomplete / pilot not authorized**로 보고하고 agent 실행을 시작하지 않는다.

## 5. Evaluator construction

Pilot primary set은 다음 objective mode만 허용한다.

1. deterministic acceptance test;
2. golden output/patch invariant;
3. property/integration evaluator.

human rubric이나 LLM judge가 필요한 task는 pilot primary set에서 제외하거나, 결과를
보기 전 protocol amendment로 별도 exploratory endpoint를 정의한다. 하나의 global judge
또는 언어별 threshold 하나를 objective quality로 대체하지 않는다.

각 evaluator는 다음 계약을 만족한다.

- agent 이름과 output에 blind한 상태에서 task contract만 보고 작성;
- agent-writeable checkout 밖의 read-only artifact로 materialize;
- command, 보호 evaluator root 기준 상대 artifact path/mode/hash, version, timeout 고정;
- 모든 assertion에 stable ID, requirement, task field와 literal contract text 매핑;
- `assertion_inventory_complete=true` reviewer attestation;
- base fixture에서 의도한 missing behavior 때문에 실패하는 negative control;
- 알려진 유효 solution 또는 property fixture를 판별하는 positive/sanity control;
- 실행 전후 artifact hash 동일성 검증;
- lint/typecheck/process completion을 objective quality와 분리.

`testing` task는 agent가 작성한 test로 자기 자신을 증명하지 않게 held-out buggy
implementation, mutation target 또는 외부 hidden test를 사용한다. 이 경계를 만들 수
없으면 해당 task를 포함하지 않는다.

## 6. Validity review gate

validity reviewer는 agent 결과 없이 task별로 다음을 확인하고 role ID와 timestamp를
manifest에 attest한다.

- evaluator의 모든 assertion이 task 문구에 실제로 요구됐는가;
- task의 모든 acceptance criterion이 evaluator assertion으로 검사되는가;
- evaluator가 문서에 없는 top-level key, 경로, formatting을 요구하지 않는가;
- golden artifact나 답이 workspace/prompt/visible Git ref로 새지 않는가;
- negative control 실패 이유가 의도한 missing behavior인가;
- positive/sanity control이 evaluator false-negative를 탐지하는가;
- allowlist가 task에 필요한 최소 범위이며 glob이나 절대 경로가 없는가;
- 특정 agent CLI 출력 형식·언어 스타일을 품질로 보상하지 않는가;
- task source와 evaluator source가 confirmatory holdout을 소모하지 않는가.

불일치가 하나라도 있으면 task/evaluator version을 올리고 모든 control과 review를 다시
수행한다. review 뒤 artifact를 수정하면 기존 attestation은 무효다.

## 7. Manifest와 분석 계약

machine-readable schema는 다음을 강제하거나 명시적으로 attest하게 한다.

- 정확히 두 agent와 60 task/120 maximum execution;
- Korean/English/mixed 각각 정확히 20 task;
- 다섯 category의 포함과 task별 provenance;
- exact environment/repository/agent/evaluator identity;
- project instruction parity와 global effective-instruction inventory/hash pin;
- role separation, result blindness, evaluator validity review;
- deterministic balanced order와 stable pair/execution/attempt identity rule;
- primary paired objective-quality risk difference;
- reliability, safety/constraint, resource, scope, evaluator coverage의 분리;
- quality/cost/resource missing을 0이나 pass로 대체하지 않는 규칙;
- stopping/pause/exclusion/resume과 untouched suffix 보존;
- pilot task의 confirmatory reuse 금지와 별도 target-workload weight gate;
- manifest 밖의 별도 run authorization.

JSON Schema만으로 task ID/repository ID의 key-level uniqueness, task의
`task_set_version` 일치, 참조 무결성, 역할 ID 집합의 disjointness, artifact hash 계산,
task별 최대 실행 수와 전체 budget 관계는 완전히 증명할 수 없다. Phase 2b semantic
validator가 이 항목을 추가로 검사해야 한다.

## 8. 실행 전 agent-free gate

완성된 manifest를 version control에 동결한 뒤에도 실행은 자동 승인되지 않는다.
별도 validator/dry run이 다음을 모두 통과해야 한다.

1. JSON Schema와 semantic invariant validation;
2. source repository clean 상태와 exact commit/tree/fixture hash;
3. protected evaluator path/mode/version/hash와 negative-control evidence;
4. 120개 unique workspace/attempt identity와 balanced order projection;
5. agent 호출 없는 120-checkout materialization 및 격리 검증;
6. synthetic complete/discordant/one-sided/incomplete projection golden test;
7. missing quality/cost/resource와 unexpected-file aggregation golden test;
8. partial finalized prefix와 untouched suffix resume rehearsal;
9. installed model/CLI/permission/environment epoch 및 resource budget check;
10. project instruction parity 재검증과 manifest에 pin한 global instruction context 일치;
11. manifest commit 이후 task/evaluator/analysis artifact가 바뀌지 않았다는 audit.

그 뒤 사용자에게 exact manifest commit, 예상 최대 시간·실행 수, CLI quota 상태,
protected workspace/control path, 중단 규칙을 제시하고 120 execution을 별도로 승인받는다.

## 9. 실행·중단·재개 원칙

- secret/production/network/push, base/evaluator hash mismatch, 격리 실패는 즉시 중단;
- permission/sandbox/quota/infrastructure one-sided failure는 row를 finalized하고 pause;
- agent failure/timeout/interruption은 편의상 제외하지 않음;
- fixture 자체가 양쪽 실행 전 깨진 경우만 사전 exclusion rule로 제외;
- finalized prefix를 수정·삭제하지 않고 materialize되지 않은 untouched suffix만 재개;
- quality 미관측은 `missing`, cost 미노출은 `unknown`, terminal 없음은 `incomplete`;
- missing을 quality 0/pass나 cost 0으로 impute하지 않음;
- 모든 exclusion, pause, resume, protocol deviation을 공개.

## 10. 완료 정의와 다음 작업

construction 단계 완료 조건은 다음과 같다.

- [x] construction/validity workflow와 machine-readable schema 동결;
- [x] source candidate ledger schema와 inclusion/exclusion rule 작성;
- [ ] 양쪽 global instruction context 동등화/격리 및 effective hash pin;
- [ ] source pool screening 완료 및 candidate ledger 동결;
- [ ] 역할을 분리해 native task 60개 작성;
- [ ] 보호 evaluator 60개, assertion inventory, negative/positive control 작성;
- [ ] 독립 validity review 완료;
- [ ] 완성된 manifest instance와 semantic validator 작성;
- [ ] agent-free validation/dry run 결과 검토;
- [ ] 별도 120-execution 승인.

따라서 이 문서 다음의 실제 작업은 runner 실행이 아니라
[source candidate ledger](paired-pilot-candidate-ledger.md)의 pool을 완성·동결하고
global instruction gate를 닫은 뒤 **역할 분리된 task construction package**를 만드는
것이다. 현재 작업 순서와 snapshot은
[진행상황의 현재 재개 지점](adaptive-routing-progress.md#현재-재개-지점과-고정-작업-순서-2026-07-22)을
단일 진입점으로 사용한다. 두 construction gate가 닫히기 전에는 task authoring이나
Phase 2b agent 실행을 시작하지 않는다.
