use serde_json::Value;

use rag_contracts::SearchPlan;
use rag_retrieval::repo_agent::{
    build_repo_agent_plan, collect_modules, collect_tests, compact_slice, disambiguate_symbols,
    expand_domain_terms, extract_symbol_candidates, infer_risks, total_source_tokens,
};

#[test]
fn repo_agent_bundle_matches_python_fixture() {
    let fixture: Value = serde_json::from_str(include_str!(
        "../../../tests/rust-compat/r4/repo_agent_bundle.json"
    ))
    .expect("fixture json");

    let query = "Add analytics event only for still being created paid order and move setupAppStateForNewOrder into another module";
    let planner = SearchPlan {
        queries: vec!["paid order analytics".to_owned()],
        strategy: rag_contracts::SearchStrategy::GraphWalk,
        ..SearchPlan::default()
    };
    let plan = build_repo_agent_plan(query, planner, true);
    assert_eq!(plan.query, fixture["plan"]["query"]);
    assert_eq!(plan.context_query, fixture["plan"]["context_query"]);
    assert_eq!(
        plan.symbols,
        serde_json::from_value::<Vec<String>>(fixture["plan"]["symbols"].clone()).unwrap()
    );

    let exact = serde_json::json!({
        "slices": [
            {"file_path": "src/main.py", "name": "main", "lines": "1-3", "score": 1.0},
            {"file_path": "tests/test_main.py", "name": "test_main", "lines": "1-3", "score": 1.0}
        ],
        "total_source_tokens": 44
    });
    let understand = serde_json::json!({
        "modules": [
            {"path": "src", "file_count": 12, "score": 0.9, "kinds": {"py": 3}}
        ]
    });
    let ambiguity_value = serde_json::json!({"symbol": "CheckoutService"});
    let ambiguity_value_2 = serde_json::json!({"symbol": "StateAnalyzer"});

    let tests = collect_tests(&[Some(&exact)], 8);
    assert_eq!(tests.len(), 1);
    assert_eq!(total_source_tokens(&[Some(&exact)]), 44);

    let modules = collect_modules(Some(&understand), 1);
    assert_eq!(modules[0]["path"], "src");

    let ambiguities = disambiguate_symbols(&serde_json::json!({
        "definitions": [
            {"name": "same", "file_path": "a/Foo.kt"},
            {"name": "same", "file_path": "b/Foo.kt"}
        ]
    }));
    assert!(ambiguities.contains_key("same"));

    let risks = infer_risks(
        "analytics event module move",
        true,
        &[ambiguity_value, ambiguity_value_2],
        &[],
    );
    assert_eq!(
        risks,
        serde_json::from_value::<Vec<String>>(fixture["risks"].clone()).unwrap()
    );

    let compact = compact_slice(&serde_json::json!({
        "file_path": "src/main.py",
        "name": "main",
        "lines": "1-3",
        "score": 1.0,
        "why_included": "exact_or_lexical_match"
    }));
    assert_eq!(compact, fixture["compact"]);

    assert_eq!(
        extract_symbol_candidates(
            "Make successful paid order handling call setupAppStateForNewOrder before trackPaymentFinished",
            12
        ),
        serde_json::from_value::<Vec<String>>(fixture["symbols"].clone()).unwrap()
    );
    assert_eq!(
        expand_domain_terms("successful paid order resets state before tracking analytics"),
        serde_json::from_value::<Vec<String>>(fixture["domain_terms"].clone()).unwrap()
    );
}
