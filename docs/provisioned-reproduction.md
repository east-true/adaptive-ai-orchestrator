# Provisioned-environment 재현 절차

> 기준일: 2026-07-19
> 측정 artifact: [`phase2b-provisioning-measurements-2026-07-19.json`](../experiments/phase2b-provisioning-measurements-2026-07-19.json)
> 관련: [사전등록 계약](paired-pilot-preregistration.md) §4.5, [candidate ledger](paired-pilot-candidate-ledger.md)

후보의 `reproducible_within_budget`을 판정하려면 agent 없이 환경을 실제로 만들고
base·negative·positive control을 재현해야 한다. 이 문서는 4개 후보에서 실측한 절차와
비용을 남겨 다음 세션이 다시 탐색하지 않게 한다.

## 1. 원칙

eligibility는 **screening host에 무엇이 깔려 있는지로 판정하지 않는다.** 물어야 할 것은
"대상 플랫폼에 고정 가능한가"다. 반대로 macOS 전용 독점 도구처럼 Linux 경로가 아예 없는
경우는 provisioning 원칙과 무관하게 자원 사유로 제외한다.

manifest schema는 **용량을 제약하지 않는다.** disk·memory 필드가 없고 강제되는 예산은
`evaluator.timeout_seconds`, `agents.time_limit_seconds`,
`maximum_active_wall_time_seconds`뿐이다. 따라서 환경이 커도 evaluator가 제한 시간 안에
끝나면 예산을 위협하지 않는다.

## 2. 절차

### 2.1 Toolchain을 digest로 고정해 격리 설치

sudo 없이 사용자 경로에 푼다. 공개 체크섬이 있으면 반드시 대조한다.

```bash
# Python: python-build-standalone (install_only 변형)
curl -sL "$BASE/cpython-3.11.15+20260718-x86_64-unknown-linux-gnu-install_only.tar.gz" -o py.tgz
sha256sum py.tgz                      # 게시자 SHA256SUMS와 대조
tar xzf py.tgz                        # ./python/bin/python3

# .NET
curl -sSL https://dot.net/v1/dotnet-install.sh | bash -s -- --channel 8.0 --install-dir "$D" --no-path

# Swift
curl -sL "https://download.swift.org/swift-6.3.3-release/ubuntu2204/swift-6.3.3-RELEASE/swift-6.3.3-RELEASE-ubuntu22.04.tar.gz" -o swift.tgz
```

체크섬을 게시하지 않는 배포자(예: Swift는 detached PGP 서명)는 그 사실을 기록하고
"검증했다"고 쓰지 않는다.

### 2.2 Base를 materialize하고 tree hash를 git으로 읽는다

```bash
git init -q . && git remote add origin "https://github.com/$REPO.git"
git fetch -q --depth 1 origin "$BASE_SHA" && git checkout -q FETCH_HEAD
git rev-parse HEAD^{tree}
```

**API의 `GET /git/trees/{commit_sha}`를 tree hash 출처로 쓰지 않는다.** commit SHA를 넘기면
입력 SHA를 그대로 돌려주므로 commit을 tree로 잘못 기록하게 된다. 이 오류는 실제로 3개 행에
들어갔다가 materialize 후 정정됐다.

짧은 SHA만 있으면 `https://github.com/$REPO/commit/$SHORT.patch`의 첫 줄에서 full SHA를
얻는다. `git fetch`는 짧은 SHA를 받지 않는다.

### 2.3 PR 시점 evaluator를 재구성한다

default branch의 테스트를 그대로 쓰면 **그 PR 이후 변경들의 assertion까지 실패**해
negative control이 의도한 이유로만 실패하지 않는다. PR diff에서 테스트 파일 hunk만 뽑아
base 테스트에 적용한다.

```bash
curl -sL "https://github.com/$REPO/pull/$PR.diff" -o pr.diff        # web 호스트, API 한도와 무관
awk '/^diff --git a\/tests\/…/,/^diff --git a\/(?!tests)/' pr.diff > test_only.diff
patch -s -o protected/gold.sh base_test.sh test_only.diff
chmod 0444 protected/gold.sh
```

보호 evaluator는 **agent checkout 밖**에 두고 read-only로 만든다.

### 2.4 Repo-local 컨텍스트를 명시로 주입한다

상류 테스트를 workspace 밖에서 실행하면 저장소에 의존하던 컨텍스트를 잃는다. 실측에서 두
형태가 나왔다.

| 형태 | 증상 | 대응 |
|---|---|---|
| `dirname $0/..`로 repo root 유도 | 소스 파일을 못 찾아 실패 | root를 주입 가능하게 한 줄 수정 |
| pytest가 저장소의 `asyncio_mode = "auto"`를 못 읽음 | async 테스트 전부 "not natively supported" | `-c pyproject.toml --rootdir .` 명시 |

이 적응은 evaluator 제작의 일부이며, **assertion을 바꾸지 않았음을 검토**해야 한다.

### 2.5 Negative → positive control

```bash
# negative: base workspace에 보호 evaluator 실행 → 의도한 assertion만 실패해야 한다
# positive: 구현 파일만 적용한 사본에 같은 evaluator 실행 → 전부 통과해야 한다
```

실행 전후 보호 artifact 해시가 같은지, base workspace가 clean으로 남는지 확인한다.
**빌드나 기존 suite 통과는 negative control을 대신하지 않는다.**

## 3. 실측 비용

| toolchain | 다운로드 | 설치 | 의존성 | provisioning |
|---|---:|---:|---:|---:|
| CPython 3.11.15 | 49MB | 161MB | 0 | 16초 |
| CPython 3.13.14 | 113MB | 378MB | 578MB | 49초 |
| .NET SDK 8.0.423 | — | 578MB | 94MB | 21초 |
| Swift 6.3.3 | 1,019MB | 3,362MB | 129MB | 109초 |

| candidate | base | negative | positive | evaluator | bucket |
|---|---|---|---|---:|---|
| `factlog #26` | 44p/0f | **44p/2f** (의도) | 46p/0f | 2초 | `small` |
| `ante #2349` | 17p | **17p/10f** (의도) | 27p/0f | 1초 | `small` |
| `TimePilot #62` | build 0 warn/0 err | — | — | 8초 | `small` |
| `swift-tui #18` | 1,064 tests pass | — | — | 90초 | `medium` |

`TimePilot`은 `-p:EnableWindowsTargeting=true`로 Linux 빌드가 성공했고, `swift-tui`는 빌드와
1,064개 테스트가 모두 통과했다. 두 후보는 **보호 evaluator를 아직 만들지 않아** control이
없으므로 `reproducible_within_budget`은 `unknown`이다.

## 4. 한계

- 한 호스트·한 네트워크의 측정이라 시간은 달라진다.
- Swift 아카이브는 SHA-256을 기록만 했고 게시자 체크섬 목록과 대조하지 못했다(배포자가
  detached PGP 서명을 제공한다). "검증됨"으로 표기하지 않는다.
- `/tmp` 아래 환경은 휘발성이다. 재구성 가능하게 만드는 것은 여기 적힌 **identity**이지
  디렉터리 자체가 아니다.
- 네 후보 중 둘만 control까지 갖췄다. 나머지 둘의 근거는 더 약하다.
