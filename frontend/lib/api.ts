/**
 * API client for OCR Extraction Platform
 */

import { formatApiErrorDetail } from "./format-api-error";

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

/** Must match use-auth.tsx localStorage keys */
const AUTH_TOKEN_KEY = "idp_auth_token";
const AUTH_USER_KEY = "idp_auth_user";
/** One-time message for login page after session-invalid 401 */
export const LOGIN_FLASH_SESSION_KEY = "idp_login_flash";

let sessionInvalidRedirectScheduled = false;

function detailLooksLikePasswordSessionInvalid(detail: unknown): boolean {
  const text = formatApiErrorDetail(detail, "").toLowerCase();
  return (
    text.includes("session invalidated") ||
    text.includes("password was changed")
  );
}

function clearAuthAndGoToLoginWithFlash(message: string): void {
  if (typeof window === "undefined" || sessionInvalidRedirectScheduled) return;
  sessionInvalidRedirectScheduled = true;
  try {
    localStorage.removeItem(AUTH_TOKEN_KEY);
    localStorage.removeItem(AUTH_USER_KEY);
    sessionStorage.setItem(LOGIN_FLASH_SESSION_KEY, message);
  } catch {
    /* ignore */
  }
  window.location.assign("/login");
}

// Types
export interface Provider {
  name: string;
  display_name: string;
  description: string;
  provider_type: "local" | "cloud";
  cost_tier: "free" | "low" | "medium" | "high";
  requires_api_key: boolean;
  api_key_env_var?: string;
  is_available: boolean;
  error?: string;
  capabilities: string[];
  config_options: Record<string, unknown>;
}

export interface ProvidersResponse {
  ocr_providers: Provider[];
  llm_providers: Provider[];
}

export interface JobPart {
  part_name: string;
  status: "pending" | "processing" | "completed" | "failed";
  extracted_data?: Record<string, unknown>;
  confidence: number;
  error?: string;
  processing_time: number;
  page_range?: number[] | null;
}

export interface FieldCorrectionUpdate {
  path: string;
  value?: unknown;
  page?: number;
  polygon?: number[][];
}

export interface PatchPartFieldsResponse {
  job_id: string;
  part_name: string;
  extracted_data?: Record<string, unknown>;
  cache_synced: boolean;
  message: string;
}

export interface Job {
  id: string;
  status: "pending" | "processing" | "completed" | "failed";
  progress: number;
  current_step: string;
  user_id?: string;
  username?: string;
  document_name: string;
  doc_type: string;
  ocr_provider: string;
  llm_provider: string;
  schema_id?: string;
  workflow_id?: string;
  ocr_model_config?: Record<string, unknown>;
  parts: JobPart[];
  input_tokens: number;
  output_tokens: number;
  estimated_cost: number;
  processing_time?: number;
  error?: string;
  created_at?: string;
  started_at?: string;
  completed_at?: string;
  output_dir?: string;
  document_storage_path?: string;
  has_stored_document?: boolean;
  /** Segmentation profile slug (e.g. invoice) when job is linked to segmentation cache — used when saving multidoc workflows */
  segmentation_profile?: string | null;
  /** Real segmentation settings resolved from linked segmentation cache */
  segmentation_settings?: {
    mode?: "homogeneous" | "heterogeneous" | string;
    expected_types?: string[];
    profile?: string;
  } | null;
}

export interface JobsResponse {
  jobs: Job[];
  total: number;
  limit: number;
  offset: number;
}

export interface JobStatsSummary {
  by_status: Record<string, number>;
  by_doc_type: Record<string, number>;
  totals: {
    input_tokens: number;
    output_tokens: number;
    estimated_cost: number;
  };
}

export type SchemaStatus = "draft" | "pending_review" | "published" | "rejected";

export interface SchemaOwner {
  id: string;
  username: string;
  display_name?: string;
}

export interface Schema {
  id: string;
  name: string;
  doc_type: string;
  description?: string;
  json_schema: Record<string, unknown>;
  parts_config?: Array<{
    name: string;
    label: string;
    page_range?: string | number[];
  }>;
  custom_instructions?: string;
  is_default: boolean;
  is_active: boolean;
  owner_id?: string;
  status: SchemaStatus;
  reviewed_by_id?: string;
  reviewed_at?: string;
  submit_notes?: string;
  review_notes?: string;
  owner?: SchemaOwner;
  reviewed_by?: SchemaOwner;
  created_at?: string;
  updated_at?: string;
}

export interface PendingReviewCount {
  pending_schemas: number;
}

export interface SchemaCreate {
  name: string;
  doc_type: string;
  json_schema: Record<string, unknown>;
  description?: string;
  parts_config?: Array<{
    name: string;
    label: string;
    page_range?: string | number[];
  }>;
  custom_instructions?: string;
}

export interface ProviderConfig {
  id: string;
  provider_name: string;
  provider_type: string;
  display_name?: string;
  config: Record<string, unknown>;
  has_api_key: boolean;
  is_enabled: boolean;
  last_test_at?: string;
  last_test_success?: boolean;
  created_at?: string;
  updated_at?: string;
}

// Document Intelligence Types
export interface ProviderRecommendation {
  provider: string;
  display_name: string;
  confidence: number;
  reasoning: string;
}

export interface DocumentTypeResult {
  primary_type: string;
  confidence: number;
  alternative_types: Array<{ type: string; confidence: number }>;
  signals: string[];
  language: string;
  classifier_used?: string;
  suggested_ocr?: ProviderRecommendation | null;
  suggested_llm?: ProviderRecommendation | null;
}

