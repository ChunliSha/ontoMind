export type LlmSource = 'cloud' | 'local';
export type LlmProvider =
  | 'openai'
  | 'azure_openai'
  | 'deepseek'
  | 'qwen'
  | 'zhipu'
  | 'moonshot'
  | 'ollama'
  | 'vllm'
  | 'local_openai'
  | 'custom';
export type LlmStatus = 'active' | 'disabled' | 'failed';

export interface LlmModelRead {
  id: string;
  name: string;
  source: LlmSource;
  provider: LlmProvider;
  api_base: string | null;
  has_api_key: boolean;
  model_name: string;
  is_default: boolean;
  status: LlmStatus;
  last_error?: string | null;
  last_tested_at?: string | null;
  extra_config?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface LlmModelCreate {
  name: string;
  source: LlmSource;
  provider: LlmProvider;
  api_base?: string | null;
  api_key?: string | null;
  model_name: string;
  is_default?: boolean;
  extra_config?: Record<string, unknown> | null;
}

export interface LlmModelUpdate {
  name?: string;
  source?: LlmSource;
  provider?: LlmProvider;
  api_base?: string | null;
  api_key?: string | null;
  model_name?: string;
  is_default?: boolean;
  status?: LlmStatus;
  extra_config?: Record<string, unknown> | null;
}

export interface LlmModelTestResult {
  ok: boolean;
  message: string;
  latency_ms?: number | null;
}

export interface LlmPreset {
  id: string;
  name: string;
  source: LlmSource;
  provider: LlmProvider;
  api_base: string | null;
  model_name: string;
  hint: string;
}
