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
    contributions?: boolean;
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
  /** What the comparison data rests on, for the note under the report. */
  corpusBias?: string | null;
  wasOcred: boolean;
  pageCount: number;
  warnings: string[];
  findings: Finding[];
  /** Terms found but judged by nothing: no data, no law, no rule. */
  notChecked?: { clauseId: string; label: string; value: string }[];
  distributions: Record<string, Distribution>;
}

export interface Span {
  page: number;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export interface Clause {
  id: string;
  type: string | null;
  typeLabel: string | null;
  heading: string | null;
  text: string;
  spans: Span[];
}

export interface Fact {
  value: number | string;
  clauseId: string;
  raw: string;
}

export interface CostLine {
  key: string;
  label: string;
  amount: number | null;
  proRata?: number | null;
  salaryMonths?: number;
  kind: "up_to" | "if_no_notice";
  clauseId: string;
  note: string;
}

export interface Exposure {
  kind: "lease" | "employment";
  horizon: number;
  lockInMonths?: number | null;
  bondMonths?: number | null;
  nonCompeteMonths?: number | null;
  schedule: { month: number; lines: CostLine[]; atRisk: number }[];
  depositHeld?: { amount: number; clauseId: string; days: number | null } | null;
  lateFee?: { pctPerMonth: number; amount: number; clauseId: string } | null;
  rentByYear?: { year: number; rent: number }[];
}

export interface TimelineEvent {
  label: string;
  date: string;
  clauseId: string;
  basis: string;
  stated: boolean;
  kind: "milestone" | "deadline" | "money";
}

export interface Timeline {
  events: TimelineEvent[];
  recurring: {
    label: string;
    dayOfMonth: number;
    clauseId: string;
    from: string | null;
    months: number;
  } | null;
  hasStart: boolean;
}

export interface ShareableFigure {
  key: string;
  label: string;
  value: number;
  unit: string;
}

export interface Report extends AnalysisResult {
  findings: (Finding & { label: string; suggestedWording: string | null })[];
  clauses: Clause[];
  facts: Record<string, Fact>;
  exposure: Exposure | null;
  timeline: Timeline;
  shareable: ShareableFigure[];
}

export type Change = "better" | "worse" | "changed" | "added" | "removed";

export interface Diff {
  figures: {
    key: string;
    label: string;
    unit: string;
    old: number | null;
    new: number | null;
    oldClause: string | null;
    newClause: string | null;
    change: Change;
  }[];
  findings: Record<
    "resolved" | "raised" | "remaining",
    { headline: string; severity: Severity; clauseId: string }[]
  >;
  clauses: {
    modified: { oldId: string; newId: string; similarity: number; oldText: string; newText: string }[];
    added: { id: string; text: string }[];
    removed: { id: string; text: string }[];
    unchanged: number;
  };
}

export interface AskResult {
  answers: { clauseId: string; clauseType: string | null; text: string; score: number }[];
  silent: boolean;
  topics: string[];
}
