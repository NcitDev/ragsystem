from rag.agents.repo_agent import (
    build_eval_metrics,
    build_context_query,
    build_documentation_queries,
    build_repo_agent_plan,
    build_reuse_queries,
    collect_modules,
    collect_tests,
    collect_top_files,
    disambiguate_symbols,
    expand_domain_terms,
    extract_symbol_candidates,
    is_architecture_task,
    should_use_semantic_fallback,
    total_source_tokens,
)
from rag.agents.retrieval import SearchPlan


def test_extract_symbol_candidates_prefers_code_like_names():
    symbols = extract_symbol_candidates(
        "Make successful paid order handling call setupAppStateForNewOrder before trackPaymentFinished"
    )

    assert symbols == ["setupAppStateForNewOrder", "trackPaymentFinished"]


def test_build_context_query_combines_planner_queries_and_symbols():
    plan = SearchPlan(
        queries=["waitForPayedOrder setupAppStateForNewOrder", "analytics completion"],
        strategy="graph_walk",
    )

    query = build_context_query(
        "successful paid order analytics",
        plan,
        ["trackPaymentFinished"],
    )

    assert "waitForPayedOrder" in query
    assert "setupAppStateForNewOrder" in query
    assert "trackPaymentFinished" in query


def test_expand_domain_terms_maps_product_language_to_code_terms():
    terms = expand_domain_terms(
        "successful paid order resets state before tracking analytics"
    )

    assert "waitForPayedOrder" in terms
    assert "setupAppStateForNewOrder" in terms
    assert "trackPaymentFinished" in terms


def test_expand_domain_terms_maps_analytics_event_language_to_existing_events():
    terms = expand_domain_terms(
        "Add analytics event only for still being created paid order"
    )

    assert "OrderIsBeingCreated" in terms
    assert "PaymentAnalytics" in terms
    assert "orderPollingAfterPaymentStart" in terms
    assert "START_ORDER_POLLING_AFTER_PAYMENT" in terms


def test_extract_symbol_candidates_ignores_lowercase_prose():
    symbols = extract_symbol_candidates("smallest safe tracking analytics")

    assert symbols == []


def test_build_repo_agent_plan_disables_semantic_fallback_when_requested():
    plan = SearchPlan(queries=["paid order"], strategy="lod_drill")

    repo_plan = build_repo_agent_plan(
        "trackPaymentFinished paid order resets state",
        plan,
        allow_semantic_fallback=False,
    )

    assert repo_plan.semantic_fallback_allowed is False
    assert "trackPaymentFinished" in repo_plan.symbols
    assert "setupAppStateForNewOrder" in repo_plan.symbols


def test_build_repo_agent_plan_adds_reuse_checks_for_new_analytics_events():
    plan = SearchPlan(queries=["paid order analytics"], strategy="graph_walk")

    repo_plan = build_repo_agent_plan(
        "Add analytics event only for still being created paid order",
        plan,
    )

    assert repo_plan.reuse_queries
    assert "PaymentAnalytics" in repo_plan.reuse_queries[0]
    assert "START_ORDER_POLLING_AFTER_PAYMENT" in repo_plan.reuse_queries[0]
    assert repo_plan.documentation_queries
    assert "analytics event catalog" in repo_plan.documentation_queries[0]


def test_build_reuse_queries_adds_architecture_boundary_search():
    queries = build_reuse_queries(
        "Evaluate whether reset logic can move into another module",
        ["CheckoutService", "StateAnalyzer"],
    )

    assert queries
    assert "dependencies" in queries[0]
    assert "CheckoutService" in queries[0]


def test_build_documentation_queries_adds_module_boundary_docs_search():
    queries = build_documentation_queries(
        "Extract code into another module and report public API boundaries",
        ["CheckoutService"],
    )

    assert queries == ["module ownership dependency rules public API boundaries CheckoutService"]


def test_build_repo_agent_plan_enables_architecture_and_call_tree_checks():
    plan = SearchPlan(queries=["checkout reset module"], strategy="global")

    repo_plan = build_repo_agent_plan(
        "Evaluate whether setupAppStateForNewOrder can move into another module",
        plan,
    )

    assert is_architecture_task(repo_plan.query)
    assert repo_plan.architecture_query
    assert "build" in repo_plan.architecture_query
    assert repo_plan.call_tree_symbols == ["setupAppStateForNewOrder"]


def test_disambiguate_symbols_groups_same_name_definitions():
    ambiguities = disambiguate_symbols(
        {
            "definitions": [
                {"name": "setupAppStateForNewOrder", "file_path": "a/CheckoutService.kt"},
                {"name": "setupAppStateForNewOrder", "file_path": "b/StateAnalyzer.kt"},
            ]
        }
    )

    assert ambiguities
    assert ambiguities[0]["symbol"] == "setupAppStateForNewOrder"


def test_collect_evidence_bundle_parts_from_packs_and_understand():
    pack = {
        "slices": [
            {"file_path": "src/Foo.kt", "lines": "1-2", "name": "foo", "score": 10},
            {"file_path": "src/test/FooTest.kt", "lines": "5-8", "name": "testFoo", "score": 9},
        ]
    }
    understand = {"modules": [{"path": "src", "file_count": 2, "score": 3.0, "kinds": {"class": 1}}]}

    assert collect_top_files(pack)[0]["file_path"] == "src/Foo.kt"
    assert collect_tests(pack)[0]["file_path"] == "src/test/FooTest.kt"
    assert collect_modules(understand)[0]["path"] == "src"


def test_build_eval_metrics_tracks_core_fields():
    first = {"file_path": "src/Foo.kt", "why_included": "ast_index_symbol"}
    exact = {"slices": [first], "total_source_tokens": 50}

    metrics = build_eval_metrics(
        first_slice=first,
        exact_pack=exact,
        semantic_pack=None,
        total_tokens=50,
    )

    assert metrics["first_relevant_rank"] == 1
    assert metrics["first_relevant_file"] == "src/Foo.kt"
    assert metrics["source_tokens"] == 50
    assert metrics["embeddings_used"] is False
    assert metrics["whole_file_reads_avoided"] is True


def test_should_use_semantic_fallback_when_exact_pack_is_thin():
    pack = {"slices": [{"why_included": "exact_or_lexical_match"}]}

    assert should_use_semantic_fallback(pack, min_exact_slices=3)


def test_should_not_use_semantic_fallback_for_enough_exact_slices():
    pack = {
        "slices": [
            {"why_included": "ast_index_symbol"},
            {"why_included": "exact_or_lexical_match"},
            {"why_included": "ast_index_search_symbol"},
        ]
    }

    assert not should_use_semantic_fallback(pack, min_exact_slices=3)


def test_total_source_tokens_sums_present_packs():
    assert total_source_tokens(
        {"total_source_tokens": 10},
        None,
        {"total_source_tokens": 7},
    ) == 17
