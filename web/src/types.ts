export type Severity = "high" | "medium" | "low";

export interface RoleOption {
  value: string;
  label: string;
  hint: string;
}

export interface Corpus {
  version: string;
  synthetic: boolean;
  fields: number;
  usable: number;
  bias: string | null;
  coverage: { field: string; n: number; usable: boolean }[];
}

export interface DomainOption {
  value: string;
  label: string;
  weakerParty: string;
  roles: RoleOption[];
  corpora: Corpus[];
}

export interface Config {
  domains: DomainOption[];
  minSampleSize: number;
  capabilities: {
    ocr: boolean;
    clauseClassifier: "rules" | "trained";
    unfairDetector: "rules" | "trained";
  };
  unverifiedAnchors: string[];
}

export interface Norm {
  value: number;
  median: number;
  percentile: number;
  ciLow: number;
  ciHigh: number;
  n: number;
  robustZ: number;
  sufficient: boolean;
}

export interface Evidence {
  clauseType: string;
  clauseText: string;
  field: string | null;
  term: { value: number | string | boolean; unit: string | null; raw: string } | null;
  norm: Norm | null;
  anchor: {
    value: number;
    source: string;
    note: string | null;
    exceeded: boolean;
    applies: boolean;
  } | null;
  directionRationale: string | null;
  asymmetry: boolean;
  missingClause: boolean;
  venueDistanceKm: number | null;
  semanticOutlier: number | null;
  unfairTypes: string[];
}

export interface Finding {
  clauseId: string;
  severity: Severity;
  score: number;
  headline: string;
  plainLanguage: string;
  question: string | null;
  evidence: Evidence;
}

export interface Distribution {
  n: number;
  median: number;
  counts: { value: number; count: number }[];
}

export interface AnalysisResult {
  summary: string;
  clausesChecked: number;
  corpusVersion: string | null;
  wasOcred: boolean;
  pageCount: number;
  lowStructure: boolean;
  role: string;
  warnings: string[];
  findings: Finding[];
  distributions: Record<string, Distribution>;
}
