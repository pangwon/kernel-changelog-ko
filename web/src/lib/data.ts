// 빌드 시점에 저장소의 data/<track>/ JSON을 읽는다. 런타임 API는 없다.
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(process.cwd(), "..");
export const TRACK = process.env.TRACK ?? "ufs";
const DATA_DIR = path.join(ROOT, "data", TRACK);

export type ChangeType = "fix" | "feature" | "hardware" | "performance" | "cleanup" | "docs" | "treewide";
export type Importance = "high" | "medium" | "low";

export interface FileChange {
  path: string;
  status: string;
  in_track: boolean;
  added: number;
  deleted: number;
  area: string | null;
  vendor: string | null;
}

export interface Fix {
  abbrev: string;
  subject: string | null;
  sha: string | null;
  introduced_in: string | null;
}

export interface Commit {
  sha: string;
  release: string;
  author: { name: string; email: string };
  author_date: string;
  commit_date: string;
  subject: string;
  body: string;
  trailers: Record<string, string[]>;
  fixes: Fix[];
  cc_stable: boolean;
  message_id: string | null;
  series_id: string;
  series_index: number | null;
  area: string;
  vendor: string | null;
  vendors: string[];
  files: FileChange[];
  summary_ko: string | null;
  explanation_ko: string | null;
  patch: string;
  patch_bytes: number;
  change_type?: ChangeType;
  importance?: Importance;
  keywords?: string[];
}

export interface Series {
  id: string;
  title: string;
  commits: string[];
  authors: string[];
  areas: string[];
  title_ko: string | null;
  summary_ko: string | null;
}

export interface Highlight {
  title_ko: string;
  description_ko: string;
  commits: string[];
}

export interface Release {
  tag: string;
  prev_tag: string;
  date: string;
  commit_count: number;
  series_count: number;
  areas: Record<string, number>;
  vendors: Record<string, number>;
  highlights_ko: {
    headline_ko: string;
    highlights: Highlight[];
    area_notes: { area: string; summary_ko: string }[];
  } | null;
}

function readJson<T>(file: string): T {
  return JSON.parse(fs.readFileSync(file, "utf-8")) as T;
}

let releasesCache: Release[] | null = null;

/** 최신 릴리스가 앞에 오도록 정렬한 목록. */
export function releases(): Release[] {
  releasesCache ??= readJson<Release[]>(path.join(DATA_DIR, "releases.json")).reverse();
  return releasesCache;
}

const commitCache = new Map<string, Commit[]>();
const seriesCache = new Map<string, Series[]>();

export function commits(tag: string): Commit[] {
  if (!commitCache.has(tag)) commitCache.set(tag, readJson(path.join(DATA_DIR, tag, "commits.json")));
  return commitCache.get(tag)!;
}

export function series(tag: string): Series[] {
  if (!seriesCache.has(tag)) seriesCache.set(tag, readJson(path.join(DATA_DIR, tag, "series.json")));
  return seriesCache.get(tag)!;
}

export function patch(tag: string, commit: Commit): string {
  return fs.readFileSync(path.join(DATA_DIR, tag, commit.patch), "utf-8");
}

/** 트랙 안 파일이 모두 한 벤더(들)에 속하면 그 벤더 목록, core 등 벤더 무관 파일이 섞이면 빈 배열. */
export function vendorOnly(c: Commit): string[] {
  const own = c.files.filter((f) => f.in_track);
  if (own.length === 0 || own.some((f) => !f.vendor)) return [];
  return [...new Set(own.map((f) => f.vendor!))].sort();
}

/** tracks/<id>.toml의 [policy.vendors.X] visible = false 인 벤더 (기본 숨김). */
export function hiddenVendors(): string[] {
  const toml = fs.readFileSync(path.join(ROOT, "tracks", `${TRACK}.toml`), "utf-8");
  const hidden: string[] = [];
  let section = "";
  for (const raw of toml.split(/\r?\n/)) {
    const line = raw.replace(/#.*/, "").trim();
    const sec = line.match(/^\[(.+)\]$/);
    if (sec) section = sec[1];
    const m = section.match(/^policy\.vendors\.([\w-]+)$/);
    if (m && /^visible\s*=\s*false$/.test(line)) hidden.push(m[1]);
  }
  return hidden;
}

export function trackName(): string {
  const toml = fs.readFileSync(path.join(ROOT, "tracks", `${TRACK}.toml`), "utf-8");
  return toml.match(/^name\s*=\s*"(.+)"/m)?.[1] ?? TRACK;
}

export const short = (sha: string) => sha.slice(0, 12);

/** 커밋 제목에서 "scsi: ufs: core: " 같은 서브시스템 접두어를 뗀다. 영역·벤더는 배지로 따로 보여 준다. */
export function cleanSubject(subject: string): string {
  const rest = subject.replace(/^(?:[\w.,/+-]+\s?:\s+)+/, "");
  return rest ? rest[0].toUpperCase() + rest.slice(1) : subject;
}

export const AREA_LABEL: Record<string, string> = {
  core: "core",
  host: "host",
  bindings: "bindings",
  phy: "phy",
  crypto: "crypto",
  docs: "docs",
};
export const AREA_ORDER = ["core", "host", "phy", "crypto", "bindings", "docs"];

export const TYPE_LABEL: Record<ChangeType, string> = {
  fix: "수정",
  feature: "기능",
  hardware: "하드웨어",
  performance: "성능",
  cleanup: "정리",
  docs: "문서",
  treewide: "트리 전반",
};

export const IMPORTANCE_LABEL: Record<Importance, string> = { high: "high", medium: "medium", low: "low" };

export function formatDate(iso: string): string {
  return iso.slice(0, 10);
}
