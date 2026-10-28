# kernel-changelog-ko

리눅스 커널 메인라인 변경사항을 릴리스별로 한국어로 요약·해설합니다. (현재 UFS 트랙)

## 구조

```
tracks/<id>.toml   트랙 정의: 수집 경로, 영역·벤더 분류 규칙, 표시 정책
worker/            수집·생성 파이프라인 (Python 3.11+, 외부 의존성 없음)
data/<track>/      수집 결과
  releases.json      릴리스 목록과 통계
  <tag>/commits.json   커밋 (원문 메시지, 트레일러, 파일별 영역·벤더, 시리즈)
  <tag>/series.json    패치 시리즈 묶음
  <tag>/candidates.json  트랙 경로 밖이지만 UFS를 언급하는 커밋 (검토용)
  <tag>/patches/*.diff   트랙 경로로 제한한 원본 diff
web/               웹사이트 (Astro 정적 생성 + Pagefind 검색)
.cache/linux.git   torvalds/linux 부분 clone (gitignore)
```

## 웹사이트

`data/`를 빌드 시점에 읽어 정적 HTML을 만듭니다. 서버나 API 없이 어떤 정적 호스팅에도 올릴 수 있습니다.

```bash
cd web
npm install
npm run build      # dist/ 생성 + Pagefind 검색 색인
npm run preview    # http://localhost:4321
```

- 페이지: 릴리스 목록(`/`), 릴리스(`/ufs/<tag>/`), 커밋(`/ufs/<tag>/<sha12>/`), 검색(`/search/`).
- 릴리스 페이지는 하이라이트, 영역별 노트, 영역·시리즈별 변경 목록을 보여 줍니다. 영역·유형·중요도 필터와 벤더 숨기기는 브라우저에서 동작합니다.
- 벤더 숨기기는 그 벤더의 파일만 바꾼 커밋만 숨깁니다. core 등을 함께 바꾼 커밋은 그대로 보입니다.
  `tracks/<id>.toml`에 `[policy.vendors.<벤더>] visible = false`를 두면 기본으로 숨겨집니다.
- 커밋 페이지는 한국어(요약·해설), 원문(커밋 메시지), diff 탭으로 나뉩니다.
- 하위 경로에 배포할 때는 `BASE_PATH=/repo-name/ SITE_URL=https://user.github.io npm run build`처럼 지정합니다.
- 검색은 빌드한 사이트에서만 동작합니다 (`npm run dev`에는 색인이 없음).

## 사용법

```bash
cd worker
python -m kclog fetch                    # linux.git 부분 clone 또는 갱신
python -m kclog collect                  # 트랙의 since부터 최신 릴리스까지 수집
python -m kclog collect --release v6.12 --force   # 특정 릴리스 다시 수집
python -m kclog check                    # clone 없이 새 정식 릴리스 확인
python -m kclog update                   # 새 릴리스 fetch·수집 + commits 생성 작업 export
python -m kclog stats                    # 통계
python -m unittest discover -s tests -t .
```

`KCLOG_GIT_DIR` 환경변수로 linux.git 위치를 바꿀 수 있습니다.

## 한국어 요약 생성

요약과 해설은 Claude Code가 만듭니다. 별도 API 키나 과금 없이, 사용 중인 Claude 플랜으로 동작합니다.

```bash
cd worker
python -m kclog gen export commits --release v7.4   # 작업 파일 생성
# Claude Code에 요청: ".cache/gen/ufs/commits 작업을 처리해줘"
python -m kclog gen import commits --model claude-opus-5-5   # 결과 검증 후 반영
```

- 단계는 `commits`(커밋 요약·해설) → `series`(다중 커밋 시리즈 요약) → `release`(릴리스 하이라이트) 순서입니다. 앞 단계가 끝나야 다음 단계 작업이 만들어집니다.
- `export`는 `.cache/gen/<track>/<stage>/`에 단계 지침(`INSTRUCTIONS.md`)과 항목별 입력(`<id>.input.md`)을 씁니다.
  Claude Code는 지침을 따라 같은 폴더에 `<id>.json`을 씁니다.
- `import`는 결과를 출력 스키마로 검증해 통과한 것만 `data/`에 반영하고 작업 파일을 지웁니다. 실패한 항목은 파일이 남아 있으니 고쳐서 다시 import합니다.
- 이미 생성된 항목은 export에서 빠집니다 (`--force`로 다시 포함). 결과에는 생성 모델과 `prompt_version`이 기록됩니다.
- 트리 전반 변경(UFS 파일 비중 50% 미만)과 `policy`에서 `explain = false`인 벤더는 요약만 만듭니다.

## 새 릴리스가 나왔을 때

1. `new-release` workflow가 매주 월요일 upstream 태그를 확인하고, 새 정식 릴리스가 있으면 이슈를 엽니다 (Actions 탭에서 수동 실행도 가능).
2. 로컬에서 `python -m kclog update`로 수집하고 commits 작업을 export합니다.
3. Claude Code로 commits → series → release 순서로 생성·import합니다 (위 "한국어 요약 생성").
4. 커밋해서 push하면 `site` workflow가 테스트하고 사이트를 빌드합니다.

요약이 아직 없는 릴리스도 사이트에 나오며, "요약 준비 중"으로 표시되고 커밋은 원문 제목으로 보입니다.

## GitHub Actions

| workflow | 실행 시점 | 하는 일 |
|---|---|---|
| `site` | main push, PR, 수동 | Python 테스트, 사이트 빌드, `site` 아티팩트 업로드 (14일 보관) |
| `new-release` | 매주 월요일, 수동 | 새 릴리스가 있으면 이슈 생성 |
| `deploy-pages` | 수동만 | GitHub Pages 배포 |

`site` 아티팩트를 내려받아 압축을 풀고 그 폴더에서 `python -m http.server`를 실행하면 로컬에서 볼 수 있습니다.
절대 경로를 쓰므로 `index.html`을 파일로 바로 열면 링크가 동작하지 않습니다.

GitHub Pages로 배포하려면 저장소를 public으로 바꾸거나(무료 플랜) Pro 이상을 쓰고,
Settings > Pages의 Source를 "GitHub Actions"로 둔 뒤 `deploy-pages`를 실행합니다.
push마다 자동 배포하려면 `deploy-pages.yml`의 `on:`에 `push: branches: [main]`을 추가합니다.

## 수집 규칙

- 수집 범위는 트랙의 `since`(UFS: v6.18)부터 최신 정식 릴리스까지입니다. `since`를 올리고 다시 collect하면 그보다 오래된 릴리스는 `releases.json`에서 빠집니다 (`data/<track>/<tag>/` 폴더는 직접 지웁니다).
- 릴리스 vX.Y의 내용은 직전 정식 태그..vX.Y 구간입니다 (rc 제외).
- `git log --full-history`로 경로에 걸리는 non-merge 커밋을 모두 가져옵니다.
- 영역(core/host/bindings/phy/crypto/docs)과 벤더(qcom/exynos/mediatek/...)는 별개 축입니다.
  벤더별 숨김이나 해설 생략은 수집이 아니라 `policy`에서 정합니다.
- `Link:` 트레일러의 message-id(git send-email, b4 형식)로 패치 시리즈를 묶습니다.
- `Fixes:` 대상 커밋이 처음 포함된 릴리스(`introduced_in`)를 계산합니다.
- `fs/ufs`(BSD Unix File System)는 UFS 스토리지와 무관하므로 후보에서 제외합니다.
