export type Severity = "high" | "medium" | "low";

export interface RoleOption {
  value: string;
  label: string;
  hint: string;
}

export interface Corpus {
  version: string;
  /** Absent from a backend older than the interface; fall back to `version`. */
  label?: string;
  synthetic: boolean;
  bias: string | null;
  coverage: { field: string; label: string; n: number; usable: boolean }[];
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
  capabilities: {
    ocr: boolean;
    clauseClassifier: "rules" | "trained";
    unfairDetector: "rules" | "trained";
  };
}

export interface Norm {
  value: number;
  median: number;
  percentile: number;
  ciLow: number;
  ciHigh: number;
  n: number;
}

export interface Evidence {
  clauseType: string;
  clauseText: string;
  field: string | null;
  term: { value: number | string | boolean; unit: string | null; raw: string } | null;
  norm: Norm | null;
  anchor: {
    value: number;
    comparison: "max" | "min";
    unit: string;
    source: string;
    note: string | null;
    exceeded: boolean;
    applies: boolean;
  } | null;
  directionRationale: string | null;
  missingClause: boolean;
  venueDistanceKm: number | null;
  unfairTypes: string[];
  /** Set when the finding comes from a declared rule rather than data. */
  ruleBasis?: string | null;
}

export interface Finding {
  clauseId: string;
  severity: Severity;
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
  clausesChecked: number;
  corpusLabel: string | null;
  wasOcred: boolean;
  pageCount: number;
  warnings: string[];
  findings: Finding[];
  /** Terms found but judged by nothing: no data, no law, no rule. */
  notChecked?: { clauseId: string; label: string; value: string }[];
  distributions: Record<string, Distribution>;
}