export interface DocumentSection {
  title: string;
  level: number;
  start_page: number;
  end_page: number;
  preview: string;
}

export interface DocumentTable {
  page: number;
  columns: string[];
  row_count: number;
  preview: string[][];
}

export interface DocumentFormField {
  label: string;
  type: string;
  page: number;
  required: boolean;
}

export interface StructureAnalysisResult {
  suggested_parts: Array<{
    name: string;
    label: string;
    description?: string;
    page_range: [number, number];
    priority?: number;
  }>;
  detected_sections: DocumentSection[];
  tables: DocumentTable[];
  form_fields: DocumentFormField[];
  total_pages: number;
  layout_type: string;
  confidence: number;
}

export interface SchemaField {
  name: string;
  display_name: string;
  type: string;
  description?: string;
  required: boolean;
  sample?: unknown;
  confidence: number;
}

export interface SchemaInferenceResult {
  schema_name: string;
  document_type: string;
  fields: SchemaField[];
  json_schema: Record<string, unknown>;
  confidence: number;
  suggestions: string[];
}

export interface ConsensusResult {
  success: boolean;
  data: Record<string, unknown>;
  overall_confidence: number;
  overall_agreement: number;
  providers_used: string[];
  conflicts: string[];
  needs_review: string[];
  processing_time: number;
  error?: string;
}

export interface OCRTextResult {
  success: boolean;
  text?: string;
  provider?: string;
  total_pages?: number;
  error?: string;
}

// Text highlighting types
export interface TextMatch {
  page: number;      // 1-indexed page number
  start: number;     // Character offset in page text
  end: number;       // Character offset end
  value: string;     // The matched text
  match_type: "exact" | "fuzzy" | "partial" | "region_exact";
  confidence: number;
  polygon?: number[][];  // Normalized 0-1 polygon [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
}

export interface RegionMatch {
  page: number;           // 1-indexed page number
  value: string;
  polygon: number[][];    // Normalized 0-1 polygon [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
  confidence: number;
  match_type: string;
}

// Segmentation types
export interface SegmentBoundaryResponse {
  page_after: number;
  confidence: number;
  signals: string[];
  detection_method: string;
}

export interface DocumentSegmentResponse {
  index: number;
  page_start: number;
  page_end: number;
  page_count: number;
  detected_type?: string;
  type_confidence: number;
  schema_id?: string;
  extraction_status: string;
}

/** Per-page document type from VLM pairwise classification */
export interface PageClassificationItem {
  page: number;
  document_type: string;
  confidence: number;
}

export interface SegmentationAnalysisResponse {
  success: boolean;
  segments: DocumentSegmentResponse[];
  boundaries: SegmentBoundaryResponse[];
  detection_method: string;
  total_pages: number;
  processing_time: number;
  llm_tokens_used: number;
  heuristic_only: boolean;
  error?: string;
  /** Present when VLM classified each page (heterogeneous or VLM profile) */
  page_classifications?: PageClassificationItem[];
  // Cache IDs for reuse in extraction
  document_cache_id?: string;
  segmentation_config_hash?: string;
}

export interface TextIndexResponse {
  success: boolean;
  fields: Record<string, TextMatch[]>;
  region_fields?: Record<string, RegionMatch[]>;
  page_count: number;
  detected_type?: string;
  type_confidence: number;
  schema_id?: string;
  extraction_status: string;
}

export interface SegmentationAnalysisResponse {
  success: boolean;
  segments: DocumentSegmentResponse[];
  boundaries: SegmentBoundaryResponse[];
  detection_method: string;
  total_pages: number;
  processing_time: number;
  llm_tokens_used: number;
  heuristic_only: boolean;
  error?: string;
  // Cache IDs for reuse in extraction
  document_cache_id?: string;
  segmentation_config_hash?: string;
}

export interface TextIndexResponse {
  success: boolean;
  fields: Record<string, TextMatch[]>;
  page_count: number;
  error?: string;
}

// User Settings Types
export interface UserSettings {
  // Document Classification Settings
  document_classifier: string;  // gemini, gpt-4o, mistral, pattern, custom
  pdf_extractor: string;        // pymupdf4llm, pymupdf, pdfplumber, pypdf
  fallback_ocr: string;         // mistral, paddle, azure, marker, surya
  min_text_threshold: number;   // Minimum chars before falling back to OCR

  // Default Extraction Providers
  default_ocr_provider: string;
  default_llm_provider: string;

  // Consensus Extraction Settings
  consensus_enabled: boolean;
  consensus_ocr_providers: string[];
  consensus_llm_providers: string[];
  consensus_threshold: number;

  // UI Preferences
  theme: string;  // light, dark, system
  compact_view: boolean;
  show_confidence_scores: boolean;
  auto_expand_results: boolean;

  // Processing Options
  auto_detect_document_type: boolean;
  auto_infer_schema: boolean;
  save_ocr_text: boolean;
  max_pages_for_classification: number;
}

export interface SettingsResponse {
  settings: UserSettings;
  defaults: UserSettings;
}

export interface SettingOption {
  options: string[];
  description: string;
  default: string | string[] | number | boolean;
  multi_select?: boolean;
}

export interface SettingsOptions {
  document_classifier: SettingOption;
  pdf_extractor: SettingOption;
  fallback_ocr: SettingOption;
  default_ocr_provider: SettingOption;
  default_llm_provider: SettingOption;
  consensus_ocr_providers: SettingOption;
  consensus_llm_providers: SettingOption;
  theme: SettingOption;
}

