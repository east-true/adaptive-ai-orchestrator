# Adaptive Routing 연구 교차검토

> 기준일: 2026-07-17
> 목적: [Adaptive Routing v2](adaptive-routing-v2.md)의 근거, 반례, 적용 한계를
> 재현 가능하게 남긴다.

## 1. 검토 질문

1. 작업 구성이 한 agent에 유리할 때 생기는 selection bias를 어떻게 다루는가?
2. 2026년 기술은 prompt-only/offline router에서 얼마나 발전했는가?
3. 복잡한 router가 단순 baseline보다 실제로 정확하고 효율적인가?
4. evaluator와 multilingual benchmark 자체가 만든 편향은 무엇인가?
5. coding-agent CLI라는 현재 프로젝트에 바로 옮길 수 있는 부분은 무엇인가?

## 2. 조사 방법과 한계

- contextual bandit/OPE의 고전 연구, 2024~2026 LLM routing, coding-agent routing,
  evaluator bias, multilingual evaluation을 함께 봤다.
- 논문 landing page와 PDF, 공개 repository 같은 1차 자료를 우선했다.
- peer-reviewed conference, workshop, preprint, vendor self-report를 구분했다.
- 서양권만 보지 않기 위해 중국·홍콩·한국·싱가포르·인도·동남아시아 관련
  기관/언어 연구를 의도적으로 추가했다.
- 기관 소재지는 관점 다양성의 proxy일 뿐이다. native task인지, judge와 model
  family가 다양한지가 더 직접적인 증거다.
- 공개 artifact의 존재는 확인했지만 이 저장소에서 각 논문 결과를 로컬
  재현하지 않았다. API/model 비용, benchmark 규모, coding CLI 환경 차이 때문에
  reported gain을 현재 프로젝트의 예상 gain으로 사용하지 않는다.
- 2026-07 논문 일부는 매우 최근 preprint/workshop 결과다. 후속 수정·철회·정식
  출판 여부를 다시 확인해야 한다.

## 3. 기술 변화: 과거에서 2026년까지

### 3.1 2010~2017: 선택편향과 안전한 탐색의 기본 도구

