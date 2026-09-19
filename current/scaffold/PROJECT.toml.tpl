schema_version = "1.9.0"
template_version = "1.9.1"

[project]
name = {{PROJECT_NAME_TOML}}
slug = {{PROJECT_SLUG_TOML}}
description = {{PROJECT_DESCRIPTION_TOML}}
profile = {{PROJECT_PROFILE_TOML}}
created_date = "{{CREATED_DATE}}"
root = {{PROJECT_ROOT_TOML}}
default_language = "zh-CN"

[governance]
mode = {{GOVERNANCE_MODE_TOML}}
initialized_mode = {{GOVERNANCE_MODE_TOML}}
selection_reason = {{GOVERNANCE_REASON_TOML}}
promoted_at = ""
standard_mode_templates_sha256 = "{{STANDARD_MODE_TEMPLATES_SHA256}}"

[workflow]
role_model = "tool_agnostic_multi_agent"
user_zero_command = true
direct_next_batch = true
manual_acceptance_before_stage_advance = true
semantic_docs_updated_by_ai = true
state_and_log_updated_by_tool = true
require_manager_review = true
strict_document_first = true
block_batch_close_with_open_changes = true
block_stage_advance_with_open_changes = true
pass_requires_all_tests_passed = true
partial_and_blocked_keep_batch_open = true
project_closure_is_terminal = true
closed_release_versions_are_permanently_frozen = true
reopened_release_version_is_locked = true
recover_pending_changes_on_entry = true

[role_policy]
single_active_project_manager = true
analysis_agents_default_read_only = true
parallel_analysis_allowed = true
parallel_code_execution_allowed = {{PARALLEL_CODE_EXECUTION_ALLOWED}}
integration_review_required_for_parallel_execution = true
shared_semantic_documents_single_writer = true
tool_bindings_optional = true
tool_names_non_authoritative = true

[permissions.project_owner]
may_approve_product_direction = true
may_approve_high_risk_actions = true
may_record_manual_acceptance = true

[permissions.project_manager_agent]
may_change_requirements = true
may_change_acceptance_criteria = true
may_change_architecture = true
may_change_development_plan = true
may_update_shared_semantic_documents = true
may_assign_tasks = true
may_close_batch = true
may_close_stage_after_user_acceptance = true

[permissions.analysis_review_agent]
may_read_all_project_information = true
may_modify_code = false
may_modify_shared_semantic_documents = false
may_close_batch = false
may_close_stage = false

[permissions.code_executor]
may_modify_assigned_code = true
may_modify_assigned_tests = true
may_run_commands_and_tests = true
may_suggest_document_changes = true
may_change_requirements = false
may_change_architecture = false
may_modify_shared_semantic_documents = false
may_record_user_acceptance = false
may_close_stage = false

[permissions.integration_reviewer]
may_review_parallel_changes = true
may_run_integration_tests = true
may_modify_shared_semantic_documents = false
may_record_user_acceptance = false
may_close_stage = false

[context]
loading_protocol = "hot-task-cold"
raw_evidence_default_read = false
context_index_is_derived = true
default_entry_mode = "{{DEFAULT_ENTRY_MODE}}"
active_batch_mode = "light"
stage_transition_mode = "full"
use_conversation_memory_in_same_window = true
prefer_diff_for_changed_documents = true
never_read_logs_by_default = true
require_full_audit_before_stage_transition = true
project_memory_authoritative = false

[testing]
levels = ["L1", "L2", "L3", "L4", "L5"]
parent_minimum = "L3"
high_risk_minimum = "L4"
stage_minimum = "L4"
release_minimum = "L5"

[requirement_policy]
id_prefix = "R"
initial_revision = 1
revision_on_semantic_change_only = true
stable_acceptance_ids = true
current_document_latest_revision_only = true
preserve_removed_requirements = true
trace_implementation = true
trace_tests = true
trace_manual_acceptance = true
release_baseline_required = {{RELEASE_BASELINE_REQUIRED}}
require_optimistic_version_lock = true
require_real_change_for_semantic_revision = true
link_trace_fields_only = true

[delivery_policy]
generate_only_from_release_baseline = true
customer_docs_separate_from_internal_docs = true
require_no_placeholders = true
require_actual_ui_verification = true
require_owner_final_acceptance = true
freeze_git_head = true
freeze_artifact_hashes = true
immutable_release_baselines = true
transactional_release_baseline_updates = true
transactional_project_closure = true
artifacts_must_resolve_inside_project_root = true

[authorization]
local_reversible_code_changes = true
local_normal_database_write = true
destructive_database_operation = false
real_external_api = false
paid_external_action = false
git_push = false
git_tag = false
release = false
production_deployment = false
credential_change = false

[documents]
required = {{COMMON_REQUIRED_DOCUMENTS_TOML}}
standard_required = {{STANDARD_REQUIRED_DOCUMENTS_TOML}}

[limits]
agents_max_lines = 120
agents_max_kb = 18
role_boundaries_max_lines = 260
role_boundaries_max_kb = 35
current_state_max_lines = 240
current_state_max_kb = 30
project_memory_max_lines = 300
project_memory_max_kb = 30
project_rules_max_kb = 70
requirements_max_kb = 100
requirement_changelog_max_kb = 100
traceability_max_kb = 100
architecture_max_kb = 80
decisions_max_kb = 80
pitfalls_max_kb = 60
monthly_log_max_kb = 100
generic_document_max_kb = 100
runtime_max_files = 12
runtime_max_kb = 1024

[automation]
auto_resume_on_ai_entry = true
require_structured_batch_request = true
require_structured_batch_result = true
require_change_capture_before_rework = true
require_document_hash_verification = true
require_git_worktree_fingerprint = true
auto_update_state_on_finish = true
append_monthly_log_on_finish = true
auto_generate_handoff = true
run_health_check_on_finish = true
check_memory_writeback = true
rotate_monthly_log = true
runtime_open_items_only = true
install_git_hooks = true
auto_update_project_memory_status = true
generate_context_reading_plan = true
validate_role_boundaries = true
validate_requirement_registry = true
auto_sync_requirement_documents = true
require_release_baseline_for_delivery = true
verify_customer_delivery_documents = true
require_final_acceptance_before_closure = {{FINAL_ACCEPTANCE_REQUIRED}}
require_reproducible_regression_tests = true

# Opt-in protocol; legacy requests never gain new guarantees implicitly.
[acceptance_infrastructure]
protocol = "acceptance/1"
contract_revision_independent = true
volatile_metadata_default = "audit_only"