export interface User {
  id: string;
  username: string;
  email?: string;
  display_name?: string;
  role: "admin" | "contributor" | "viewer";
  settings: UserSettings;
  is_active: boolean;
  created_at?: string;
  updated_at?: string;
  last_login_at?: string;
}

// Workflow Types
export type WorkflowStatus = "active" | "inactive" | "archived";
export type WorkflowPublishStatus = "draft" | "pending_review" | "published" | "rejected";
export type WorkflowResponseMode = "sync" | "async";
export type WorkflowCollaboratorRole = "viewer" | "editor" | "admin";

export interface AutoDisableSettings {
  enabled: boolean;
  max_calls?: number;
  max_tokens?: number;
  max_cost?: number;
  period: "daily" | "monthly" | "total";
}

export interface WorkflowSettings {
  consensus_enabled?: boolean;
  consensus_ocr_providers?: string[];
  consensus_llm_providers?: string[];
  consensus_threshold?: number;
  auto_detect_document_type?: boolean;
  custom_instructions_override?: string;
  auto_disable?: AutoDisableSettings;
}

export interface WorkflowOwner {
  id: string;
  username: string;
  display_name?: string;
}

export interface WorkflowReviewer {
  id: string;
  username: string;
  display_name?: string;
}

export interface WorkflowSchema {
  id: string;
  name: string;
  doc_type: string;
}

/** Optional defaults for workflow multi-doc / segmentation (API uses same engine as Extract page) */
export interface WorkflowSegmentationSettings {
  mode?: "homogeneous" | "heterogeneous";
  /** Document types to guide boundary detection (e.g. from schema doc_type) */
  expected_types?: string[] | string;
  profile?: string;
  enable_llm_fallback?: boolean;
  confidence_threshold?: number;
  use_agents?: boolean;
}

/** Segmentation profile row (subset) from GET /api/segmentation-profiles */
export interface SegmentationProfileSummary {
  id: string;
  name: string;
  display_name: string;
  enable_section_splitting: boolean;
  default_detection_method?: string | null;
  ocr_method?: string | null;
}

export interface Workflow {
  id: string;
  name: string;
  slug: string;
  description?: string;
  owner_id: string;
  schema_id: string;
  ocr_provider: string;
  llm_provider: string;
  ocr_model_config?: Record<string, unknown>;
  /** When true, workflow /extract runs PDF segmentation then extracts each segment with this workflow's schema */
  is_multidoc?: boolean;
  segmentation_settings?: WorkflowSegmentationSettings | null;
  settings: WorkflowSettings;
  status: WorkflowStatus;
  status_reason?: string;
  status_changed_by_id?: string;
  status_changed_at?: string;
  response_mode: WorkflowResponseMode;
  webhook_url?: string;
  rate_limit_per_minute: number;
  rate_limit_per_day: number;
  created_at?: string;
  updated_at?: string;
  publish_status: WorkflowPublishStatus;
  reviewed_by_id?: string;
  reviewed_at?: string;
  submit_notes?: string;
  review_notes?: string;
  owner?: WorkflowOwner;
  schema_info?: WorkflowSchema;
  reviewed_by?: WorkflowReviewer;
  /** True when the current user may open settings, keys, and usage (owner, collaborator, or platform admin). */
  management_access?: boolean;
}

export interface WorkflowCreate {
  name: string;
  slug: string;
  description?: string;
  schema_id: string;
  ocr_provider: string;
  llm_provider: string;
  ocr_model_config?: Record<string, unknown>;
  settings?: WorkflowSettings;
  response_mode?: WorkflowResponseMode;
  webhook_url?: string;
  rate_limit_per_minute?: number;
  rate_limit_per_day?: number;
  is_multidoc?: boolean;
  segmentation_settings?: WorkflowSegmentationSettings;
}

export interface WorkflowUpdate {
  name?: string;
  description?: string;
  schema_id?: string;
  ocr_provider?: string;
  llm_provider?: string;
  ocr_model_config?: Record<string, unknown>;
  settings?: WorkflowSettings;
  status?: WorkflowStatus;
  status_change_reason?: string;
  response_mode?: WorkflowResponseMode;
  webhook_url?: string;
  rate_limit_per_minute?: number;
  rate_limit_per_day?: number;
  is_multidoc?: boolean;
  segmentation_settings?: WorkflowSegmentationSettings | null;
}

export interface WorkflowStatusChangeLog {
  id: string;
  workflow_id: string;
  changed_by_id: string;
  change_type: string;
  old_value?: string;
  new_value: string;
  reason?: string;
  created_at?: string;
  changed_by?: {
    id: string;
    username: string;
    display_name?: string;
  };
}

export interface PendingWorkflowReviewCount {
  pending_workflows: number;
}

export interface WorkflowCollaborator {
  id: string;
  workflow_id: string;
  user_id: string;
  role: WorkflowCollaboratorRole;
  added_by: string;
  created_at?: string;
  user?: {
    id: string;
    username: string;
    display_name?: string;
    email?: string;
  };
}

export interface WorkflowApiKey {
  id: string;
  workflow_id: string;
  name: string;
  key_prefix: string;
  is_active: boolean;
  expires_at?: string;
  last_used_at?: string;
  usage_count: number;
  created_by: string;
  created_at?: string;
  revoked_at?: string;
  key?: string; // Only present when creating a new key
}

export interface WorkflowUsageSummary {
  total_requests: number;
  successful_requests: number;
  failed_requests: number;
  avg_response_time_ms: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost: number;
}

