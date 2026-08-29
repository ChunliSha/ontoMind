export interface EvidenceTriple {
  subject_id: string;
  subject_label: string;
  predicate: string;
  object_id?: string | null;
  object_label?: string | null;
  object_value?: string | null;
}

export interface Evidence {
  id: string;
  kind: string;
  entity_id?: string | null;
  label: string;
  class_label?: string | null;
  properties?: Record<string, unknown>;
  triples?: EvidenceTriple[];
  source_ref?: Record<string, unknown> | null;
}

export interface QaMessage {
  id: string;
  role: 'user' | 'assistant' | string;
  content: string;
  evidences?: Evidence[];
  plan?: Record<string, unknown> | null;
  tool_trace?: Array<Record<string, unknown>>;
  created_at?: string | null;
}

export interface QaSessionSummary {
  id: string;
  ontology_model_id: string;
  llm_model_id?: string | null;
  title: string;
  message_count: number;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface QaSession {
  id: string;
  ontology_model_id: string;
  llm_model_id?: string | null;
  title: string;
  resolved_entities?: Record<string, unknown> | null;
  created_at?: string | null;
  updated_at?: string | null;
  messages: QaMessage[];
}

export interface QaChatResponse {
  session_id: string;
  answer: string;
  evidences: Evidence[];
  plan?: Record<string, unknown> | null;
  tool_trace?: Array<Record<string, unknown>>;
  resolved_entities?: Record<string, unknown> | null;
}

export interface KnowledgeAccessLog {
  id: string;
  created_at?: string | null;
  caller: string;
  tool_name: string;
  ontology_model_id?: string | null;
  session_id?: string | null;
  trace_id: string;
  latency_ms: number;
  empty_hit: boolean;
  error?: string | null;
}