- [LinUCB](https://archives.iw3c2.org/www2010/_lihong/pub/Li10Contextual.pdf)는
  context에 따른 기대 reward와 uncertainty를 이용해 선택한다.
- [Doubly Robust Policy Evaluation](https://arxiv.org/abs/1103.4601)과
  [Counterfactual Risk Minimization](https://proceedings.mlr.press/v37/swaminathan15.html)은
  logging propensity가 있어야 선택되지 않은 action을 제한적으로 평가할 수 있음을
  보여준다.
- [Conservative Contextual Linear Bandits](https://papers.nips.cc/paper_files/paper/2017/hash/bdc4626aa1d1df8e14d80d345b2a442d-Abstract.html)은
  탐색 중 누적 성능 제약을 다룬다.

이 시기의 핵심 교훈은 지금도 유효하다. 선택 확률이 0인 후보의 반사실은 로그만으로
복구할 수 없고, 안전이라는 말을 쓰려면 무엇을 어느 기간에 보장하는지 정확히
정의해야 한다.

### 3.2 2021~2025: offline preference와 cost-aware routing

- [Contextual Bandit Bake-off](https://www.jmlr.org/papers/v22/18-863.html)는
  optimism 계열이 강했지만 단순 greedy도 놀라울 만큼 경쟁력 있었고 Online Cover가
  견고했음을 보고했다. 복잡도 자체가 성능 보장은 아니다.
- [PILOT / Adaptive LLM Routing Under Budget Constraints](https://aclanthology.org/2025.findings-emnlp.1301/)
  는 preference prior와 LinUCB, online knapsack을 결합한다. 그러나 사람
  preference prior도 자체 편향을 가질 수 있다.
- [PAK-UCB](https://proceedings.mlr.press/v267/hu25m.html)은 prompt-aware
  per-arm kernel과 random Fourier feature를 사용한다. 생성 모델 routing에는
  흥미롭지만 coding-agent CLI의 실행·권한·workspace 효과를 직접 검증하지 않는다.
- [Router-R1](https://papers.nips.cc/paper_files/paper/2025/hash/ceaa137fce916aba5c65fceb1309088b-Abstract-Conference.html)은
  단발 선택 대신 multi-round routing/aggregation을 학습한다. 성능 가능성과 함께
  orchestration 비용·안전 표면도 커진다.

변화의 이유는 고정 benchmark preference 분류가 실제 운영의 비용, drift,
feedback loop를 다루지 못했기 때문이다. 다만 대부분은 여전히 stateless model
호출을 가정한다.

### 3.3 2026: agentic·temporal·unseen-model·safety calibration

- [Agent-as-a-Router](https://arxiv.org/pdf/2606.22902)는 coding task에서
  약 10k task와 8개 frontier LLM, orchestrator/verifier/memory를 결합한다.
  routing model의 coding 능력과 routing 능력이 같지 않으며, dimension별 성능
  memory가 유용할 수 있음을 보여준다. [공개 artifact](https://github.com/LanceZPF/agent-as-a-router)가
  있으나 proxy 및 LLM judge, 제한된 step budget, 공개 가격 기반 비용 등 현재
  CLI와 다른 조건이 있다.
- [SWE-Router](https://arxiv.org/pdf/2607.00053)는 prompt-only 정보의 Bayes
  error floor를 지적하고, 저가 모델의 초기 trajectory를 본 뒤 계속하거나 강한
  모델로 올리는 temporal routing을 제안한다. SWE-Bench Verified의 제한된 model
  pair에 대한 workshop/preliminary 결과이며, 약한 reasoning을 강한 모델에
  전달할 때 생기는 bias와 safety 우회 가능성을 스스로 한계로 든다.
- [Online Multi-LLM Selection via Contextual Bandits Under Unstructured Context Evolution](https://ojs.aaai.org/index.php/AAAI/article/view/39672)는
  순차적으로 변하는 black-box context와 myopic regret, budget/position 확장을
  다룬다. [artifact](https://github.com/EntroShape/Online_Multi_LLM)는 notebook과
  Math500/OpenRouter 중심이므로 coding CLI 재현성은 제한적이다.
- [Meta-Router](https://openreview.net/forum?id=r0BFucF2dH)는 gold label과
  preference label 사이의 causal correction을 다룬다. preference를 ground truth로
  놓지 않아야 한다는 현재 설계와 맞는다.
- [UniRoute](https://openreview.net/pdf?id=ka82fvJ5f1)는 model feature vector로
  unseen model routing을 다룬다. model/tier 변경 때 과거 evidence를 그대로 합치지
  말고 transfer prior와 새 environment를 분리해야 한다는 근거가 된다.
- [Conformal LLM Routing with Distribution-Free Safety Guarantees](https://aclanthology.org/2026.acl-srw.70/)
  는 cheap model 사용의 violation rate를 calibration한다. 두 모델과 GSM8K/MMLU
  중심의 student workshop 결과이므로 coding-agent 안전 보장으로 확대 해석하지
  않는다.

2026년의 핵심 발전은 “prompt를 보고 모델 하나 고르기”에서 “실행 중 evidence,
memory, 환경 변화, unseen model, calibration을 포함한 순차 결정”으로 이동한
것이다. 동시에 더 많은 관측과 judge를 쓰기 때문에 evaluator 편향과 운영비가
새로운 병목이 됐다.

## 4. 아시아권·다언어 관점에서 추가된 반례

### 4.1 대규모 benchmark에서도 복잡한 router가 압도적이지 않다

[LLMRouterBench](https://aclanthology.org/2026.findings-acl.1881.pdf)는 중국의
연구기관들이 참여한 ACL 2026 연구로, 391,645 instance, 21 dataset, 33 model,
10 baseline을 비교한다. [공개 repository](https://github.com/ynulihao/LLMRouterBench)도
제공한다.

중요한 부정 결과는 다음과 같다.

- 여러 sophisticated method의 성능이 비슷하고 clustering/no-neural-network
  방법도 경쟁력 있다.
- 성능 향상의 상당 부분은 세밀한 의미 이해보다 coarse domain structure에서
  온다.
- 정답 모델이 3개 이하인 희소 사례에서 상위 router들의 model recall이 낮다.
- 일부 상용 router는 best-single model보다도 못했다.

따라서 초기 연구 감사 snapshot 12개 로그에서 고차원 router를 도입하는 것은
근거가 없다. task type와 language를 명시적으로 층화한 단순 baseline을 먼저
이겨야 한다.

### 4.2 번역 benchmark는 native task를 대신하지 못한다

- [Open Ko-LLM Leaderboard2](https://aclanthology.org/2025.naacl-industry.22.pdf)는
  기존 한국어 benchmark 중 번역 의존과 실제 한국어 사용과의 괴리를 지적하고
  한국어 특화 task를 보강했다.
- [SeaExam/SeaBench](https://aclanthology.org/2025.findings-naacl.341/)는 native
  Southeast Asian question이 번역 question보다 모델을 더 잘 구분할 수 있음을
  보여준다.
- [SEA-HELM](https://aclanthology.org/2025.findings-acl.636/)은 언어뿐 아니라
  문화·안전 축을 분리한다.

현재 프로젝트는 Korean prompt를 English로 번역해 같은 benchmark를 돌리는 것으로
끝내면 안 된다. 실제 Korean repository 문서, 혼합 언어 지시, 한국어 acceptance
criteria가 있는 native task가 필요하다.

### 4.3 LLM judge는 언어별로 같은 기준을 적용하지 않을 수 있다

- [LLM Evaluators are Biased across Languages](https://arxiv.org/abs/2607.14480)는
  의미가 같은 response pair를 23개 언어에서 비교했을 때 pairwise 정확도가 높아도
  언어별 acceptance rate 차이가 크게 날 수 있음을 보고한 2026-07-16 preprint다.
- [Challenges and Recommendations for LLM-as-a-Judge in Multilingual Evaluation](https://arxiv.org/abs/2607.02235)는
  ACL 계열 judge 연구 중 multilingual/low-resource 중심 연구가 매우 적고
  single-judge 과신이 흔함을 지적한다.
- [Humans or LLMs as the Judge?](https://aclanthology.org/2024.emnlp-main.474/)는
  misinformation, gender, authority, beauty 관련 bias와 prompt attack 취약성을
  분석한다.
- [Justice or Prejudice?](https://openreview.net/forum?id=wtscPS2zJH)는 LLM judge의
  여러 systematic bias를 분류한다.

따라서 “test가 없으니 Claude/다른 LLM이 판정”은 중립적 대안이 아니다. agent 이름
blind, 순서 randomization/reversal, judge family 다양화, human gold audit,
언어별 calibration이 필요하다.

단, 2026-07 두 multilingual preprint의 수치와 세부 결론은 잠정적이다. 언어별
calibration 원칙은 이 하루 된 자료 하나가 아니라 2024~2025 judge bias 연구와
native-language benchmark의 공통된 위험 신호에 근거한 보수적 평가 설계다.

### 4.4 산업 운영은 정확도 외에 session/cache를 본다

[GitHub Copilot의 production routing 설명](https://github.blog/ai-and-ml/github-copilot/getting-more-from-each-token-how-copilot-improves-context-handling-and-model-routing/)은
task intent뿐 아니라 실시간 health와 cache boundary를 고려하고, mid-session switch가
cache를 깨뜨릴 수 있음을 설명한다. 16개 language family로 학습하고 19개 언어를
평가했다는 내용도 있다.

이는 유용한 운영 사례지만 peer-reviewed 독립 검증이 아닌 vendor self-report다.
현재 프로젝트에는 “partial trajectory가 더 정확하다”만 옮길 것이 아니라 CLI session
재개 가능성, cache 손실, restart 비용을 직접 계측해야 한다.

## 5. 실패·공격·희소 사례를 포함한 위험 검토

- [Router fragility 연구](https://arxiv.org/abs/2504.07113)는 routing threshold에
  따라 strong model over-routing이 급변하고, category cue와 jailbreak가 weak model
  route를 유도할 수 있음을 보인다.
- 평균 성능이 좋아도 희소한 어려운 task에서 적절한 model을 recall하지 못할 수 있다.
- preference data는 과거 사용자 선택과 노출 정책을 그대로 학습할 수 있다.
- escalation data는 첫 agent 실패 조건부이므로 unconditional 성공률이 아니다.
- agentic trajectory는 prompt-only보다 정보가 많지만 tool action과 safety policy를
  우회할 새로운 표면을 만든다.
- evaluator가 agent output 형식이나 언어 스타일을 선호하면 router가 실제 품질보다
  judge 맞춤 행동을 학습한다.

## 6. 현재 프로젝트에 적용할 것과 보류할 것

### 지금 적용

- evaluator role과 관측 여부를 typed schema로 저장;
- append-only started/terminal/evaluation event;
- policy, eligibility, propensity, cohort 기록;
- native Korean/English/mixed strata;
- 같은 base revision의 paired benchmark;
- static/best-single/층화 greedy를 필수 baseline으로 사용;
- global decision/environment epoch 기반 drift;
- effective sample size와 CI가 부족하면 정책 순위 거부.

### evidence를 모은 뒤 적용

- full-covariance contextual model;
- vendor/tier 계층 transfer;
- partial trajectory continue/escalate;
- conformal risk calibration;
- session/project budget pacing.

충분한 auto traffic과 overlap support가 생긴 뒤에만 적용:

- 최대 0.05에서 시작하는 safe prospective overlap;
- support가 있는 estimand의 IPS/DR policy 평가.

### 현재 보류

- prompt embedding/neural router;
- 임의의 50:50 agent 사용 강제;
- untyped verifier pass를 quality 1로 사용;
- LLM judge 하나를 ground truth로 사용;
- Codex 현금 비용 결측을 0으로 둔 cost optimization;
- diagonal covariance를 엄밀한 LinUCB uncertainty로 표현;
- 현재 legacy 로그 replay로 새 정책의 무회귀를 주장.

## 7. 근거의 신뢰도 요약

| 근거군 | 강점 | 한계 | 설계에서의 무게 |
|---|---|---|---|
| 고전 bandit/OPE | 이론과 장기간 검증 | coding CLI 직접 연구 아님 | propensity/support 원칙에 높음 |
| peer-reviewed router benchmark | 비교 baseline과 재현성 | 정적 QA가 많음 | 모델 선택보다 평가 설계에 높음 |
| 2026 agentic/temporal 연구 | 현재 문제와 가까움 | 최근 preprint/workshop, 제한된 pair | shadow 실험 가설 |
| 아시아 native-language 평가 | 번역/언어 편향 반례 | routing 직접 연구는 적음 | strata/evaluator 설계에 높음 |
| vendor production report | 운영 cache/health 통찰 | 독립 검증 없음 | 계측 항목 가설 |
| 현재 로컬 12건 | 실제 CLI/schema 결함 확인 | propensity/반사실/표본 부족 | 진단과 migration만 |

## 8. 아직 남은 연구 검토

구현을 막지는 않지만 다음 checkpoint에서 갱신한다.

- 2026-07 preprint들의 정식 출판/수정 상태;
- 공개 artifact의 작은 subset 로컬 재현;
- Korean coding-agent native benchmark 또는 공개 patch task의 추가 탐색;
- Claude/Codex CLI session continuation과 cache 계측 가능성;
- subjective judge panel의 비용 대비 실제 human agreement;
- 보안 평가를 포함한 agent routing 연구;
- model/CLI 업데이트 직후 drift detector의 false alarm/검출 지연.

이 항목들은 [진행상황 문서](adaptive-routing-progress.md)에서 구현 checkpoint와
함께 추적한다.