export interface WorkflowUsageLog {
  id: string;
  workflow_id: string;
  api_key_id?: string;
  job_id?: string;
  request_ip?: string;
  request_size_bytes: number;
  document_name?: string;
  status_code: number;
  response_time_ms: number;
  success: boolean;
  error_message?: string;
  input_tokens: number;
  output_tokens: number;
  estimated_cost: number;
  created_at?: string;
}

export interface WorkflowUsageChartData {
  date: string;
  requests: number;
  successful: number;
  failed: number;
  avg_response_time_ms: number;
}

// Helper to get auth token
function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(AUTH_TOKEN_KEY);
}

// API client
class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string = API_BASE_URL) {
    this.baseUrl = baseUrl;
  }

  private async fetch<T>(
    endpoint: string,
    options?: RequestInit
  ): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;
    const token = getAuthToken();

    const headers: HeadersInit = {
      ...options?.headers,
    };

    // Add auth header if token exists
    if (token) {
      (headers as Record<string, string>)["Authorization"] = `Bearer ${token}`;
    }

    const response = await fetch(url, {
      ...options,
      headers,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "Request failed" }));
      const detail = (error as { detail?: unknown }).detail;
      if (
        response.status === 401 &&
        token &&
        detailLooksLikePasswordSessionInvalid(detail)
      ) {
        clearAuthAndGoToLoginWithFlash(
          formatApiErrorDetail(
            detail,
            "Your session ended because your password was changed. Please sign in again."
          )
        );
      }
      throw new Error(formatApiErrorDetail(detail, `HTTP error ${response.status}`));
    }

    return response.json();
  }

  // Providers
  async getProviders(): Promise<ProvidersResponse> {
    return this.fetch<ProvidersResponse>("/api/providers");
  }

  /** List segmentation profiles (for workflow save snapshot, lab UI, etc.) */
  async listSegmentationProfiles(): Promise<SegmentationProfileSummary[]> {
    return this.fetch<SegmentationProfileSummary[]>("/api/segmentation-profiles/");
  }

  async getOcrProviders(): Promise<Provider[]> {
    return this.fetch<Provider[]>("/api/providers/ocr");
  }

  async getLlmProviders(): Promise<Provider[]> {
    return this.fetch<Provider[]>("/api/providers/llm");
  }

  // Provider Configurations
  async listProviderConfigs(providerType?: string): Promise<ProviderConfig[]> {
    const params = providerType ? `?provider_type=${providerType}` : "";
    return this.fetch<ProviderConfig[]>(`/api/providers/configs${params}`);
  }

  async createProviderConfig(
    providerName: string,
    providerType: string,
    config: Record<string, unknown>,
    displayName?: string,
    isEnabled?: boolean
  ): Promise<ProviderConfig> {
    return this.fetch<ProviderConfig>("/api/providers/configs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        provider_name: providerName,
        provider_type: providerType,
        config,
        display_name: displayName,
        is_enabled: isEnabled ?? true,
      }),
    });
  }

  async deleteProviderConfig(configId: string): Promise<void> {
    await this.fetch<{ message: string }>(`/api/providers/configs/${configId}`, {
      method: "DELETE",
    });
  }

  async testProviderConnection(
    providerName: string,
    providerType: string,
    apiKey?: string,
    config?: Record<string, unknown>
  ): Promise<{ success: boolean; message: string; response_time_ms?: number }> {
    return this.fetch("/api/providers/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        provider_name: providerName,
        provider_type: providerType,
        api_key: apiKey,
        config,
      }),
    });
  }

  // Extraction
  async startExtraction(
    file: File,
    docType: string,
    ocrProvider: string,
    llmProvider: string,
    schemaId?: string,
    useAgents: boolean = false,
    ocrModelConfig?: Record<string, string>,
    workflowId?: string
  ): Promise<Job> {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("doc_type", docType);
    formData.append("ocr_provider", ocrProvider);
    formData.append("llm_provider", llmProvider);
    if (schemaId) {
      formData.append("schema_id", schemaId);
    }
    if (workflowId) {
      formData.append("workflow_id", workflowId);
    }
    formData.append("use_agents", String(useAgents));
    if (ocrModelConfig) {
      formData.append("ocr_model_config", JSON.stringify(ocrModelConfig));
    }

    return this.fetch<Job>("/api/extract", {
      method: "POST",
      body: formData,
    });
  }

  // Jobs
  async getJobs(limit: number = 50, offset: number = 0): Promise<JobsResponse> {
    return this.fetch<JobsResponse>(`/api/jobs?limit=${limit}&offset=${offset}`);
  }

  async listJobs(options?: { limit?: number; offset?: number; status?: string; doc_type?: string; workflow_id?: string }): Promise<JobsResponse> {
    const params = new URLSearchParams();
    if (options?.limit) params.append("limit", options.limit.toString());
    if (options?.offset) params.append("offset", options.offset.toString());
    if (options?.status) params.append("status", options.status);
    if (options?.doc_type) params.append("doc_type", options.doc_type);
    if (options?.workflow_id) params.append("workflow_id", options.workflow_id);
    const queryString = params.toString();
    return this.fetch<JobsResponse>(`/api/jobs${queryString ? `?${queryString}` : ""}`);
  }

  async getJobStatsSummary(): Promise<JobStatsSummary> {
    return this.fetch<JobStatsSummary>("/api/jobs/stats/summary");
  }

  async getJob(jobId: string): Promise<Job> {
    return this.fetch<Job>(`/api/jobs/${jobId}`);
  }

  async patchJobPartFields(
    jobId: string,
    partName: string,
    updates: FieldCorrectionUpdate[],
  ): Promise<PatchPartFieldsResponse> {
    return this.fetch<PatchPartFieldsResponse>(
      `/api/jobs/${jobId}/parts/${encodeURIComponent(partName)}/fields`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ updates }),
      },
    );
  }

  async getJobOcrText(jobId: string): Promise<OCRTextResult> {
    return this.fetch<OCRTextResult>(`/api/extract/${jobId}/ocr-text`);
  }

  async getJobTextIndex(
    jobId: string,
    partName?: string | null,
  ): Promise<TextIndexResponse> {
    const q =
      partName && partName.trim().length > 0
        ? `?part_name=${encodeURIComponent(partName.trim())}`
        : "";
    return this.fetch<TextIndexResponse>(`/api/extract/${jobId}/text-index${q}`);
  }

  async getJobSegments(jobId: string): Promise<DocumentSegmentResponse[]> {
    return this.fetch<DocumentSegmentResponse[]>(`/api/extract/${jobId}/segments`);
  }

  async deleteJob(jobId: string): Promise<void> {
    await this.fetch<{ message: string }>(`/api/jobs/${jobId}`, {
      method: "DELETE",
    });
  }

  // Schemas
  async getSchemas(docType?: string): Promise<Schema[]> {
    const params = docType ? `?doc_type=${encodeURIComponent(docType)}` : "";
    return this.fetch<Schema[]>(`/api/schemas${params}`);
  }

  // Alias for getSchemas
  async listSchemas(docType?: string): Promise<Schema[]> {
    return this.getSchemas(docType);
  }

  async getSchema(schemaId: string): Promise<Schema> {
    return this.fetch<Schema>(`/api/schemas/${schemaId}`);
  }

  async createSchema(
    name: string,
    docType: string,
    jsonSchema: Record<string, unknown>,
    description?: string,
    partsConfig?: Array<{ name: string; label: string; page_range?: string | number[] }>,
    customInstructions?: string
  ): Promise<Schema> {
    return this.fetch<Schema>("/api/schemas", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        name,
        doc_type: docType,
        json_schema: jsonSchema,
        description,
        parts_config: partsConfig,
        custom_instructions: customInstructions,
      }),
    });
  }

  async updateSchema(
    schemaId: string,
    updates: Partial<SchemaCreate> & { is_active?: boolean }
  ): Promise<Schema> {
    return this.fetch<Schema>(`/api/schemas/${schemaId}`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(updates),
    });
  }

  async deleteSchema(schemaId: string): Promise<void> {
    await this.fetch<{ message: string }>(`/api/schemas/${schemaId}`, {
      method: "DELETE",
    });
  }

  async getDefaultSchemas(): Promise<Schema[]> {
    return this.fetch<Schema[]>("/api/schemas/defaults");
  }

  async getMySchemas(): Promise<Schema[]> {
    return this.fetch<Schema[]>("/api/schemas/my");
  }

  async publishSchema(schemaId: string, comment: string): Promise<Schema> {
    return this.fetch<Schema>(`/api/schemas/${schemaId}/publish`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ comment }),
    });
  }

  // Admin schema review endpoints
  async getPendingSchemas(): Promise<Schema[]> {
    return this.fetch<Schema[]>("/api/admin/schemas/pending");
  }

  async getPendingSchemaCount(): Promise<PendingReviewCount> {
    return this.fetch<PendingReviewCount>("/api/admin/schemas/pending/count");
  }

  async reviewSchema(
    schemaId: string,
    approved: boolean,
    notes?: string
  ): Promise<Schema> {
    return this.fetch<Schema>(`/api/admin/schemas/${schemaId}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved, notes }),
    });
  }

  // Download extracted data
  getDownloadUrl(jobId: string, format: "json" | "csv" = "json"): string {
    return `${this.baseUrl}/api/jobs/${jobId}/download?format=${format}`;
  }

  // Get stored document URL for a job (legacy - use getDocumentBlob for authenticated requests)
  getDocumentUrl(jobId: string): string {
    return `${this.baseUrl}/api/jobs/${jobId}/document`;
  }

  // Get stored document as a blob (with authentication)
  async getDocumentBlob(jobId: string): Promise<Blob> {
    const url = `${this.baseUrl}/api/jobs/${jobId}/document`;
    const token = getAuthToken();

    const headers: HeadersInit = {};
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }

    const response = await fetch(url, { headers });

    if (!response.ok) {
      if (response.status === 401) {
        throw new Error("Authentication required to access document");
      }
      if (response.status === 403) {
        throw new Error("You do not have permission to access this document");
      }
      if (response.status === 404) {
        throw new Error("Document not found");
      }
      throw new Error(`Failed to fetch document: ${response.statusText}`);
    }

    return response.blob();
  }

  // ==========================================================================
  // User Settings
  // ==========================================================================

  async getSettings(): Promise<SettingsResponse> {
    return this.fetch<SettingsResponse>("/api/users/settings");
  }

  async updateSettings(settings: Partial<UserSettings>, merge: boolean = true): Promise<SettingsResponse> {
    return this.fetch<SettingsResponse>("/api/users/settings", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ settings, merge }),
    });
  }

  async patchSettings(settings: Partial<UserSettings>): Promise<SettingsResponse> {
    return this.fetch<SettingsResponse>("/api/users/settings", {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(settings),
    });
  }

  async resetSettings(): Promise<SettingsResponse> {
    return this.fetch<SettingsResponse>("/api/users/settings/reset", {
      method: "POST",
    });
  }

  async getSettingsOptions(): Promise<SettingsOptions> {
    return this.fetch<SettingsOptions>("/api/users/settings-options");
  }

  async getCurrentUser(): Promise<User> {
    return this.fetch<User>("/api/users/me");
  }

  // WebSocket URL for job updates
  getWebSocketUrl(jobId: string): string {
    const wsProtocol = this.baseUrl.startsWith("https") ? "wss" : "ws";
    const wsHost = this.baseUrl.replace(/^https?:\/\//, "");
    return `${wsProtocol}://${wsHost}/ws/jobs/${jobId}`;
  }

  // ============================================
  // Document Intelligence APIs
  // ============================================

  /**
   * Detect document type automatically
   * @param file - The document file to analyze
   * @param ocrProvider - Optional OCR provider (uses user settings if not provided)
   * @param classifier - Optional classifier (uses user settings if not provided): "pattern", "gpt-4o", "mistral", "gemini", "pere-custom-classifier"
   */
  async detectDocumentType(
    file: File,
    ocrProvider?: string,
    classifier?: string
  ): Promise<DocumentTypeResult> {
    const formData = new FormData();
    formData.append("file", file);
    // Only append if provided - backend will use user settings otherwise
    if (ocrProvider) {
      formData.append("ocr_provider", ocrProvider);
    }
    if (classifier) {
      formData.append("classifier", classifier);
    }

    return this.fetch<DocumentTypeResult>("/api/extract/detect-type", {
      method: "POST",
      body: formData,
    });
  }

  /**
   * Analyze document structure (sections, tables, form fields)
   * If ocrProvider not provided, backend uses user's fallback_ocr setting
   */
  async analyzeStructure(
    file: File,
    ocrProvider?: string
  ): Promise<StructureAnalysisResult> {
    const formData = new FormData();
    formData.append("file", file);
    if (ocrProvider) {
      formData.append("ocr_provider", ocrProvider);
    }

    return this.fetch<StructureAnalysisResult>("/api/extract/analyze-structure", {
      method: "POST",
      body: formData,
    });
  }

  /**
   * Auto-infer extraction schema from document.
   *
   * If ocrProvider and llmProvider are not provided, the backend will use
   * the user's settings (document_classifier for LLM, fallback_ocr for OCR).
   */
  async inferSchema(
    file: File,
    ocrProvider?: string,
    llmProvider?: string,
    guidance?: string
  ): Promise<SchemaInferenceResult> {
    const formData = new FormData();
    formData.append("file", file);
    // Only send providers if explicitly specified - let backend use user settings
    if (ocrProvider) {
      formData.append("ocr_provider", ocrProvider);
    }
    if (llmProvider) {
      formData.append("llm_provider", llmProvider);
    }
    if (guidance) {
      formData.append("guidance", guidance);
    }

    return this.fetch<SchemaInferenceResult>("/api/extract/infer-schema", {
      method: "POST",
      body: formData,
    });
  }

  /**
   * Extract with multi-provider consensus for high accuracy.
   * If providers not specified, backend uses user's consensus_ocr_providers and consensus_llm_providers settings.
   */
  async extractWithConsensus(
    file: File,
    ocrProviders?: string[],
    llmProviders?: string[],
    schemaId?: string,
    consensusThreshold?: number
  ): Promise<ConsensusResult> {
    const formData = new FormData();
    formData.append("file", file);
    if (ocrProviders && ocrProviders.length > 0) {
      formData.append("ocr_providers", ocrProviders.join(","));
    }
    if (llmProviders && llmProviders.length > 0) {
      formData.append("llm_providers", llmProviders.join(","));
    }
    if (consensusThreshold !== undefined) {
      formData.append("consensus_threshold", consensusThreshold.toString());
    }
    if (schemaId) {
      formData.append("schema_id", schemaId);
    }

    return this.fetch<ConsensusResult>("/api/extract/consensus", {
      method: "POST",
      body: formData,
    });
  }

  /**
   * Universal extraction with auto-detection.
   * If providers not specified, backend uses user's default_ocr_provider and default_llm_provider settings.
   */
  async startUniversalExtraction(
    file: File,
    options: {
      docType?: string;
      ocrProvider?: string;
      ocrModelConfig?: Record<string, any>;
      llmProvider?: string;
      schemaId?: string;
      autoDetect?: boolean;
    } = {}
  ): Promise<Job> {
    const formData = new FormData();
    formData.append("file", file);

    if (options.docType) {
      formData.append("doc_type", options.docType);
    }
    // Only send providers if explicitly specified - let backend use user settings
    if (options.ocrProvider) {
      formData.append("ocr_provider", options.ocrProvider);
    }
    if (options.ocrModelConfig) {
      formData.append("ocr_model_config", JSON.stringify(options.ocrModelConfig));
    }
    if (options.llmProvider) {
      formData.append("llm_provider", options.llmProvider);
    }
    formData.append("auto_detect", (options.autoDetect !== false).toString());

    if (options.schemaId) {
      formData.append("schema_id", options.schemaId);
    }

    return this.fetch<Job>("/api/extract", {
      method: "POST",
      body: formData,
    });
  }

  /**
   * Analyze document segmentation (detect boundaries in multi-document PDFs)
   * @param file - The document file to analyze
   * @param mode - Segmentation mode: "homogeneous" (same doc type) or "heterogeneous" (mixed types)
   * @param expectedTypes - Expected document types for better detection
   * @param enableLlmFallback - Use LLM when heuristics are uncertain
   * @param confidenceThreshold - Minimum confidence for boundary detection (0.0-1.0)
   * @param ocrProvider - Optional OCR provider for text extraction
   */
  async analyzeSegments(
    file: File,
    mode: "homogeneous" | "heterogeneous" = "homogeneous",
    expectedTypes: string[] = [],
    enableLlmFallback: boolean = false,
    confidenceThreshold: number = 0.6,
    ocrProvider?: string,
    profileId?: string,
    ocrModelConfig?: Record<string, string>
  ): Promise<SegmentationAnalysisResponse> {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("mode", mode);
    if (expectedTypes.length > 0) {
      // Backend expects comma-separated string
      formData.append("expected_types", expectedTypes.join(","));
    }
    formData.append("enable_llm_fallback", String(enableLlmFallback));
    formData.append("confidence_threshold", String(confidenceThreshold));
    if (ocrProvider) {
      formData.append("ocr_provider", ocrProvider);
    }
    if (profileId && profileId !== "auto") {
      formData.append("profile", profileId);
    }
    if (ocrModelConfig && Object.keys(ocrModelConfig).length > 0) {
      formData.append("ocr_model_config", JSON.stringify(ocrModelConfig));
    }

    return this.fetch<SegmentationAnalysisResponse>("/api/extract/segment-analysis", {
      method: "POST",
      body: formData,
    });
  }

  /**
   * Start extraction with document segmentation
   * @param file - The document file to extract
   * @param segmentSchemas - Map of segment index to schema ID
   * @param mode - Segmentation mode
   * @param expectedTypes - Expected document types
   * @param enableLlmFallback - Use LLM for boundary detection
   * @param confidenceThreshold - Minimum boundary confidence
   * @param ocrProvider - OCR provider to use
   * @param llmProvider - LLM provider to use
   * @param useAgents - Enable multi-agent extraction
   * @param profileId - Segmentation profile ID
   * @param documentCacheId - Cached OCR ID from analyze_segments (optional, for cache reuse)
   * @param segmentationConfigHash - Cached segmentation config hash (optional, for cache reuse)
   */
  async startSegmentedExtraction(
    file: File,
    segmentSchemas: Record<number, string>,
    mode: "homogeneous" | "heterogeneous" = "homogeneous",
    expectedTypes: string[] = [],
    enableLlmFallback: boolean = false,
    confidenceThreshold: number = 0.6,
    ocrProvider?: string,
    llmProvider?: string,
    useAgents: boolean = false,
    profileId?: string,
    documentCacheId?: string,
    segmentationConfigHash?: string,
    ocrModelConfig?: Record<string, string>
  ): Promise<Job> {
    const formData = new FormData();
    formData.append("file", file);
    // Backend expects JSON string for segment_schemas
    formData.append("segment_schemas", JSON.stringify(segmentSchemas));
    formData.append("mode", mode);
    if (expectedTypes.length > 0) {
      // Backend expects comma-separated string
      formData.append("expected_types", expectedTypes.join(","));
    }
    formData.append("enable_llm_fallback", String(enableLlmFallback));
    formData.append("confidence_threshold", String(confidenceThreshold));
    if (ocrProvider) {
      formData.append("ocr_provider", ocrProvider);
    }
    if (llmProvider) {
      formData.append("llm_provider", llmProvider);
    }
    formData.append("use_agents", String(useAgents));
    if (profileId && profileId !== "auto") {
      formData.append("profile", profileId);
    }
    if (ocrModelConfig && Object.keys(ocrModelConfig).length > 0) {
      formData.append("ocr_model_config", JSON.stringify(ocrModelConfig));
    }
    // Pass cache IDs for reuse
    if (documentCacheId) {
      formData.append("document_cache_id", documentCacheId);
    }
    if (segmentationConfigHash) {
      formData.append("segmentation_config_hash", segmentationConfigHash);
    }

    return this.fetch<Job>("/api/extract/start-segmented", {
      method: "POST",
      body: formData,
    });
  }

  /**
   * Convert a document to PDF for preview.
   * Returns a Blob containing the PDF data.
   *
   * This is used to preview non-PDF documents (DOCX, XLSX, etc.)
   * by converting them server-side and displaying the result.
   */
  async convertForPreview(file: File): Promise<Blob> {
    const formData = new FormData();
    formData.append("file", file);

    const token = getAuthToken();
    const response = await fetch(`${this.baseUrl}/api/extract/preview-convert`, {
      method: "POST",
      body: formData,
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });

    if (!response.ok) {
      const errorText = await response.text();
      let errorMessage = `Failed to convert document: ${response.status}`;
      try {
        const errorJson = JSON.parse(errorText);
        errorMessage = errorJson.detail || errorMessage;
      } catch {
        // Use default error message
      }
      throw new Error(errorMessage);
    }

    return response.blob();
  }

  // ==========================================================================
  // Workflows
  // ==========================================================================

  async listWorkflows(options?: {
    status?: WorkflowStatus;
    includeCollaborated?: boolean;
    limit?: number;
    offset?: number;
  }): Promise<Workflow[]> {
    const params = new URLSearchParams();
    if (options?.status) params.append("status", options.status);
    if (options?.includeCollaborated !== undefined) {
      params.append("include_collaborated", options.includeCollaborated.toString());
    }
    if (options?.limit) params.append("limit", options.limit.toString());
    if (options?.offset) params.append("offset", options.offset.toString());
    const queryString = params.toString();
    return this.fetch<Workflow[]>(`/api/workflows${queryString ? `?${queryString}` : ""}`);
  }

  async getWorkflow(workflowId: string): Promise<Workflow> {
    return this.fetch<Workflow>(`/api/workflows/${workflowId}`);
  }

  async createWorkflow(data: WorkflowCreate): Promise<Workflow> {
    return this.fetch<Workflow>("/api/workflows", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
  }

  async updateWorkflow(workflowId: string, data: WorkflowUpdate): Promise<Workflow> {
    return this.fetch<Workflow>(`/api/workflows/${workflowId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
  }

  async deleteWorkflow(workflowId: string): Promise<void> {
    await this.fetch<{ status: string }>(`/api/workflows/${workflowId}`, {
      method: "DELETE",
    });
  }

  // Workflow Publishing
  async submitWorkflowForReview(workflowId: string, comment: string): Promise<Workflow> {
    return this.fetch<Workflow>(`/api/workflows/${workflowId}/publish`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ comment }),
    });
  }

  async getWorkflowStatusHistory(workflowId: string, limit = 50): Promise<WorkflowStatusChangeLog[]> {
    return this.fetch<WorkflowStatusChangeLog[]>(`/api/workflows/${workflowId}/status-history?limit=${limit}`);
  }

  // Admin workflow review endpoints
  async getPendingWorkflows(): Promise<Workflow[]> {
    return this.fetch<Workflow[]>("/api/admin/workflows/pending");
  }

  async getPendingWorkflowCount(): Promise<PendingWorkflowReviewCount> {
    return this.fetch<PendingWorkflowReviewCount>("/api/admin/workflows/pending/count");
  }

  async reviewWorkflow(
    workflowId: string,
    approved: boolean,
    notes?: string
  ): Promise<Workflow> {
    return this.fetch<Workflow>(`/api/admin/workflows/${workflowId}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved, notes }),
    });
  }

  // Collaborators
  async listCollaborators(workflowId: string): Promise<WorkflowCollaborator[]> {
    return this.fetch<WorkflowCollaborator[]>(`/api/workflows/${workflowId}/collaborators`);
  }

  async addCollaborator(
    workflowId: string,
    userId: string,
    role: WorkflowCollaboratorRole
  ): Promise<WorkflowCollaborator> {
    return this.fetch<WorkflowCollaborator>(`/api/workflows/${workflowId}/collaborators`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, role }),
    });
  }

  async updateCollaborator(
    workflowId: string,
    userId: string,
    role: WorkflowCollaboratorRole
  ): Promise<WorkflowCollaborator> {
    return this.fetch<WorkflowCollaborator>(`/api/workflows/${workflowId}/collaborators/${userId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role }),
    });
  }

  async removeCollaborator(workflowId: string, userId: string): Promise<void> {
    await this.fetch<{ status: string }>(`/api/workflows/${workflowId}/collaborators/${userId}`, {
      method: "DELETE",
    });
  }

  // API Keys
  async listApiKeys(workflowId: string, includeRevoked = false): Promise<WorkflowApiKey[]> {
    const params = includeRevoked ? "?include_revoked=true" : "";
    return this.fetch<WorkflowApiKey[]>(`/api/workflows/${workflowId}/keys${params}`);
  }

  async createApiKey(
    workflowId: string,
    name: string,
    expiresInDays?: number
  ): Promise<WorkflowApiKey> {
    return this.fetch<WorkflowApiKey>(`/api/workflows/${workflowId}/keys`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, expires_in_days: expiresInDays }),
    });
  }

  async revokeApiKey(workflowId: string, keyId: string): Promise<void> {
    await this.fetch<{ status: string }>(`/api/workflows/${workflowId}/keys/${keyId}`, {
      method: "DELETE",
    });
  }

  async rotateApiKey(workflowId: string, keyId: string): Promise<WorkflowApiKey> {
    return this.fetch<WorkflowApiKey>(`/api/workflows/${workflowId}/keys/${keyId}/rotate`, {
      method: "POST",
    });
  }

  async revealApiKey(workflowId: string, keyId: string): Promise<{ id: string; key: string }> {
    return this.fetch<{ id: string; key: string }>(`/api/workflows/${workflowId}/keys/${keyId}/reveal`);
  }

  // Usage Analytics
  async getWorkflowUsage(
    workflowId: string,
    period: "today" | "week" | "month" | "all" = "today"
  ): Promise<WorkflowUsageSummary> {
    return this.fetch<WorkflowUsageSummary>(`/api/workflows/${workflowId}/usage?period=${period}`);
  }

  async getWorkflowUsageLogs(
    workflowId: string,
    options?: { limit?: number; offset?: number; successOnly?: boolean }
  ): Promise<{ logs: WorkflowUsageLog[]; total: number; limit: number; offset: number }> {
    const params = new URLSearchParams();
    if (options?.limit) params.append("limit", options.limit.toString());
    if (options?.offset) params.append("offset", options.offset.toString());
    if (options?.successOnly !== undefined) params.append("success_only", options.successOnly.toString());
    const queryString = params.toString();
    return this.fetch(`/api/workflows/${workflowId}/usage/logs${queryString ? `?${queryString}` : ""}`);
  }

  async getWorkflowUsageChart(workflowId: string, days = 7): Promise<WorkflowUsageChartData[]> {
    return this.fetch<WorkflowUsageChartData[]>(`/api/workflows/${workflowId}/usage/chart?days=${days}`);
  }
}

// Export singleton instance
export const api = new ApiClient();

// Export class for custom instances
export { ApiClient };
