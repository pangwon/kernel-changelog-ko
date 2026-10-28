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
.cache/linux.git   torvalds/linux 부분 clone (gitignore)
```

## 사용법

```bash
cd worker
python -m kclog fetch                    # linux.git 부분 clone 또는 갱신
python -m kclog collect                  # 트랙의 since부터 최신 릴리스까지 수집
python -m kclog collect --release v6.12 --force   # 특정 릴리스 다시 수집
python -m kclog stats                    # 통계
python -m unittest discover -s tests -t .
```

`KCLOG_GIT_DIR` 환경변수로 linux.git 위치를 바꿀 수 있습니다.

## 수집 규칙

- 릴리스 vX.Y의 내용은 직전 정식 태그..vX.Y 구간입니다 (rc 제외).
- `git log --full-history`로 경로에 걸리는 non-merge 커밋을 모두 가져옵니다.
- 영역(core/host/bindings/phy/crypto/docs)과 벤더(qcom/exynos/mediatek/...)는 별개 축입니다.
  벤더별 숨김이나 해설 생략은 수집이 아니라 `policy`에서 정합니다.
- `Link:` 트레일러의 message-id(git send-email, b4 형식)로 패치 시리즈를 묶습니다.
- `Fixes:` 대상 커밋이 처음 포함된 릴리스(`introduced_in`)를 계산합니다.
- `fs/ufs`(BSD Unix File System)는 UFS 스토리지와 무관하므로 후보에서 제외합니다.
